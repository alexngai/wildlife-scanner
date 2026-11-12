"""Operator CLI: connectors, profiles, policy, and the baseline pipeline.

Observation commands print aggregate summaries only (counts, months, licenses), never
coordinates: public outputs must go through the policy egress filter.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import yaml

from wildlife_radar import __version__


def _cmd_astro(args: argparse.Namespace) -> int:
    from wildlife_radar.connectors.astronomy import astro_state, daily_events

    day = date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
    ev = daily_events(args.lat, args.lon, day, args.utc_offset)
    tz_note = f"UTC{args.utc_offset:+g}"

    def fmt(dt: datetime | None) -> str:
        if dt is None:
            return "—"
        local = dt + timedelta(hours=args.utc_offset)
        return f"{local:%H:%M} ({tz_note})"

    noon_local = datetime(day.year, day.month, day.day, 12, tzinfo=UTC) - timedelta(
        hours=args.utc_offset
    )
    state = astro_state(args.lat, args.lon, noon_local)
    print(f"Astronomy for {args.lat:.4f}, {args.lon:.4f} on {day} ({tz_note})")
    for name in ("civil_dawn", "sunrise", "sunset", "civil_dusk", "moonrise", "moonset"):
        print(f"  {name:<11} {fmt(getattr(ev, name))}")
    print(
        f"  moon at local noon: {state.moon_illumination:.0%} illuminated, "
        f"phase angle {state.moon_phase_angle_deg:.0f}° (0 new, 180 full)"
    )
    return 0


def _cmd_tides(args: argparse.Namespace) -> int:
    from wildlife_radar.connectors.noaa_coops import CoopsTideConnector

    start = date.fromisoformat(args.start)
    end = start + timedelta(days=args.days - 1)
    values = CoopsTideConnector().predictions(args.station, start, end, args.interval)
    for v in values:
        kind = v.attrs.get("type", "")
        print(f"{v.valid_time:%Y-%m-%d %H:%M}Z  {v.value:6.3f} m  {kind}")
    return 0


def _cmd_observations(args: argparse.Namespace) -> int:
    from wildlife_radar.connectors.base import ObservationQuery
    from wildlife_radar.core.licenses import combine

    if args.source == "inaturalist":
        from wildlife_radar.connectors.inaturalist import INaturalistConnector as Connector
    else:
        from wildlife_radar.connectors.gbif import GBIFConnector as Connector

    bbox = None
    if args.region:
        from wildlife_radar.regions import load_region

        bbox = load_region(args.region).bbox
    elif args.bbox:
        bbox = tuple(float(x) for x in args.bbox.split(","))

    query = ObservationQuery(
        taxon_name=args.taxon,
        bbox=bbox,
        start=date.fromisoformat(args.since) if args.since else None,
        end=date.fromisoformat(args.until) if args.until else None,
        limit=args.limit,
    )
    observations = list(Connector().fetch(query))
    months = Counter(o.time.start.month for o in observations)
    grades = Counter(o.evidence_grade.value for o in observations)
    licenses = Counter(o.license.id for o in observations)
    obscured = sum(o.sensitivity.obscured for o in observations)
    constraints = combine(o.license for o in observations)
    summary = {
        "source": args.source,
        "taxon": args.taxon,
        "n": len(observations),
        "by_month": dict(sorted(months.items())),
        "evidence_grades": dict(grades),
        "licenses": dict(licenses),
        "obscured": obscured,
        "derived_product_constraints": {
            "fully_open": constraints.fully_open,
            "noncommercial": constraints.noncommercial,
            "publishable_noncommercially": constraints.publishable_noncommercially,
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


def _cmd_profiles(args: argparse.Namespace) -> int:
    from wildlife_radar.policy import PolicyTier
    from wildlife_radar.profiles import ProfileLibrary

    lib = ProfileLibrary(args.profiles_dir) if args.profiles_dir else ProfileLibrary()
    if args.action == "list":
        for pid in lib.ids():
            kind = lib.raw(pid).get("kind", "species")
            print(f"{kind:<9} {pid}")
        return 0
    if not args.id:
        print("error: profile id required", file=sys.stderr)
        return 2
    profile = lib.resolve(args.id)
    if args.action == "show":
        print(yaml.safe_dump(profile.model_dump(mode="json", exclude_none=True), sort_keys=False))
        return 0
    on = date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
    eff = profile.effective_tier(
        PolicyTier(args.auto_tier), region=args.region, on=on, now=datetime.now(UTC)
    )
    print(f"{profile.id} in {args.region or 'all regions'} on {on}: tier {eff.tier.name}")
    for r in eff.reasons:
        print(f"  + {r}")
    for r in eff.ignored:
        print(f"  ! {r}")
    return 0


def _cmd_sources(_: argparse.Namespace) -> int:
    from wildlife_radar.connectors import ALL_SOURCES

    for src in ALL_SOURCES.values():
        lic = "per record" if src.per_record_license else (src.license.id if src.license else "?")
        print(f"{src.source_id:<12} {src.kind.value:<12} license: {lic:<14} terms: {src.terms_url}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wildlife-radar", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("astro", help="sun/moon events for a location (offline)")
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--date", help="YYYY-MM-DD (default: today, UTC)")
    p.add_argument("--utc-offset", type=float, default=0.0, help="local UTC offset in hours")
    p.set_defaults(func=_cmd_astro)

    p = sub.add_parser("tides", help="NOAA CO-OPS tide predictions (network)")
    p.add_argument("--station", required=True, help="CO-OPS station id, e.g. 9410230")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--interval", choices=["h", "6", "hilo"], default="hilo")
    p.set_defaults(func=_cmd_tides)

    p = sub.add_parser("observations", help="summarize observations from a source (network)")
    p.add_argument("--source", choices=["inaturalist", "gbif"], required=True)
    p.add_argument("--taxon", required=True, help="scientific name")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--region", help="region pack id, e.g. socal")
    group.add_argument("--bbox", help="lon_min,lat_min,lon_max,lat_max")
    p.add_argument("--since", help="YYYY-MM-DD")
    p.add_argument("--until", help="YYYY-MM-DD")
    p.add_argument("--limit", type=int, default=500)
    p.set_defaults(func=_cmd_observations)

    p = sub.add_parser("profiles", help="list, show or evaluate species profiles")
    p.add_argument("action", choices=["list", "show", "tier"])
    p.add_argument("id", nargs="?")
    p.add_argument("--region")
    p.add_argument("--date", help="YYYY-MM-DD for seasonal windows")
    p.add_argument(
        "--auto-tier", type=int, default=0, choices=[0, 1, 2, 3], help="automatic tier input"
    )
    p.add_argument("--profiles-dir")
    p.set_defaults(func=_cmd_profiles)

    p = sub.add_parser("sources", help="list connector sources and their terms")
    p.set_defaults(func=_cmd_sources)

    from wildlife_radar.cli_conditions import register as register_conditions
    from wildlife_radar.cli_pipeline import register
    from wildlife_radar.cli_profilegen import register as register_profilegen

    register(sub)
    register_profilegen(sub)
    register_conditions(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # surface connector/profile errors without a traceback
        from wildlife_radar.connectors.base import ConnectorError
        from wildlife_radar.profiles.loader import ProfileError

        if isinstance(exc, ConnectorError | ProfileError):
            print(f"error: {exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
