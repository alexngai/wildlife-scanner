"""Pipeline CLI commands: ingest → build-baseline → evaluate-baseline → build-tiers → query/serve.

The database defaults to ``data/wildlife-radar.duckdb`` (``data/`` is git-ignored).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta

DEFAULT_DB = "data/wildlife-radar.duckdb"


def _region(args: argparse.Namespace):
    from wildlife_radar.regions import load_region

    return load_region(args.region)


def _statuses_path(args: argparse.Namespace, region):
    """Curated statuses: ``--statuses``, the region pack's file, or one next to a region file."""
    from pathlib import Path

    from wildlife_radar.regions import region_dir

    if getattr(args, "statuses", None):
        path = Path(args.statuses)
        if not path.exists():
            raise SystemExit(f"error: {path} not found")
        return path
    candidates = [region_dir(region.id) / "statuses.yaml"]
    if Path(args.region).suffix:
        candidates.append(Path(args.region).parent / "statuses.yaml")
    return next((p for p in candidates if p.exists()), None)


def _registry(args: argparse.Namespace):
    from pathlib import Path

    from wildlife_radar.baseline.effort import DatasetRegistry
    from wildlife_radar.regions import region_dir

    region = _region(args)
    path = (
        Path(args.datasets)
        if getattr(args, "datasets", None)
        else (region_dir(region.id) / "datasets.yaml")
    )
    return DatasetRegistry.load(path)


def _print(model) -> None:
    if hasattr(model, "model_dump_json"):
        print(model.model_dump_json(indent=2))
    else:
        print(json.dumps(model, indent=2, default=str))


def cmd_ingest_snapshot(args: argparse.Namespace) -> int:
    from wildlife_radar.connectors.gbif_snapshot import (
        SnapshotReport,
        snapshot_observations,
        snapshot_url,
    )
    from wildlife_radar.storage import ObservationStore

    region = _region(args)
    paths = args.paths or [snapshot_url(args.snapshot_date)]
    report = SnapshotReport()
    with ObservationStore(args.db) as store:
        n = store.add(snapshot_observations(paths, region.bbox, report, limit=args.limit))
        print(json.dumps({"stored": n, **report.__dict__, "total": store.count()}, indent=2))
    return 0


def cmd_ingest_api(args: argparse.Namespace) -> int:
    from wildlife_radar.connectors.base import ObservationQuery
    from wildlife_radar.storage import ObservationStore

    if args.source == "inaturalist":
        from wildlife_radar.connectors.inaturalist import INaturalistConnector as Connector
    else:
        from wildlife_radar.connectors.gbif import GBIFConnector as Connector
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
    from wildlife_radar.baseline import BaselineConfig, build_baseline
    from wildlife_radar.storage import ObservationStore

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
    from wildlife_radar.baseline import BaselineConfig, backtest_baseline
    from wildlife_radar.storage import ObservationStore

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
    from wildlife_radar.baseline.effort import date_spikes
    from wildlife_radar.connectors.gbif_datasets import fetch_dataset_meta
    from wildlife_radar.storage import ObservationStore

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
    from wildlife_radar.policy.statuses import (
        CachedStatusProvider,
        RegionStatusFile,
        build_tier_table,
    )
    from wildlife_radar.storage import ObservationStore

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
            from wildlife_radar.connectors.inaturalist_taxa import InatTaxonStatusProvider

            providers.append(
                CachedStatusProvider(
                    store.conn,
                    max_age=timedelta(0) if args.refresh_statuses else timedelta(days=90),
                    inner=InatTaxonStatusProvider(
                        region.inat_place_scopes, innermost_place=region.inat_innermost_place
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
    from wildlife_radar.connectors.gbif_events import fetch_event_ids
    from wildlife_radar.storage import ObservationStore
    from wildlife_radar.storage.repair import (
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
    import yaml

    from wildlife_radar.policy.audit import audit_tiers, summarize
    from wildlife_radar.storage import ObservationStore

    region = _region(args)
    statuses = _statuses_path(args, region)
    curated = []
    if statuses:
        doc = yaml.safe_load(statuses.read_text(encoding="utf-8")) or {}
        curated = [e["taxon_id"] for e in doc.get("statuses", [])]
    with ObservationStore(args.db) as store:
        findings = audit_tiers(store.conn, region.id, curated)
    report = summarize(findings)
    report["findings"] = report["findings"][: args.show]
    report["curated_statuses"] = str(statuses) if statuses else None
    print(json.dumps(report, indent=2))
    return 1 if report["counts"].get("high") else 0


def _queries(args: argparse.Namespace):
    import duckdb

    from wildlife_radar.policy.statuses import TierService
    from wildlife_radar.profiles import ProfileLibrary
    from wildlife_radar.serving import BaselineQueries

    region = _region(args)
    conn = duckdb.connect(args.db, read_only=True)
    profiles = ProfileLibrary()
    return BaselineQueries(conn, region, TierService(conn, region.id, profiles), profiles)


def cmd_query(args: argparse.Namespace) -> int:
    from wildlife_radar.serving import NotAvailable

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

    from wildlife_radar.api import create_app

    uvicorn.run(create_app(args.db, region_id=args.region), host=args.host, port=args.port)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Build a complete offline demo database from synthetic data."""
    from wildlife_radar.baseline import backtest_baseline, build_baseline
    from wildlife_radar.policy import ConservationStatus
    from wildlife_radar.policy.statuses import StaticStatusProvider, StatusLookup, build_tier_table
    from wildlife_radar.storage import ObservationStore
    from wildlife_radar.synthetic import SyntheticWorld

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
        f"  wildlife-radar query place --db {args.db} --lat 32.85 --lon -117.27 --date 2026-05-15"
    )
    print(f"  wildlife-radar serve --db {args.db}")
    return 0


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
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", help="build an offline demo database from synthetic data")
    common(p)
    p.set_defaults(db="data/demo.duckdb")
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(func=cmd_demo)
