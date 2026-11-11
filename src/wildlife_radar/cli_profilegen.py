"""CLI for profile generation: ``wildlife-radar profilegen resolve|generate|review|promote``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _names(args: argparse.Namespace) -> list[str]:
    names = list(args.names or [])
    if getattr(args, "names_file", None):
        names += [
            line.strip()
            for line in Path(args.names_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
    if not names:
        raise SystemExit("error: give scientific names or --names-file")
    return names


def cmd_resolve(args: argparse.Namespace) -> int:
    from wildlife_radar.profilegen.identity import IdentityResolver

    for ident in IdentityResolver().resolve_many(_names(args)):
        print(json.dumps(ident.model_dump(mode="json", by_alias=True, exclude_none=True)))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    from wildlife_radar.profilegen.draft import DEFAULT_DRAFT_DIR
    from wildlife_radar.profilegen.identity import IdentityResolver
    from wildlife_radar.profilegen.pipeline import Generator
    from wildlife_radar.profilegen.traits import TetrapodTraits
    from wildlife_radar.profilegen.wikipedia import WikipediaClient
    from wildlife_radar.regions import load_region
    from wildlife_radar.storage import ObservationStore

    out_dir = Path(args.out) if args.out else DEFAULT_DRAFT_DIR
    gen = Generator(resolver=IdentityResolver(), out_dir=out_dir)
    if args.traits:
        gen.traits = TetrapodTraits(args.traits)
    store = None
    if args.db:
        store = ObservationStore(args.db)
        gen.store = store.conn
        if args.region:
            region = load_region(args.region)
            gen.region_id = region.id
            gen.bbox = region.bbox
    if args.extract:
        from wildlife_radar.profilegen.extract import ClaudeExtractor

        gen.wiki = WikipediaClient(cache_dir=out_dir.parent / "cache" / "wikipedia")
        gen.extractor = ClaudeExtractor(model=args.model)
    try:
        reports = gen.run(_names(args))
    finally:
        if store is not None:
            store.close()
    for report in reports:
        print(json.dumps(report.as_dict()))
    return 0 if all(r.path for r in reports) else 1


def cmd_review(args: argparse.Namespace) -> int:
    from wildlife_radar.profilegen.draft import DEFAULT_DRAFT_DIR, draft_path, load_doc

    out_dir = Path(args.out) if args.out else DEFAULT_DRAFT_DIR
    doc = load_doc(draft_path(out_dir, args.id))
    if doc is None:
        print(f"error: no draft {args.id!r} in {out_dir}", file=sys.stderr)
        return 1
    gen = doc.get("generation", {})
    prov = doc.get("provenance", {})
    print(f"{doc['id']}  {doc.get('scientific_name')}  ({doc.get('common_name')})")
    print(f"  extends {doc.get('extends')}  status {doc.get('status')}")
    print(f"  licenses {gen.get('licenses')}  open variant: {gen.get('open_variant')}")
    print("  review queue (uncertainty × impact):")
    for path in gen.get("review_queue", []):
        p = prov.get(path, {})
        value = doc
        for part in path.split("."):
            value = (value or {}).get(part) if isinstance(value, dict) else None
        print(
            f"    {path:<32} {json.dumps(value):<40} "
            f"[{p.get('method')}, conf {p.get('confidence')}, {p.get('source')}]"
        )
    for c in gen.get("conflicts", []):
        print(f"  conflict {c['field']}: {c['values']} from {c['sources']}")
    for note in gen.get("notes", []):
        print(f"  note: {note}")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    from wildlife_radar.profilegen.draft import (
        DEFAULT_DRAFT_DIR,
        draft_path,
        dump,
        load_doc,
        promote,
    )
    from wildlife_radar.profiles.loader import DEFAULT_PROFILES_DIR

    out_dir = Path(args.out) if args.out else DEFAULT_DRAFT_DIR
    doc = load_doc(draft_path(out_dir, args.id))
    if doc is None:
        print(f"error: no draft {args.id!r} in {out_dir}", file=sys.stderr)
        return 1
    dest_dir = Path(args.to) if args.to else DEFAULT_PROFILES_DIR / "species"
    dest = dest_dir / f"{args.id}.yaml"
    existing = load_doc(dest)
    if existing and not existing.get("generation") and not args.replace_curated:
        print(
            f"error: {dest} is a hand-curated profile; merge by hand or pass --replace-curated",
            file=sys.stderr,
        )
        return 1
    split = lambda s: [f.strip() for f in (s or "").split(",") if f.strip()]  # noqa: E731
    reviewed = promote(
        doc,
        reviewer=args.reviewer,
        lock=split(args.lock),
        reject=split(args.reject),
        existing=existing if existing and existing.get("generation") else None,
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(dump(reviewed), encoding="utf-8")
    print(f"wrote {dest} (locked: {reviewed['locked']})")
    return 0


def cmd_crosswalk(args: argparse.Namespace) -> int:
    """Resolve every baseline taxon in a region; verified iNaturalist ids feed build-tiers."""
    from wildlife_radar.profilegen.identity import (
        IDENTITY_SCHEMA,
        IdentityResolver,
        save_identities,
    )
    from wildlife_radar.storage import ObservationStore

    resolver = IdentityResolver()
    done = 0
    with ObservationStore(args.db) as store:
        store.conn.execute(IDENTITY_SCHEMA)
        names = [
            n
            for (n,) in store.conn.execute(
                """
                SELECT DISTINCT scientific_name FROM prior_taxa
                WHERE region_id = ? AND scientific_name IS NOT NULL
                  AND (? OR scientific_name NOT IN (SELECT query_name FROM taxon_identity))
                ORDER BY 1
                """,
                [args.region_id, args.refresh],
            ).fetchall()
        ][: args.limit]
        for start in range(0, len(names), args.chunk):
            chunk = names[start : start + args.chunk]
            idents = resolver.resolve_many(chunk, gbif="fallback")
            save_identities(store.conn, idents)
            done += len(chunk)
            print(f"resolved {done}/{len(names)}", file=sys.stderr)
        summary = store.conn.execute(
            """
            SELECT count(*), count(*) FILTER (WHERE taxon_id IS NOT NULL),
                count(*) FILTER (WHERE (record->>'$.verified.inaturalist')::BOOLEAN),
                count(*) FILTER (WHERE record->>'$.wikidata' IS NOT NULL)
            FROM taxon_identity
            """
        ).fetchone()
    print(
        json.dumps(
            dict(
                zip(
                    ["identities", "resolved", "inaturalist_verified", "wikidata"],
                    summary,
                    strict=True,
                )
            )
        )
    )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("profilegen", help="generate draft species profiles from metadata")
    actions = p.add_subparsers(dest="profilegen_action", required=True)

    a = actions.add_parser("resolve", help="resolve names to identities and crosswalk ids")
    a.add_argument("names", nargs="*")
    a.add_argument("--names-file")
    a.set_defaults(func=cmd_resolve)

    a = actions.add_parser(
        "crosswalk", help="resolve every baseline taxon in a region (cached in the store)"
    )
    a.add_argument("--db", required=True)
    a.add_argument("--region-id", required=True, help="baseline region id (e.g. sandiego)")
    a.add_argument("--limit", type=int)
    a.add_argument("--chunk", type=int, default=200)
    a.add_argument("--refresh", action="store_true", help="re-resolve cached names")
    a.set_defaults(func=cmd_crosswalk)

    a = actions.add_parser("generate", help="write draft profiles (data/profiles/generated)")
    a.add_argument("names", nargs="*")
    a.add_argument("--names-file")
    a.add_argument("--out", help="draft directory (default: data/profiles/generated)")
    a.add_argument("--traits", help="TetrapodTraits CSV (CC BY 4.0, downloaded to data/)")
    a.add_argument("--db", help="observation store with a baseline (occurrence-derived priors)")
    a.add_argument("--region", help="region pack whose baseline to use")
    a.add_argument(
        "--extract", action="store_true", help="LLM extraction from Wikipedia (needs the llm extra)"
    )
    a.add_argument("--model", help="extraction model id (or WILDLIFE_RADAR_EXTRACTION_MODEL)")
    a.set_defaults(func=cmd_generate)

    a = actions.add_parser("review", help="show a draft's review queue, conflicts and notes")
    a.add_argument("id")
    a.add_argument("--out")
    a.set_defaults(func=cmd_review)

    a = actions.add_parser("promote", help="promote a reviewed draft into profiles/species")
    a.add_argument("id")
    a.add_argument("--reviewer", required=True)
    a.add_argument("--lock", help="comma-separated field paths the reviewer checked")
    a.add_argument("--reject", help="comma-separated field paths to remove (locked as absent)")
    a.add_argument("--out", help="draft directory")
    a.add_argument("--to", help="destination directory (default: profiles/species)")
    a.add_argument("--replace-curated", action="store_true")
    a.set_defaults(func=cmd_promote)
