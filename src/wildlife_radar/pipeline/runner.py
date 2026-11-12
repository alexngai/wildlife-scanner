"""The job graph: ``wildlife-radar run <target> --region R`` (docs/design/data-platform.md §2–3).

Each job records a manifest when it completes: its version (a timestamp), the versions of the
jobs it read, and what it produced. A job is **up to date** when its latest complete manifest
records the current versions of all its inputs and, for jobs that pull from outside sources,
it is younger than its cadence (``max_age``). ``run`` walks the graph to the target and runs
only stale jobs; a failed job leaves no complete manifest, so it runs again next time.

Jobs operate on the region's work store (a DuckDB file); serving reads only published bundles,
so builds never block the API. Global reference jobs (identity, statuses) are per region for
now and will move to a shared store with the lake (data-platform.md §8).
"""

from __future__ import annotations

import json
import os
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from wildlife_radar.core.time import utcnow
from wildlife_radar.regions import Region, region_dir


@dataclass
class JobContext:
    region: Region
    region_path: Path | None
    """Folder of the region pack (statuses.yaml, datasets.yaml), if any."""
    db: Path
    lake: Path
    now: datetime
    log: Callable[[str], None] = print
    params: dict = field(default_factory=dict)

    def store(self):
        from wildlife_radar.storage import ObservationStore

        return ObservationStore(self.db)

    def registry(self):
        from wildlife_radar.baseline.effort import DatasetRegistry

        path = self.params.get("datasets") or (
            self.region_path / "datasets.yaml" if self.region_path else None
        )
        return DatasetRegistry.load(Path(path)) if path else DatasetRegistry()

    def statuses_path(self) -> Path | None:
        path = self.params.get("statuses") or (
            self.region_path / "statuses.yaml" if self.region_path else None
        )
        return Path(path) if path and Path(path).exists() else None

    def config(self):
        from wildlife_radar.baseline.builder import BaselineConfig

        return BaselineConfig(since_year=self.region.pipeline.since_year)

    def backtest_split(self) -> datetime:
        d = self.region.pipeline.backtest_split or date(self.now.year - 1, 1, 1)
        return datetime(d.year, d.month, d.day, tzinfo=UTC)

    def conditions_split(self) -> datetime:
        d = self.region.pipeline.conditions_split or date(self.now.year - 2, 1, 1)
        return datetime(d.year, d.month, d.day, tzinfo=UTC)


@dataclass(frozen=True)
class Job:
    name: str
    deps: tuple[str, ...]
    run: Callable[[JobContext], dict]
    max_age: timedelta | None = None
    description: str = ""


# -- Job bodies ---------------------------------------------------------------------------


def _snapshot(ctx: JobContext) -> dict:
    with ctx.store() as store:
        n = store.conn.execute("SELECT count(*) FROM observations").fetchone()[0]
    if not n:
        raise RuntimeError("the store has no observations: run ingest-snapshot first")
    return {"observations": n, "note": "registered existing ingest"}


def _repairs(ctx: JobContext) -> dict:
    from wildlife_radar.connectors.gbif_events import fetch_event_ids
    from wildlife_radar.storage.repair import (
        missing_event_ids,
        redate_from_event_ids,
        set_event_ids,
    )

    out = {}
    with ctx.store() as store:
        for key, entry in ctx.registry().datasets.items():
            if not (entry.event_id_date and entry.placeholder_dates):
                continue
            for d in entry.placeholder_dates:
                if missing_event_ids(store.conn, key, [d]):
                    set_event_ids(
                        store.conn, key, fetch_event_ids(key, d.isoformat(), ctx.region.bbox)
                    )
            out[key] = redate_from_event_ids(
                store.conn, key, entry.event_id_date, entry.placeholder_dates
            )
    return {"redated": out}


def _crosswalk(ctx: JobContext) -> dict:
    from wildlife_radar.profilegen.identity import (
        IDENTITY_SCHEMA,
        IdentityResolver,
        save_identities,
    )

    with ctx.store() as store:
        store.conn.execute(IDENTITY_SCHEMA)
        # Species-level names with enough records to get a baseline; only names not yet cached.
        names = [
            n
            for (n,) in store.conn.execute(
                """
                SELECT mode(taxon_name) FROM observations
                WHERE taxon_id IS NOT NULL GROUP BY taxon_id HAVING count(*) >= 5
                EXCEPT SELECT query_name FROM taxon_identity
                """
            ).fetchall()
            if n
        ]
        resolver = IdentityResolver()
        for start in range(0, len(names), 200):
            save_identities(
                store.conn, resolver.resolve_many(names[start : start + 200], gbif="fallback")
            )
            ctx.log(f"crosswalk: {min(start + 200, len(names))}/{len(names)}")
    return {"new_names": len(names)}


def _aliases(ctx: JobContext) -> dict:
    from wildlife_radar.storage.aliases import build_alias_table

    with ctx.store() as store:
        return build_alias_table(store.conn)


def _signals(ctx: JobContext) -> dict:
    from wildlife_radar.conditions.daily import (
        COOPS_PRODUCTS,
        CoopsDailyFetcher,
        ensure_schema,
        store_rows,
    )

    fetcher = CoopsDailyFetcher()
    end = ctx.now.date()
    n = 0
    with ctx.store() as store:
        ensure_schema(store.conn)
        for st in ctx.region.tide_stations:
            last = store.conn.execute(
                "SELECT max(day) FROM signal_daily WHERE station_id = ?", [st.station_id]
            ).fetchone()[0]
            start = (last - timedelta(days=3)) if last else date(2010, 1, 1)
            for product in COOPS_PRODUCTS:
                n += store_rows(
                    store.conn, fetcher.observations(st.station_id, st.lon, product, start, end)
                )
            n += store_rows(
                store.conn, fetcher.tides(st.station_id, st.lon, start, end + timedelta(days=30))
            )
    return {"daily_values": n}


LIVE_WINDOW_DAYS = 60
LIVE_MAX_RECORDS = 20_000


def _live(ctx: JobContext) -> dict:
    """Recent iNaturalist records for the region (docs/design/data-platform.md §4).

    Records updated since the previous run's cursor (with an hour of overlap), observed within
    the last ``LIVE_WINDOW_DAYS`` days; keyset-paged at ≤1 request/s and capped per run, so a
    backlog is caught up over several runs. Copies of records already ingested from snapshots
    replace them (same iNaturalist id).
    """
    from wildlife_radar.connectors.base import ObservationQuery
    from wildlife_radar.connectors.inaturalist import INaturalistConnector

    previous = latest(ctx.lake, ctx.region.id, "live")
    cursor = (
        datetime.fromisoformat(previous["outputs"]["cursor"])
        if previous and previous.get("status") == "complete"
        else ctx.now - timedelta(days=3)
    )
    started = utcnow()
    query = ObservationQuery(
        bbox=ctx.region.bbox,
        start=(ctx.now - timedelta(days=LIVE_WINDOW_DAYS)).date(),
        updated_since=cursor - timedelta(hours=1),
        limit=LIVE_MAX_RECORDS,
    )
    with ctx.store() as store:
        n = store.add(INaturalistConnector().fetch(query))
    capped = n >= LIVE_MAX_RECORDS
    return {
        "records": n,
        # When capped, keep the old cursor so the next run continues the backlog.
        "cursor": (cursor if capped else started).isoformat(),
        "capped": capped,
    }


def _baseline(ctx: JobContext) -> dict:
    from wildlife_radar.baseline import build_baseline

    with ctx.store() as store:
        report = build_baseline(
            store.conn,
            region_id=ctx.region.id,
            bbox=ctx.region.bbox,
            config=ctx.config(),
            registry=ctx.registry(),
        )
    return {"taxa": report.taxa, "visits": report.visits, "survey_trials": report.survey_trials}


def _backtest(ctx: JobContext) -> dict:
    from wildlife_radar.baseline import backtest_baseline

    with ctx.store() as store:
        scores = backtest_baseline(
            store.conn,
            region_id=ctx.region.id,
            bbox=ctx.region.bbox,
            split=ctx.backtest_split(),
            config=ctx.config(),
            registry=ctx.registry(),
        )
    return {"scored": len(scores), "passing": sum(s.passes for s in scores)}


def _tiers(ctx: JobContext) -> dict:
    from wildlife_radar.connectors.inaturalist_taxa import InatTaxonStatusProvider
    from wildlife_radar.policy.statuses import (
        CachedStatusProvider,
        RegionStatusFile,
        build_tier_table,
    )

    providers = []
    statuses = ctx.statuses_path()
    if statuses:
        providers.append(RegionStatusFile(statuses))
    else:
        ctx.log("warning: no curated statuses file; state-listed populations won't be raised")
    with ctx.store() as store:
        providers.append(
            CachedStatusProvider(
                store.conn,
                InatTaxonStatusProvider(
                    ctx.region.inat_place_scopes,
                    innermost_place=ctx.region.inat_innermost_place,
                ),
            )
        )
        decisions = build_tier_table(
            store.conn, region_id=ctx.region.id, scopes=ctx.region.scopes, providers=providers
        )
    counts: dict[str, int] = {}
    for d in decisions.values():
        counts[d.tier.name] = counts.get(d.tier.name, 0) + 1
    return {"tiers": counts, "curated_statuses": str(statuses) if statuses else None}


def _conditions(ctx: JobContext) -> dict:
    from wildlife_radar.conditions import terms_from_profile
    from wildlife_radar.conditions.levels import run_conditions
    from wildlife_radar.profiles import ProfileLibrary

    lib = ProfileLibrary()
    specs = {}
    for pid in lib.ids(kind="species"):
        terms, _ = terms_from_profile(lib.resolve(pid))
        if terms:
            specs[pid] = terms
    with ctx.store() as store:
        known = {
            t
            for (t,) in store.conn.execute(
                "SELECT DISTINCT taxon_id FROM prior_taxa WHERE region_id = ?", [ctx.region.id]
            ).fetchall()
        }
        specs = {t: terms for t, terms in specs.items() if t in known}
        reports = run_conditions(
            store.conn,
            region_id=ctx.region.id,
            bbox=ctx.region.bbox,
            split=ctx.conditions_split(),
            end=None,
            specs=specs,
            station_coords={s.station_id: (s.lat, s.lon) for s in ctx.region.tide_stations},
            config=ctx.config(),
            registry=ctx.registry(),
        )
    passing = [
        f"{r.taxon_id}:{r.group_id}:L{lv.level}" for r in reports for lv in r.levels if lv.passes
    ]
    return {"fitted": len(reports), "passing": passing}


def _publish(ctx: JobContext) -> dict:
    from wildlife_radar.pipeline.publish import publish_bundle

    curated = []
    statuses = ctx.statuses_path()
    if statuses:
        doc = yaml.safe_load(statuses.read_text(encoding="utf-8")) or {}
        curated = [e["taxon_id"] for e in doc.get("statuses", [])]
    with ctx.store() as store:
        result = publish_bundle(
            store.conn,
            ctx.region,
            ctx.lake / "publish",
            curated_ids=curated,
            registry=ctx.registry(),
            config=ctx.config(),
            now=ctx.now,
            allow_findings=bool(ctx.params.get("allow_findings")),
            inputs=ctx.params.get("_inputs"),
        )
    return {"version": result.version, "rows": result.rows, "audit": result.findings}


JOBS: dict[str, Job] = {
    j.name: j
    for j in (
        Job("snapshot", (), _snapshot, None, "registered observation ingest (ingest-snapshot)"),
        Job("repairs", ("snapshot",), _repairs, None, "re-date placeholder-dated records"),
        Job("crosswalk", ("snapshot",), _crosswalk, timedelta(days=30), "identities, new names"),
        Job("aliases", ("crosswalk", "repairs"), _aliases, None, "merge renamed species"),
        Job("signals", (), _signals, timedelta(hours=20), "daily station signals (NOAA)"),
        Job("live", ("snapshot",), _live, timedelta(minutes=30), "recent iNaturalist records"),
        Job("baseline", ("aliases", "repairs"), _baseline, None, "Level-0 statistics"),
        Job("backtest", ("baseline",), _backtest, None, "Level-0 gates"),
        Job("tiers", ("baseline", "crosswalk"), _tiers, timedelta(days=30), "statuses → tiers"),
        Job("conditions", ("baseline",), _conditions, timedelta(days=30), "Levels 1–2, scorecard"),
        Job(
            "publish",
            ("tiers", "backtest", "conditions", "signals", "live"),
            _publish,
            None,
            "audit-gated serving bundle",
        ),
    )
}


# -- Manifests and planning -----------------------------------------------------------------


def _manifest_dir(lake: Path, region_id: str, job: str) -> Path:
    return lake / "manifests" / f"region={region_id}" / job


def latest(lake: Path, region_id: str, job: str) -> dict | None:
    path = _manifest_dir(lake, region_id, job) / "latest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _record(lake: Path, region_id: str, manifest: dict) -> None:
    folder = _manifest_dir(lake, region_id, manifest["job"])
    folder.mkdir(parents=True, exist_ok=True)
    body = json.dumps(manifest, indent=2, default=str)
    (folder / f"{manifest['version']}.json").write_text(body, encoding="utf-8")
    tmp = folder / ".latest.tmp"
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, folder / "latest.json")


def order(target: str, jobs: dict[str, Job] | None = None) -> list[str]:
    """Jobs needed for ``target``, dependencies first."""
    jobs = jobs or JOBS
    seen: list[str] = []

    def visit(name: str, stack: tuple[str, ...]) -> None:
        if name in stack:
            raise ValueError(f"cycle: {' -> '.join([*stack, name])}")
        if name in seen:
            return
        for dep in jobs[name].deps:
            visit(dep, (*stack, name))
        seen.append(name)

    if target not in jobs:
        raise KeyError(f"unknown job {target!r}; jobs: {', '.join(jobs)}")
    visit(target, ())
    return seen


def staleness(
    lake: Path, region_id: str, name: str, now: datetime, jobs: dict[str, Job] | None = None
) -> str | None:
    """Why ``name`` must run, or ``None`` if it is up to date."""
    job = (jobs or JOBS)[name]
    m = latest(lake, region_id, name)
    if m is None or m.get("status") != "complete":
        return "never completed"
    for dep in job.deps:
        dm = latest(lake, region_id, dep)
        if dm is None or m.get("inputs", {}).get(dep) != dm.get("version"):
            return f"input {dep} changed"
    if job.max_age is not None:
        made = datetime.fromisoformat(m["created_at"])
        if now - made > job.max_age:
            return f"older than {job.max_age}"
    return None


def run(
    target: str,
    ctx: JobContext,
    *,
    force: tuple[str, ...] = (),
    dry_run: bool = False,
    jobs: dict[str, Job] | None = None,
) -> list[dict]:
    """Run stale jobs up to ``target``; returns the plan with each job's outcome."""
    jobs = jobs or JOBS
    results = []
    failed: set[str] = set()
    for name in order(target, jobs):
        blocked = [d for d in jobs[name].deps if d in failed]
        if blocked:
            # Independent branches keep running; jobs downstream of a failure wait.
            failed.add(name)
            results.append({"job": name, "reason": f"blocked by {', '.join(blocked)}"})
            continue
        reason = (
            "forced" if name in force else staleness(ctx.lake, ctx.region.id, name, ctx.now, jobs)
        )
        entry = {"job": name, "reason": reason or "up to date"}
        results.append(entry)
        if reason is None or dry_run:
            continue
        inputs = {
            dep: (latest(ctx.lake, ctx.region.id, dep) or {}).get("version")
            for dep in jobs[name].deps
        }
        version = utcnow().strftime("%Y%m%dT%H%M%S%f")
        ctx.params["_inputs"] = inputs
        ctx.log(f"== {name} ({entry['reason']})")
        manifest = {
            "job": name,
            "region": ctx.region.id,
            "version": version,
            "inputs": inputs,
            "created_at": utcnow().isoformat(),
            "code": _code_version(),
        }
        try:
            manifest["outputs"] = jobs[name].run(ctx)
            manifest["status"] = "complete"
        except Exception as exc:
            manifest["status"] = "failed"
            manifest["error"] = f"{type(exc).__name__}: {exc}"
            manifest["traceback"] = traceback.format_exc(limit=5)
            _record(ctx.lake, ctx.region.id, manifest)
            entry["outcome"] = manifest["error"]
            failed.add(name)
            continue
        manifest["finished_at"] = utcnow().isoformat()
        _record(ctx.lake, ctx.region.id, manifest)
        entry["outcome"] = manifest["outputs"]
    return results


def _code_version() -> str:
    head = Path(__file__).resolve().parents[3] / ".git" / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            ref = (head.parent / ref[5:]).read_text(encoding="utf-8").strip()
        return f"git:{ref[:7]}"
    except OSError:
        return "unknown"


def context(region_arg: str, db: str, lake: str, params: dict | None = None) -> JobContext:
    from wildlife_radar.regions import load_region

    region = load_region(region_arg)
    path = Path(region_arg)
    pack = path.parent if path.suffix else region_dir(region.id)
    return JobContext(
        region=region,
        region_path=pack if pack.exists() else None,
        db=Path(db),
        lake=Path(lake),
        now=utcnow(),
        params=params or {},
    )
