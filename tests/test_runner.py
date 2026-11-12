from datetime import UTC, datetime, timedelta

from wildlife_radar.pipeline.runner import Job, JobContext, latest, order, run, staleness
from wildlife_radar.regions import load_region


def make_jobs(calls: list[str], fail: set[str] | None = None):
    fail = fail or set()

    def body(name):
        def go(ctx):
            calls.append(name)
            if name in fail:
                raise RuntimeError(f"{name} broke")
            return {"ok": name}

        return go

    return {
        "source": Job("source", (), body("source"), timedelta(hours=1)),
        "a": Job("a", ("source",), body("a")),
        "b": Job("b", ("a",), body("b")),
        "c": Job("c", ("source",), body("c")),
        "top": Job("top", ("b", "c"), body("top")),
    }


def ctx(tmp_path, now=None):
    return JobContext(
        region=load_region("socal"),
        region_path=None,
        db=tmp_path / "store.duckdb",
        lake=tmp_path / "lake",
        now=now or datetime(2026, 11, 12, tzinfo=UTC),
        log=lambda _m: None,
    )


def test_order_is_dependencies_first():
    jobs = make_jobs([])
    plan = order("top", jobs)
    assert plan.index("source") < plan.index("a") < plan.index("b") < plan.index("top")
    assert set(plan) == {"source", "a", "b", "c", "top"}


def test_runs_only_stale_jobs(tmp_path):
    calls: list[str] = []
    jobs = make_jobs(calls)
    c = ctx(tmp_path)
    run("top", c, jobs=jobs)
    assert sorted(calls) == ["a", "b", "c", "source", "top"]
    calls.clear()
    results = run("top", c, jobs=jobs)
    assert calls == [] and {r["reason"] for r in results} == {"up to date"}
    # Forcing a mid-graph job reruns it and everything downstream of it, nothing else.
    run("top", c, jobs=jobs, force=("a",))
    assert calls == ["a", "b", "top"]
    assert latest(c.lake, "socal", "top")["inputs"]["b"] == latest(c.lake, "socal", "b")["version"]


def test_cadence_makes_source_jobs_stale(tmp_path):
    calls: list[str] = []
    jobs = make_jobs(calls)
    c = ctx(tmp_path, now=datetime.now(UTC))
    run("c", c, jobs=jobs)
    later = datetime.now(UTC) + timedelta(hours=2)
    assert staleness(c.lake, "socal", "source", later, jobs) == "older than 1:00:00"
    assert staleness(c.lake, "socal", "c", later, jobs) is None  # its input hasn't changed yet


def test_failure_stops_and_reruns_next_time(tmp_path):
    calls: list[str] = []
    c = ctx(tmp_path)
    results = {r["job"]: r for r in run("top", c, jobs=make_jobs(calls, fail={"b"}))}
    assert "broke" in results["b"]["outcome"]
    assert results["top"]["reason"] == "blocked by b"
    assert "c" in calls and "top" not in calls  # independent branch still ran
    assert latest(c.lake, "socal", "b")["status"] == "failed"
    calls.clear()
    run("top", c, jobs=make_jobs(calls))
    assert calls == ["b", "top"]  # finished jobs are not repeated


def test_live_job_advances_its_cursor(tmp_path, monkeypatch):
    from wildlife_radar.connectors import inaturalist
    from wildlife_radar.pipeline import runner
    from wildlife_radar.storage import ObservationStore
    from wildlife_radar.synthetic import SyntheticWorld

    queries = []

    def fake_fetch(self, query):
        queries.append(query)
        return iter(SyntheticWorld(observers=5, visits_per_observer=10).generate()[:5])

    monkeypatch.setattr(inaturalist.INaturalistConnector, "fetch", fake_fetch)
    c = ctx(tmp_path, now=datetime.now(UTC))
    with ObservationStore(c.db) as store:
        store.add(SyntheticWorld(observers=5, visits_per_observer=10).generate()[20:21])
    jobs = {k: runner.JOBS[k] for k in ("snapshot", "live")}
    first = {r["job"]: r for r in run("live", c, jobs=jobs)}
    assert first["live"]["outcome"]["records"] == 5
    assert queries[0].bbox == c.region.bbox and queries[0].updated_since is not None
    cursor = latest(c.lake, "socal", "live")["outputs"]["cursor"]
    # The next run (forced: within its 30-minute cadence) asks only for newer updates.
    run("live", c, jobs=jobs, force=("live",))
    assert queries[1].updated_since == datetime.fromisoformat(cursor) - timedelta(hours=1)


def test_region_pack_inherits_curated_files():
    from wildlife_radar.pipeline.runner import context

    c = context("sandiego", "unused.duckdb", "unused-lake")
    assert c.region.inherits == "california"
    assert c.statuses_path().parts[-2:] == ("california", "statuses.yaml")
    assert any(e.event_id_date for e in c.registry().datasets.values())  # shared registry


def test_live_job_pulls_registry_live_datasets_from_gbif(tmp_path):
    from wildlife_radar.pipeline import runner
    from wildlife_radar.storage import ObservationStore
    from wildlife_radar.synthetic import SyntheticWorld

    registry = tmp_path / "datasets.yaml"
    registry.write_text(
        "datasets:\n"
        "  whale-feed: {name: Live whale feed, live: true}\n"
        "  archive: {name: Old survey}\n",
        encoding="utf-8",
    )
    records = SyntheticWorld(observers=3, visits_per_observer=5).generate()

    class Fake:
        def __init__(self, items, fail=False):
            self.items, self.fail, self.queries = items, fail, []

        def fetch(self, query):
            self.queries.append(query)
            if self.fail:
                raise RuntimeError("GBIF is down")
            return iter(self.items)

    c = ctx(tmp_path, now=datetime.now(UTC))
    with ObservationStore(c.db) as store:
        store.add(records[:1])
    gbif = Fake(records[5:8])
    c.params.update({"datasets": str(registry), "_inaturalist": Fake(records[1:3]), "_gbif": gbif})
    jobs = {k: runner.JOBS[k] for k in ("snapshot", "live")}
    out = {r["job"]: r for r in run("live", c, jobs=jobs)}["live"]["outcome"]
    assert out["records"] == 2 and out["gbif_records"] == 3
    assert gbif.queries[0].dataset_keys == ("whale-feed",)  # only datasets marked live
    # A GBIF failure is recorded; the job (and publishing after it) carries on.
    c.params["_gbif"] = Fake([], fail=True)
    out = {r["job"]: r for r in run("live", c, jobs=jobs, force=("live",))}["live"]["outcome"]
    assert "GBIF is down" in out["gbif_error"] and "gbif_cursor" in out


def test_registry_live_datasets_are_live_in_training_views(tmp_path):
    from wildlife_radar.baseline.builder import BaselineConfig, create_training_view
    from wildlife_radar.baseline.effort import DatasetEntry, DatasetRegistry
    from wildlife_radar.storage import ObservationStore
    from wildlife_radar.synthetic import DEFAULT_SPECIES, SyntheticWorld

    world = SyntheticWorld(
        observers=5,
        visits_per_observer=10,
        survey_sites=((32.85, -117.27),),
        survey_species=DEFAULT_SPECIES[:1],
    )
    st = ObservationStore()
    st.add(world.generate())
    bbox = world.bbox
    counts = {}
    for live in (False, True):
        registry = DatasetRegistry(
            datasets={world.survey_dataset: DatasetEntry(effort_class="dive_survey", live=live)}
        )
        create_training_view(st.conn, BaselineConfig(since_year=None), bbox, registry)
        counts[live] = st.conn.execute(
            "SELECT count(*) FILTER (WHERE live) FROM _obs WHERE effort_class = 'dive_survey'"
        ).fetchone()[0]
    assert counts[False] == 0 and counts[True] > 0


def test_repairs_resume_after_an_interruption(tmp_path, monkeypatch):
    from datetime import date

    from wildlife_radar.connectors import gbif_events
    from wildlife_radar.connectors.base import ConnectorError
    from wildlife_radar.pipeline import runner
    from wildlife_radar.storage import ObservationStore

    registry = tmp_path / "datasets.yaml"
    registry.write_text(
        "datasets:\n  kelp: {placeholder_dates: [2023-11-30], event_id_date: '_(\\d{8})_'}\n",
        encoding="utf-8",
    )
    c = ctx(tmp_path)
    c.params["datasets"] = str(registry)
    with ObservationStore(c.db) as store:
        for i in range(6):
            store.conn.execute(
                "INSERT INTO observations (dedupe_key, obs_id, source_id, source_record_id, "
                "dataset_key, local_date, lon) VALUES (?, ?, 'gbif', ?, 'kelp', ?, -117.2)",
                [f"k{i}", f"o{i}", str(i), date(2023, 11, 30)],
            )
    events = [(f"SITE_2020010{e + 1}_A", 2) for e in range(3)]  # records 0-1, 2-3, 4-5
    index = {name: e for e, (name, _) in enumerate(events)}
    fetched: list[str] = []
    fail = {"on": "SITE_20200103_A"}

    def fake_fetch(key, chunk, **_kw):
        out = []
        for name, _n in chunk:
            if name == fail["on"]:
                raise ConnectorError("rate limited (HTTP 429)")
            fetched.append(name)
            e = index[name]
            out += [(str(2 * e), name), (str(2 * e + 1), name)]
        return out

    monkeypatch.setattr(gbif_events, "event_ids", lambda *a, **k: events)
    monkeypatch.setattr(gbif_events, "fetch_events", fake_fetch)
    monkeypatch.setattr(runner, "REPAIR_CHUNK", 1)
    jobs = {"repairs": Job("repairs", (), runner._repairs)}
    # Rate-limited part-way: the job completes with what it has (re-dated records are kept,
    # the rest stay excluded) and reports what remains.
    first = run("repairs", c, jobs=jobs)[0]["outcome"]
    assert "429" in first["stopped"] and first["remaining_events"] == 1
    assert first["redated"]["kelp"] == 4
    fail["on"] = None
    second = run("repairs", c, jobs=jobs, force=("repairs",))[0]["outcome"]
    assert fetched == ["SITE_20200101_A", "SITE_20200102_A", "SITE_20200103_A"]  # no repeats
    assert second["redated"]["kelp"] == 2 and second["remaining_events"] == 0
    # Nothing left to do: unchanged, so downstream jobs keep their inputs.
    v = latest(c.lake, "socal", "repairs")["version"]
    third = run("repairs", c, jobs=jobs, force=("repairs",))[0]["outcome"]
    assert third.get("unchanged") and latest(c.lake, "socal", "repairs")["version"] == v
    with ObservationStore(c.db) as store:
        days = store.conn.execute("SELECT DISTINCT local_date FROM observations").fetchall()
    assert sorted(d for (d,) in days) == [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]


def test_crosswalk_also_resolves_curated_status_names(tmp_path, monkeypatch):
    from wildlife_radar.pipeline import runner
    from wildlife_radar.profilegen import identity
    from wildlife_radar.storage import ObservationStore

    statuses = tmp_path / "statuses.yaml"
    statuses.write_text(
        "statuses:\n  - {taxon_id: euphydryas-editha, authority: ESA, code: E, scope: us-ca}\n",
        encoding="utf-8",
    )
    asked: list[str] = []
    monkeypatch.setattr(
        identity.IdentityResolver,
        "resolve_many",
        lambda self, names, **kw: asked.extend(names) or [],
    )
    c = ctx(tmp_path)
    c.params["statuses"] = str(statuses)
    with ObservationStore(c.db):
        pass
    out = run("crosswalk", c, jobs={"crosswalk": Job("crosswalk", (), runner._crosswalk)})[0]
    assert isinstance(out["outcome"], dict), out["outcome"]
    assert "Euphydryas editha" in asked


def test_unchanged_result_keeps_downstream_up_to_date(tmp_path):
    """A job rerun by a changed input that reports the same result keeps its version."""
    calls: list[str] = []
    state = {"same": False}

    def mid(_c):
        calls.append("mid")
        return {"unchanged": True} if state["same"] else {"n": 1}

    jobs = {
        "source": Job("source", (), lambda _c: calls.append("source") or {}),
        "mid": Job("mid", ("source",), mid),
        "down": Job("down", ("mid",), lambda _c: calls.append("down") or {}),
    }
    c = ctx(tmp_path)
    run("down", c, jobs=jobs)
    v = latest(c.lake, "socal", "mid")["version"]
    state["same"] = True
    calls.clear()
    run("down", c, jobs=jobs, force=("source",))
    assert calls == ["source", "mid"]  # down did not rerun
    assert latest(c.lake, "socal", "mid")["version"] == v
    assert staleness(c.lake, "socal", "mid", c.now, jobs) is None  # new inputs recorded
