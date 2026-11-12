"""CLI for Phase 3: ``fetch-signals``, ``fit-conditions`` and ``scorecard``."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime


def _region(args):
    from wildlife_radar.regions import load_region

    return load_region(args.region)


def cmd_fetch_signals(args: argparse.Namespace) -> int:
    from wildlife_radar.conditions.daily import COOPS_PRODUCTS, CoopsDailyFetcher, store_rows
    from wildlife_radar.storage import ObservationStore

    region = _region(args)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today()
    fetcher = CoopsDailyFetcher()
    summary = {}
    with ObservationStore(args.db) as store:
        for st in region.tide_stations:
            n = 0
            for product in COOPS_PRODUCTS:
                rows = fetcher.observations(st.station_id, st.lon, product, start, end)
                n += store_rows(store.conn, rows)
            n += store_rows(store.conn, fetcher.tides(st.station_id, st.lon, start, end))
            summary[st.station_id] = n
            print(f"{st.station_id} ({st.name}): {n} daily values", file=sys.stderr)
        coverage = store.conn.execute(
            "SELECT station_id, signal_id, min(day), max(day), count(*) FROM signal_daily "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        ).fetchall()
    print(
        json.dumps(
            [
                {"station": s, "signal": g, "from": str(a), "to": str(b), "days": n}
                for s, g, a, b, n in coverage
            ],
            indent=2,
        )
    )
    return 0


def _specs(args, region_id_for_profiles):
    from wildlife_radar.conditions import terms_from_profile
    from wildlife_radar.profiles import ProfileLibrary
    from wildlife_radar.profiles.schema import SpeciesProfile

    lib = ProfileLibrary()
    wanted = [t.strip() for t in (args.taxa or "").split(",") if t.strip()] or lib.ids(
        kind="species"
    )
    template = None
    if args.template:
        # Guild defaults for taxa without a species profile (Level 1 "built by templates").
        template = SpeciesProfile.model_validate(lib.merged(args.template))
    specs, notes = {}, {}
    for taxon_id in wanted:
        if taxon_id in lib.ids(kind="species"):
            profile = lib.resolve(taxon_id)
        elif template is not None:
            profile = template
        else:
            notes[taxon_id] = ["no species profile; pass --template for guild defaults"]
            continue
        terms, why = terms_from_profile(profile)
        notes[taxon_id] = why
        if terms:
            specs[taxon_id] = terms
    return specs, notes


def cmd_fit_conditions(args: argparse.Namespace) -> int:
    from wildlife_radar.cli_pipeline import _registry
    from wildlife_radar.conditions.levels import run_conditions
    from wildlife_radar.storage import ObservationStore

    region = _region(args)
    specs, notes = _specs(args, region.id)
    if not specs:
        print(json.dumps({"error": "no taxa with daily condition terms", "notes": notes}))
        return 1
    with ObservationStore(args.db) as store:
        from wildlife_radar.baseline.builder import BaselineConfig

        reports = run_conditions(
            store.conn,
            region_id=region.id,
            bbox=region.bbox,
            split=datetime.fromisoformat(args.split),
            end=datetime.fromisoformat(args.end) if args.end else None,
            specs=specs,
            station_coords={s.station_id: (s.lat, s.lon) for s in region.tide_stations},
            config=BaselineConfig(since_year=args.since_year),
            registry=_registry(args),
            nowcast_days=args.nowcast_days,
        )
    out = []
    for r in reports:
        out.append(
            {
                "taxon": r.taxon_id,
                "group": r.group_id,
                "terms": r.terms,
                "n_train": r.n_train,
                "n_test": r.n_test,
                "test_detections": r.n_pos_test,
                "levels": [
                    {
                        "level": lv.level,
                        "skill_vs_lower": round(lv.skill, 4),
                        "ci90": [round(lv.ci[0], 4), round(lv.ci[1], 4)],
                        "passes": lv.passes,
                    }
                    for lv in r.levels
                ],
                "brier_persistence": r.brier_persistence,
                "scorecard": [
                    {
                        "term": s.term,
                        "hypothesis": s.hypothesis,
                        "delta_log_loss": round(s.delta_log_loss, 5),
                        "ci90": [round(s.ci[0], 5), round(s.ci[1], 5)],
                        "expected": s.direction_expected,
                        "fitted": s.direction_fitted,
                        "verdict": s.verdict,
                    }
                    for s in r.scorecard
                ],
                "notes": r.notes + notes.get(r.taxon_id, []),
            }
        )
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_scorecard(args: argparse.Namespace) -> int:
    import duckdb

    conn = duckdb.connect(args.db, read_only=True)
    columns = {r[0] for r in conn.execute("DESCRIBE hypothesis_scorecard").fetchall()}
    review = "review" if "review" in columns else "NULL"  # stores fitted before the column
    rows = conn.execute(
        f"""
        SELECT taxon_id, group_id, term, hypothesis, n_test, round(delta_log_loss, 5),
            round(ci_lo, 5), round(ci_hi, 5), direction_expected, direction_fitted, verdict,
            {review}
        FROM hypothesis_scorecard WHERE region_id = ? ORDER BY taxon_id, group_id, term
        """,
        [_region(args).id],
    ).fetchall()
    if args.review:
        rows = [r for r in rows if r[-1]]
    print(f"{'taxon':28} {'group':20} {'term':22} {'Δlog loss':>10} {'90% CI':>22}  verdict")
    for t, g, term, hyp, _n, d, lo, hi, exp, fit, verdict, why in rows:
        flag = "*" if hyp else " "
        direction = f" ({exp or '?'}→{fit})" if fit else ""
        note = f"  REVIEW: {why}" if why else ""
        print(
            f"{t:28} {g:20} {term + flag:22} {d:>10} [{lo:>9}, {hi:>9}]  {verdict}{direction}{note}"
        )
    print("* hypothesis term; Δlog loss > 0 means the term improves held-out predictions")
    if args.review:
        print("REVIEW: revise the profile (docs/research/10 §1 has worked examples), then refit")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    def common(p):
        p.add_argument("--region", default="socal")
        p.add_argument("--db", default="data/wildlife-radar.duckdb")

    p = sub.add_parser("fetch-signals", help="download daily station signals (NOAA CO-OPS)")
    common(p)
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--end")
    p.set_defaults(func=cmd_fetch_signals)

    p = sub.add_parser("fit-conditions", help="fit and gate Levels 1-2; hypothesis scorecard")
    common(p)
    p.add_argument("--split", required=True, help="train before, test from this date")
    p.add_argument("--end")
    p.add_argument("--taxa", help="comma-separated taxon ids (default: all species profiles)")
    p.add_argument(
        "--template", help="template whose terms apply to taxa without a profile (guild/…)"
    )
    p.add_argument("--since-year", type=int)
    p.add_argument("--datasets", help="dataset registry YAML (default: region pack's)")
    p.add_argument("--nowcast-days", type=int, default=14)
    p.set_defaults(func=cmd_fit_conditions)

    p = sub.add_parser("scorecard", help="show the hypothesis scorecard")
    common(p)
    p.add_argument(
        "--review",
        action="store_true",
        help="only terms whose profile claim needs review (wrong direction or harmful)",
    )
    p.set_defaults(func=cmd_scorecard)
