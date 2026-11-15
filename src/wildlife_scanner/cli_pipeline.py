"""Pipeline CLI commands: ingest → build-baseline → evaluate-baseline → build-tiers → query/serve.

The database defaults to ``data/wildlife-scanner.duckdb`` (``data/`` is git-ignored).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from wildlife_scanner.regions import load_region

PUBLISH_URL_ENV = "WILDLIFE_SCANNER_PUBLISH_URL"
"""Object storage for published versions, e.g. ``s3://wildlife-scanner-publish``."""
LAKE_URL_ENV = "WILDLIFE_SCANNER_LAKE_URL"
"""Private object storage for the shared lake layers (``ref``, ``norm``), e.g.
``r2://<account id>/<bucket>/lake``."""

DEFAULT_DB = "data/wildlife-scanner.duckdb"


def _region(args: argparse.Namespace):
    from wildlife_scanner.regions import load_region

    return load_region(args.region)


def _statuses_path(args: argparse.Namespace, region):
    """Curated statuses: ``--statuses``, the region pack's file, or one next to a region file."""
    from pathlib import Path

    from wildlife_scanner.regions import region_dir

    if getattr(args, "statuses", None):
        path = Path(args.statuses)
        if not path.exists():
            raise SystemExit(f"error: {path} not found")
        return path
    from wildlife_scanner.regions import pack_file

    pack = Path(args.region).parent if Path(args.region).suffix else region_dir(region.id)
    return pack_file(region, "statuses.yaml", pack)


def _registry(args: argparse.Namespace):
    from pathlib import Path

    from wildlife_scanner.baseline.effort import DatasetRegistry
    from wildlife_scanner.regions import pack_file, region_dir

    region = _region(args)
    if getattr(args, "datasets", None):
        return DatasetRegistry.load(Path(args.datasets))
    pack = Path(args.region).parent if Path(args.region).suffix else region_dir(region.id)
    path = pack_file(region, "datasets.yaml", pack)
    return DatasetRegistry.load(path) if path else DatasetRegistry()


def _print(model) -> None:
    if hasattr(model, "model_dump_json"):
        print(model.model_dump_json(indent=2))
    else:
        print(json.dumps(model, indent=2, default=str))


def cmd_ingest_snapshot(args: argparse.Namespace) -> int:
    from wildlife_scanner.connectors.gbif_snapshot import (
        SnapshotReport,
        snapshot_observations,
        snapshot_url,
    )
    from wildlife_scanner.storage import ObservationStore

    region = _region(args)
    paths = args.paths or [snapshot_url(args.snapshot_date)]
    report = SnapshotReport()
    with ObservationStore(args.db) as store:
        n = store.add(snapshot_observations(paths, region.bbox, report, limit=args.limit))
        print(json.dumps({"stored": n, **report.__dict__, "total": store.count()}, indent=2))
    return 0


def cmd_ingest_api(args: argparse.Namespace) -> int:
    from wildlife_scanner.connectors.base import ObservationQuery
    from wildlife_scanner.storage import ObservationStore

    if args.source == "inaturalist":
        from wildlife_scanner.connectors.inaturalist import INaturalistConnector as Connector
    else:
        from wildlife_scanner.connectors.gbif import GBIFConnector as Connector
    region = _region(args)
    query = ObservationQuery(
        taxon_name=args.taxon,
        bbox=region.bbox,
        start=date.fromisoformat(args.since) if args.since else None,
        end=date.fromisoformat(args.until) if args.until else None,
        limit=args.limit,
    )
    with ObservationStore(args.db) as store:
        n = store.add(Connector().fetch(query))
        print(json.dumps({"stored": n, "total": store.count()}, indent=2))
    return 0


def cmd_build_baseline(args: argparse.Namespace) -> int:
    from wildlife_scanner.baseline import BaselineConfig, build_baseline
    from wildlife_scanner.storage import ObservationStore

    region = _region(args)
    cfg = BaselineConfig(res=args.res, min_visits=args.min_visits, since_year=args.since_year)
    with ObservationStore(args.db) as store:
        report = build_baseline(
            store.conn,
            region_id=region.id,
            bbox=region.bbox,
            config=cfg,
            registry=_registry(args),
        )
    _print(report.__dict__)
    return 0


def cmd_evaluate_baseline(args: argparse.Namespace) -> int:
    from wildlife_scanner.baseline import BaselineConfig, backtest_baseline
    from wildlife_scanner.storage import ObservationStore

    region = _region(args)
    split = datetime.fromisoformat(args.split).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC) if args.end else None
    with ObservationStore(args.db) as store:
        scores = backtest_baseline(
            store.conn,
            region_id=region.id,
            bbox=region.bbox,
            split=split,
            end=end,
            config=BaselineConfig(
                res=args.res, min_visits=args.min_visits, since_year=args.since_year
            ),
            registry=_registry(args),
            groups=args.groups.split(",") if args.groups else None,
        )
    passed = sum(s.passes for s in scores)
    print(
        f"{passed}/{len(scores)} taxon × effort groups beat the range-only reference "
        "(Brier skill > 0)"
    )
    for s in scores[: args.show]:
        print(
            f"  {s.taxon_id:<36} {s.group_id:<24} n={s.n_test:<7} hits={s.n_pos:<6} "
            f"BSS={s.bss:+.3f}"
        )
    return 0


def cmd_annotate_datasets(args: argparse.Namespace) -> int:
    from wildlife_scanner.baseline.effort import date_spikes
    from wildlife_scanner.connectors.gbif_datasets import fetch_dataset_meta
    from wildlife_scanner.storage import ObservationStore

    with ObservationStore(args.db) as store:
        n = fetch_dataset_meta(store.conn, min_records=args.min_records)
        rows = store.conn.execute(
            "SELECT type, count(*) FROM dataset_meta GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
        spikes = date_spikes(store.conn)
    print(
        json.dumps(
            {
                "fetched": n,
                "by_type": dict(rows),
                # Candidates for `placeholder_dates` in the region's datasets.yaml.
                "suspicious_dates": [
                    {"dataset_key": k, "date": d.isoformat(), "records": r, "share": round(sh, 3)}
                    for k, d, r, sh in spikes
                ],
            },
            indent=2,
        )
    )
    return 0


def cmd_build_tiers(args: argparse.Namespace) -> int:
    from wildlife_scanner.policy.statuses import (
        CachedStatusProvider,
        RegionStatusFile,
        build_tier_table,
    )
    from wildlife_scanner.storage import ObservationStore

    region = _region(args)
    statuses = _statuses_path(args, region)
    if statuses is None:
        print(
            "warning: no curated statuses file found (regions/<id>/statuses.yaml, a "
            "statuses.yaml next to the region file, or --statuses). Taxa listed only there "
            "(e.g. state-listed populations) will not be raised.",
            file=sys.stderr,
        )
    with ObservationStore(args.db) as store:
        providers = [RegionStatusFile(statuses)] if statuses else []
        if not args.offline:
            from wildlife_scanner.connectors.inaturalist_taxa import (
                InatTaxonStatusProvider,
                RecordCache,
            )

            # A refresh bypasses both the parsed lookups and the raw records.
            max_age = timedelta(0) if args.refresh_statuses else timedelta(days=90)
            providers.append(
                CachedStatusProvider(
                    store.conn,
                    max_age=max_age,
                    inner=InatTaxonStatusProvider(
                        region.inat_place_scopes,
                        innermost_place=region.inat_innermost_place,
                        records=RecordCache(store.conn, max_age=max_age),
                    ),
                )
            )
        decisions = build_tier_table(
            store.conn, region_id=region.id, scopes=region.scopes, providers=providers
        )
    counts: dict[str, int] = {}
    for d in decisions.values():
        counts[d.tier.name] = counts.get(d.tier.name, 0) + 1
    print(
        json.dumps(
            {
                "taxa": len(decisions),
                "tiers": counts,
                "curated_statuses": str(statuses) if statuses else None,
            },
            indent=2,
        )
    )
    if args.offline:
        print("note: offline mode — taxa without a completed status lookup fail closed (COARSE)")
    return 0


def cmd_repair_dates(args: argparse.Namespace) -> int:
    """Re-date placeholder-dated records from their event ids (registry: event_id_date)."""
    from wildlife_scanner.connectors.gbif_events import fetch_event_ids
    from wildlife_scanner.storage import ObservationStore
    from wildlife_scanner.storage.repair import (
        missing_event_ids,
        redate_from_event_ids,
        set_event_ids,
    )

    region = _region(args)
    registry = _registry(args)
    report = {}
    with ObservationStore(args.db) as store:
        for key, entry in registry.datasets.items():
            if not (entry.event_id_date and entry.placeholder_dates):
                continue
            fetched = 0
            if not args.no_fetch:
                for d in entry.placeholder_dates:
                    if missing_event_ids(store.conn, key, [d]):
                        print(f"fetching event ids for {key} on {d}…", file=sys.stderr)
                        fetched += set_event_ids(
                            store.conn,
                            key,
                            fetch_event_ids(key, d.isoformat(), region.bbox, workers=args.workers),
                        )
            redated = redate_from_event_ids(
                store.conn, key, entry.event_id_date, entry.placeholder_dates
            )
            report[key] = {
                "event_ids_fetched": fetched,
                "redated": redated,
                "still_on_placeholder_dates": store.conn.execute(
                    "SELECT count(*) FROM observations WHERE dataset_key = ? "
                    "AND local_date IN (SELECT unnest(?))",
                    [key, list(entry.placeholder_dates)],
                ).fetchone()[0],
            }
    print(json.dumps(report, indent=2))
    if report:
        print("note: rebuild the baseline to use the repaired dates", file=sys.stderr)
    return 0


def cmd_audit_tiers(args: argparse.Namespace) -> int:
    import duckdb
    import yaml

    from wildlife_scanner.policy.audit import audit_tiers, summarize

    region = _region(args)
    statuses = _statuses_path(args, region)
    curated = []
    if statuses:
        doc = yaml.safe_load(statuses.read_text(encoding="utf-8")) or {}
        curated = [e["taxon_id"] for e in doc.get("statuses", [])]
    conn = duckdb.connect(args.db, read_only=True)
    try:
        findings = audit_tiers(conn, region.id, curated)
    finally:
        conn.close()
    report = summarize(findings)
    report["findings"] = report["findings"][: args.show]
    report["curated_statuses"] = str(statuses) if statuses else None
    print(json.dumps(report, indent=2))
    return 1 if report["counts"].get("high") else 0


def _queries(args: argparse.Namespace):
    import duckdb

    from wildlife_scanner.policy.statuses import TierService
    from wildlife_scanner.profiles import ProfileLibrary
    from wildlife_scanner.serving import BaselineQueries

    region = _region(args)
    conn = duckdb.connect(args.db, read_only=True)
    profiles = ProfileLibrary()
    return BaselineQueries(conn, region, TierService(conn, region.id, profiles), profiles)


def cmd_query(args: argparse.Namespace) -> int:
    from wildlife_scanner.serving import NotAvailable

    queries = _queries(args)
    on = date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
    try:
        if args.what == "taxa":
            for t in queries.list_taxa(on, q=args.q, limit=args.limit):
                print(
                    f"{t.taxon_id:<40} {t.group or '':<10} tier={t.tier} visits={t.records_visits}"
                )
        elif args.what == "species":
            _print(queries.species_map(args.taxon, on, method=args.method))
        elif args.what == "calendar":
            _print(
                queries.calendar(
                    args.taxon, args.lat, args.lon, args.year or on.year, method=args.method
                )
            )
        elif args.what == "place":
            life = set((args.life_list or "").split(",")) - {""}
            _print(
                queries.place_lists(
                    args.lat, args.lon, on, life, limit=args.limit, group=args.group
                )
            )
    except NotAvailable:
        print("not available (unknown or sensitive taxon, or no data)")
        return 1
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from wildlife_scanner.api import create_app

    regions = [load_region(r.strip()).id for r in args.region.split(",") if r.strip()]
    bundle_dir = args.bundle_dir
    url = args.bundle_url
    if not url and not bundle_dir and not args.db_only:
        url = os.environ.get(PUBLISH_URL_ENV)
    if url:
        # Mirror the bucket's CURRENT bundle locally, then follow it like a local publish root.
        import threading
        import time

        from wildlife_scanner.pipeline.sync import pull_current
        from wildlife_scanner.storage.objects import open_store

        store = open_store(url)
        bundle_dir = args.cache_dir
        for region_id in regions:
            pull_current(store, region_id, Path(bundle_dir))

        def refresh() -> None:
            while True:
                time.sleep(args.refresh_seconds)
                for region_id in regions:
                    try:
                        if version := pull_current(store, region_id, Path(bundle_dir)):
                            print(f"{region_id}: bundle {version} ready", file=sys.stderr)
                    except Exception as exc:  # keep serving the current bundle
                        print(f"{region_id}: bundle refresh failed: {exc}", file=sys.stderr)

        threading.Thread(target=refresh, daemon=True).start()
    app = (
        create_app(bundle_dir=bundle_dir, region_id=regions)
        if bundle_dir
        else create_app(args.db, region_id=regions[0])
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _run_params(args: argparse.Namespace) -> dict:
    return {
        k: v
        for k, v in {
            "statuses": args.statuses,
            "datasets": args.datasets,
            "allow_findings": getattr(args, "allow_findings", False),
            "ingest_snapshots": args.ingest_snapshots,
            "snapshot_date": args.snapshot_date,
            "snapshot_workers": args.snapshot_workers,
            "keep_staging": args.keep_staging,
            "reingest_snapshot": args.reingest_snapshot,
        }.items()
        if v
    }


def cmd_worker(args: argparse.Namespace) -> int:
    """Run the job graph on a fixed tick and push each new version to object storage."""
    from datetime import timedelta

    from wildlife_scanner.pipeline import worker
    from wildlife_scanner.pipeline.runner import context
    from wildlife_scanner.storage.objects import open_store

    url = args.publish_url or os.environ.get(PUBLISH_URL_ENV)
    store = open_store(url) if url else None
    lake_url = args.lake_url or os.environ.get(LAKE_URL_ENV)
    lake_store = open_store(lake_url) if lake_url else None
    params = _run_params(args)
    regions = [r.strip() for r in args.region.split(",") if r.strip()]
    if len(regions) > 1 and "{region}" not in args.db:
        raise SystemExit("with several regions, --db needs a {region} placeholder")

    def make_contexts():
        out = []
        for region in regions:
            ctx = context(region, args.db.format(region=region), args.lake, dict(params))
            ctx.log = lambda msg, r=region: print(f"[{r}] {msg}", file=sys.stderr, flush=True)
            out.append(ctx)
        return out

    if args.once:
        outs = [worker.tick(c, store, lake_store=lake_store) for c in make_contexts()]
        print(json.dumps(outs, indent=2, default=str))
        return 1 if any(o["failed"] or "push_error" in o for o in outs) else 0
    worker.loop(
        make_contexts,
        timedelta(minutes=args.every),
        store,
        lake_store=lake_store,
        log=lambda m: print(m, flush=True),
    )
    return 0


def cmd_coverage_snapshot(args: argparse.Namespace) -> int:
    """Extract a coverage area from a GBIF snapshot into Parquet tiles (once for its regions)."""
    from wildlife_scanner.connectors import gbif_snapshot_remote as remote
    from wildlife_scanner.pipeline import coverage

    date_ = args.snapshot_date or remote.latest_snapshot()
    out = coverage.build(
        load_region(args.coverage),
        date_,
        Path(args.lake),
        workers=args.workers,
        keep_staging=args.keep_staging,
        log=lambda m: print(m, file=sys.stderr, flush=True),
    )
    print(json.dumps({k: v for k, v in out.items() if k != "tiles"}, indent=2, default=str))
    return 0


def cmd_push_publish(args: argparse.Namespace) -> int:
    """Upload the region's current published version to object storage and swap its pointer."""
    from wildlife_scanner.pipeline.sync import push_publish
    from wildlife_scanner.storage.objects import open_store

    url = args.publish_url or os.environ.get(PUBLISH_URL_ENV)
    if not url:
        raise SystemExit(f"--publish-url or {PUBLISH_URL_ENV} is required")
    region_id = load_region(args.region).id
    from wildlife_scanner.pipeline.sync import APP_COMPAT_ENV

    compat = None if args.skip_app_check else os.environ.get(APP_COMPAT_ENV)
    out = push_publish(
        Path(args.lake) / "publish", open_store(url), region_id, args.keep, compat_url=compat
    )
    print(json.dumps(out, indent=2))
    return 0


def cmd_lake_sync(args: argparse.Namespace) -> int:
    """Copy the lake's shared layers (reference store, normalized observations) to and from
    private object storage."""
    from wildlife_scanner.pipeline import coverage
    from wildlife_scanner.pipeline.sync import sync_lake
    from wildlife_scanner.storage.objects import open_store

    url = args.lake_url or os.environ.get(LAKE_URL_ENV)
    if not url:
        raise SystemExit(f"--lake-url or {LAKE_URL_ENV} is required")
    lake = Path(args.lake)
    out: dict = {}
    if args.push:
        # Tiles built before the size cap may be too big for one upload: cut them first.
        root = lake / "norm" / "observations" / "source=gbif"
        split: list[str] = []
        for marker in root.glob(f"snapshot=*/coverage=*/{coverage.SUCCESS}"):
            folder = marker.parent
            split += coverage.split_large(
                lake,
                folder.name.removeprefix("coverage="),
                folder.parent.name.removeprefix("snapshot="),
            )
        if split:
            out["split"] = split
    out.update(
        sync_lake(
            open_store(url),
            lake,
            push=args.push,
            pull=args.pull,
            pull_prefixes=tuple(args.pull_prefix) if args.pull_prefix else ("ref", "norm"),
            workers=args.workers,
            prune=args.prune,
            log=lambda m: print(m, file=sys.stderr, flush=True),
        )
    )
    print(json.dumps(out, indent=2))
    return 0


def cmd_lake_prune(args: argparse.Namespace) -> int:
    """Drop coverage snapshots and live-log days the lake no longer needs (here and remotely)."""
    from datetime import UTC, datetime

    from wildlife_scanner.pipeline import retention
    from wildlife_scanner.storage.objects import open_store

    url = args.lake_url or os.environ.get(LAKE_URL_ENV)
    store = open_store(url) if url and not args.local_only else None
    out = retention.prune(Path(args.lake), datetime.now(UTC), store=store, dry_run=args.dry_run)
    print(json.dumps(out, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run the job graph up to a target, skipping jobs whose inputs haven't changed."""
    from wildlife_scanner.pipeline.runner import JOBS, context, run

    if args.target == "list":
        for job in JOBS.values():
            deps = ", ".join(job.deps) or "-"
            age = job.max_age
            if age is None:
                cadence = ""
            elif age.days:
                cadence = f"every {age.days}d"
            elif age.seconds >= 3600:
                cadence = f"every {age.seconds // 3600}h"
            else:
                cadence = f"every {age.seconds // 60}m"
            print(f"{job.name:<11} needs {deps:<36} {cadence:<10} {job.description}")
        return 0
    params = _run_params(args)
    ctx = context(args.region, args.db, args.lake, params)
    ctx.log = lambda msg: print(msg, file=sys.stderr)
    force = tuple(f.strip() for f in (args.force or "").split(",") if f.strip())
    results = run(args.target, ctx, force=force, dry_run=args.dry_run)
    print(json.dumps(results, indent=2, default=str))
    failed = [
        r for r in results if isinstance(r.get("outcome"), str) or r["reason"].startswith("blocked")
    ]
    return 1 if failed else 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Write a policy-filtered serving bundle (gated on the tier audit) and make it current."""
    from pathlib import Path

    import yaml

    from wildlife_scanner.core.time import utcnow
    from wildlife_scanner.pipeline.publish import PublishBlocked, publish_bundle
    from wildlife_scanner.pipeline.static import before_swap
    from wildlife_scanner.storage import ObservationStore

    region = _region(args)
    statuses = _statuses_path(args, region)
    curated = []
    if statuses:
        doc = yaml.safe_load(statuses.read_text(encoding="utf-8")) or {}
        curated = [e["taxon_id"] for e in doc.get("statuses", [])]
    with ObservationStore(args.db) as store:
        try:
            result = publish_bundle(
                store.conn,
                region,
                Path(args.out),
                curated_ids=curated,
                registry=_registry(args),
                allow_findings=args.allow_findings,
                now=(now := utcnow()),
                before_swap=None if args.no_static else before_swap(region, now),
            )
        except PublishBlocked as exc:
            print(f"error: publishing blocked: {exc}; run audit-tiers for details", file=sys.stderr)
            return 1
    print(
        json.dumps(
            {
                "region": result.region_id,
                "version": result.version,
                "path": str(result.path),
                "rows": result.rows,
                "audit": result.findings,
                "audit_overridden": result.overridden,
            },
            indent=2,
        )
    )
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Build a complete offline demo database from synthetic data."""
    from wildlife_scanner.baseline import backtest_baseline, build_baseline
    from wildlife_scanner.policy import ConservationStatus
    from wildlife_scanner.policy.statuses import (
        StaticStatusProvider,
        StatusLookup,
        build_tier_table,
    )
    from wildlife_scanner.storage import ObservationStore
    from wildlife_scanner.synthetic import SyntheticWorld

    region = _region(args)
    world = SyntheticWorld(seed=args.seed)
    with ObservationStore(args.db) as store:
        store.conn.execute("DELETE FROM observations WHERE source_id = 'synthetic'")
        store.add(world.generate())
        report = build_baseline(store.conn, region_id=region.id, bbox=region.bbox)
        scores = backtest_baseline(
            store.conn,
            region_id=region.id,
            bbox=region.bbox,
            split=datetime(2025, 1, 1, tzinfo=UTC),
        )
        statuses = StaticStatusProvider(
            {
                "raritas-orientalis": StatusLookup(
                    statuses=(ConservationStatus(authority="IUCN", code="EN"),), source="demo"
                )
            }
        )
        build_tier_table(
            store.conn, region_id=region.id, scopes=region.scopes, providers=[statuses]
        )
    print(f"demo database: {args.db}")
    print(
        f"baseline: {report.taxa} taxa, {report.cells} cells, "
        f"{report.effort_rows + report.hit_rows} stored statistics rows"
    )
    for s in scores:
        print(f"  backtest {s.taxon_id:<22} BSS={s.bss:+.3f} passes={s.passes}")
    print("try:")
    print(
        f"  wildlife-scanner query place --db {args.db} --lat 32.85 --lon -117.27 --date 2026-05-15"
    )
    print(f"  wildlife-scanner serve --db {args.db}")
    return 0


def snapshot_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--ingest-snapshots",
        action="store_true",
        help="snapshot job: ingest the newest monthly GBIF snapshot when one is newer (network)",
    )
    p.add_argument("--snapshot-date", help="with --ingest-snapshots: this snapshot, not the newest")
    p.add_argument("--snapshot-workers", type=int, help="download threads (default 10)")
    p.add_argument("--keep-staging", action="store_true", help="keep staged snapshot rows")
    p.add_argument(
        "--reingest-snapshot",
        action="store_true",
        help="with --ingest-snapshots: ingest the snapshot even if its date was already "
        "ingested (e.g. to switch a region to its coverage tiles)",
    )


def register(sub: argparse._SubParsersAction) -> None:
    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--region", default="socal")
        p.add_argument("--db", default=DEFAULT_DB)

    p = sub.add_parser("ingest-snapshot", help="ingest a GBIF Parquet snapshot for a region")
    common(p)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--snapshot-date", help="e.g. 2026-11-01 (reads from AWS open data)")
    src.add_argument("--paths", nargs="+", help="local or remote Parquet paths")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_ingest_snapshot)

    p = sub.add_parser("ingest-api", help="ingest from the iNaturalist or GBIF API")
    common(p)
    p.add_argument("--source", choices=["inaturalist", "gbif"], required=True)
    p.add_argument("--taxon", help="scientific name (omit for all taxa in the region)")
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--limit", type=int, default=10_000)
    p.set_defaults(func=cmd_ingest_api)

    p = sub.add_parser("build-baseline", help="build the Level-0 prior for a region")
    common(p)
    p.add_argument("--res", type=int, default=6)
    p.add_argument("--min-visits", type=int, default=5)
    p.add_argument("--since-year", type=int, help="ignore records before this year")
    p.add_argument("--datasets", help="dataset registry YAML (default: region pack's)")
    p.set_defaults(func=cmd_build_baseline)

    p = sub.add_parser("evaluate-baseline", help="backtest the baseline vs. range-only")
    common(p)
    p.add_argument("--split", required=True, help="YYYY-MM-DD: train before, test after")
    p.add_argument("--end")
    p.add_argument("--res", type=int, default=6)
    p.add_argument("--min-visits", type=int, default=5)
    p.add_argument("--since-year", type=int, help="ignore records before this year")
    p.add_argument("--datasets", help="dataset registry YAML (default: region pack's)")
    p.add_argument("--groups", help="comma-separated effort groups to (re)score with this split")
    p.add_argument("--show", type=int, default=25)
    p.set_defaults(func=cmd_evaluate_baseline)

    p = sub.add_parser("annotate-datasets", help="fetch GBIF dataset metadata (type, title)")
    common(p)
    p.add_argument("--min-records", type=int, default=50)
    p.set_defaults(func=cmd_annotate_datasets)

    p = sub.add_parser("build-tiers", help="look up statuses and assign sensitivity tiers")
    common(p)
    p.add_argument("--offline", action="store_true", help="skip network status lookups")
    p.add_argument("--statuses", help="curated statuses YAML (default: the region pack's)")
    p.add_argument("--refresh-statuses", action="store_true", help="ignore cached status lookups")
    p.set_defaults(func=cmd_build_tiers)

    p = sub.add_parser(
        "repair-dates", help="re-date placeholder-dated records from their event ids"
    )
    common(p)
    p.add_argument("--datasets", help="dataset registry YAML (default: region pack's)")
    p.add_argument("--no-fetch", action="store_true", help="don't fetch missing event ids")
    p.add_argument("--workers", type=int, default=4)
    p.set_defaults(func=cmd_repair_dates)

    p = sub.add_parser("audit-tiers", help="check tiers against every status signal (gate)")
    common(p)
    p.add_argument("--statuses", help="curated statuses YAML (default: the region pack's)")
    p.add_argument("--show", type=int, default=40, help="findings to print")
    p.set_defaults(func=cmd_audit_tiers)

    p = sub.add_parser("query", help="query the baseline (policy-enforced)")
    common(p)
    p.add_argument("what", choices=["taxa", "species", "calendar", "place"])
    p.add_argument("taxon", nargs="?")
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float)
    p.add_argument("--date")
    p.add_argument("--year", type=int)
    p.add_argument("--q")
    p.add_argument("--life-list", help="comma-separated taxon ids you've already seen")
    p.add_argument(
        "--group", help="taxon group, effort class or method for place lists (e.g. fishes)"
    )
    p.add_argument("--method", help="effort class or method for species queries")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("serve", help="run the HTTP API")
    common(p)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--bundle-dir", help="serve published bundles from this root (follows CURRENT)")
    p.add_argument(
        "--bundle-url",
        help=f"mirror bundles from object storage (s3://bucket/prefix or a folder; "
        f"default ${PUBLISH_URL_ENV})",
    )
    p.add_argument("--cache-dir", default="data/bundles", help="local copy of mirrored bundles")
    p.add_argument("--refresh-seconds", type=int, default=60, help="how often to check CURRENT")
    p.add_argument(
        "--db-only", action="store_true", help=f"serve --db even if ${PUBLISH_URL_ENV} is set"
    )
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("run", help="run the job graph up to a target (only stale jobs)")
    common(p)
    p.add_argument("target", help="job to bring up to date (e.g. publish), or 'list'")
    p.add_argument("--lake", default="data/lake", help="lake root (manifests, publish)")
    p.add_argument("--force", help="comma-separated jobs to rerun regardless")
    p.add_argument("--dry-run", action="store_true", help="show the plan only")
    p.add_argument("--statuses", help="curated statuses YAML (default: the region pack's)")
    p.add_argument("--datasets", help="dataset registry YAML (default: the region pack's)")
    p.add_argument("--allow-findings", action="store_true", help="publish despite high findings")
    snapshot_args(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("worker", help="run the job graph on a schedule and push new versions")
    common(p)
    p.add_argument(
        "--lake-url",
        help=f"private object storage to share the reference store through (${LAKE_URL_ENV})",
    )
    p.add_argument("--lake", default="data/lake", help="lake root (manifests, publish)")
    p.add_argument("--every", type=int, default=30, help="minutes between ticks")
    p.add_argument("--once", action="store_true", help="run a single tick and exit")
    p.add_argument(
        "--publish-url", help=f"object storage for published versions (default ${PUBLISH_URL_ENV})"
    )
    p.add_argument("--statuses", help="curated statuses YAML (default: the region pack's)")
    p.add_argument("--datasets", help="dataset registry YAML (default: the region pack's)")
    snapshot_args(p)
    p.set_defaults(func=cmd_worker)

    p = sub.add_parser(
        "coverage-snapshot", help="extract a coverage area from a GBIF snapshot into tiles"
    )
    p.add_argument("--coverage", default="california", help="region pack of the coverage area")
    p.add_argument("--snapshot-date", help="default: the newest complete snapshot")
    p.add_argument("--lake", default="data/lake")
    p.add_argument("--workers", type=int, default=10)
    p.add_argument("--keep-staging", action="store_true")
    p.set_defaults(func=cmd_coverage_snapshot)

    p = sub.add_parser(
        "lake-sync", help="copy the lake's ref/ and norm/ layers to and from private storage"
    )
    common(p)
    p.add_argument("--lake", default="data/lake", help="lake root")
    p.add_argument("--lake-url", help=f"e.g. r2://<account>/<bucket>/lake (${LAKE_URL_ENV})")
    p.add_argument("--push", action="store_true", help="upload what the bucket lacks")
    p.add_argument("--pull", action="store_true", help="download what this machine lacks")
    p.add_argument(
        "--pull-prefix",
        action="append",
        help="with --pull: only keys under this prefix (repeatable), e.g. ref",
    )
    p.add_argument("--workers", type=int, default=4, help="parallel transfers")
    p.add_argument(
        "--prune",
        action="store_true",
        help="with --push: delete remote snapshot files this lake no longer has (split tiles)",
    )
    p.set_defaults(func=cmd_lake_sync)

    p = sub.add_parser(
        "lake-prune", help="drop old coverage snapshots and live-log days (keeps the newest two)"
    )
    common(p)
    p.add_argument("--lake", default="data/lake", help="lake root")
    p.add_argument("--lake-url", help=f"also delete remotely (${LAKE_URL_ENV})")
    p.add_argument("--local-only", action="store_true", help="don't touch object storage")
    p.add_argument("--dry-run", action="store_true", help="list what would be deleted")
    p.set_defaults(func=cmd_lake_prune)

    p = sub.add_parser("push-publish", help="upload the current published version")
    common(p)
    p.add_argument("--lake", default="data/lake", help="lake root (manifests, publish)")
    p.add_argument("--publish-url", help=f"default ${PUBLISH_URL_ENV}")
    p.add_argument("--keep", type=int, default=6, help="versions to keep remotely")
    p.add_argument(
        "--skip-app-check",
        action="store_true",
        help="don't ask the live app ($WILDLIFE_SCANNER_APP_COMPAT_URL) which formats it reads",
    )
    p.set_defaults(func=cmd_push_publish)

    p = sub.add_parser("publish", help="write a policy-filtered serving bundle (audit-gated)")
    common(p)
    p.add_argument("--out", default="data/lake/publish", help="publish root")
    p.add_argument("--statuses", help="curated statuses YAML (default: the region pack's)")
    p.add_argument("--datasets", help="dataset registry YAML (default: region pack's)")
    p.add_argument(
        "--allow-findings", action="store_true", help="publish despite high audit findings"
    )
    p.add_argument("--no-static", action="store_true", help="skip the static products")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("demo", help="build an offline demo database from synthetic data")
    common(p)
    p.set_defaults(db="data/demo.duckdb")
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(func=cmd_demo)
