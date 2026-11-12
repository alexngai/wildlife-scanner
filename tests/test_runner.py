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
