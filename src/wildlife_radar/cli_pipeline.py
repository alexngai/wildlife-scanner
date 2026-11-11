"""Pipeline CLI commands: ingest → build-baseline → evaluate-baseline → build-tiers → query/serve.

The database defaults to ``data/wildlife-radar.duckdb`` (``data/`` is git-ignored).
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime

DEFAULT_DB = "data/wildlife-radar.duckdb"


def _region(args: argparse.Namespace):
    from wildlife_radar.regions import load_region

    return load_region(args.region)


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
    cfg = BaselineConfig(res=args.res, min_visits=args.min_visits)
    with ObservationStore(args.db) as store:
        report = build_baseline(store.conn, region_id=region.id, bbox=region.bbox, config=cfg)
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
            config=BaselineConfig(res=args.res, min_visits=args.min_visits),
        )
    passed = sum(s.passes for s in scores)
    print(f"{passed}/{len(scores)} taxa beat the range-only reference (Brier skill > 0)")
    for s in scores[: args.show]:
        print(f"  {s.taxon_id:<40} n={s.n_test:<7} hits={s.n_pos:<6} BSS={s.bss:+.3f}")
    return 0


def cmd_build_tiers(args: argparse.Namespace) -> int:
    from wildlife_radar.policy.statuses import (
        CachedStatusProvider,
        RegionStatusFile,
        build_tier_table,
    )
    from wildlife_radar.regions import region_dir
    from wildlife_radar.storage import ObservationStore

    region = _region(args)
    with ObservationStore(args.db) as store:
        providers = [RegionStatusFile(region_dir(region.id) / "statuses.yaml")]
        if not args.offline:
            from wildlife_radar.connectors.inaturalist_taxa import InatTaxonStatusProvider

            providers.append(
                CachedStatusProvider(store.conn, InatTaxonStatusProvider(region.inat_place_scopes))
            )
        decisions = build_tier_table(
            store.conn, region_id=region.id, scopes=region.scopes, providers=providers
        )
    counts: dict[str, int] = {}
    for d in decisions.values():
        counts[d.tier.name] = counts.get(d.tier.name, 0) + 1
    print(json.dumps({"taxa": len(decisions), "tiers": counts}, indent=2))
    if args.offline:
        print("note: offline mode — taxa without a completed status lookup fail closed (COARSE)")
    return 0


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
            _print(queries.species_map(args.taxon, on))
        elif args.what == "calendar":
            _print(queries.calendar(args.taxon, args.lat, args.lon, args.year or on.year))
        elif args.what == "place":
            life = set((args.life_list or "").split(",")) - {""}
            _print(queries.place_lists(args.lat, args.lon, on, life, limit=args.limit))
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
    p.set_defaults(func=cmd_build_baseline)

    p = sub.add_parser("evaluate-baseline", help="backtest the baseline vs. range-only")
    common(p)
    p.add_argument("--split", required=True, help="YYYY-MM-DD: train before, test after")
    p.add_argument("--end")
    p.add_argument("--res", type=int, default=6)
    p.add_argument("--min-visits", type=int, default=5)
    p.add_argument("--show", type=int, default=25)
    p.set_defaults(func=cmd_evaluate_baseline)

    p = sub.add_parser("build-tiers", help="look up statuses and assign sensitivity tiers")
    common(p)
    p.add_argument("--offline", action="store_true", help="skip network status lookups")
    p.set_defaults(func=cmd_build_tiers)

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
