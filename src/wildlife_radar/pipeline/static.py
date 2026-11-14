"""Static products for the CDN, built from a finished serving bundle (data-platform.md §5–6).

They are read from the bundle through the same query layer as the API, so they pass the same
policy by construction: withheld taxa are absent, sensitive taxa appear only at their tier's
resolution and time granularity, and tiers are evaluated per week (seasonal raises apply).
The file formats are documented for frontend use in ``docs/design/static-products.md``.

Layout under ``publish/region=<id>/``::

    version=<v>/static/index.json      entry point: region, versions, places (small)
    version=<v>/static/taxa.json       search index: names, aliases, group, tier, map path,
                                       season summary, photo
    static/maps/<taxon>.<key>.json     the year's maps as cells × weeks (or months) matrices
    static/places/<place>.<key>.json   a place's names, groups and week file paths
    static/places/<place>.<key>/wNN.json  one week's lists (format 3)

Maps and place lists are **content-addressed**: ``key`` hashes everything that determines the
file (baseline build, the taxon's tier for each week, names, gates, licenses, format version),
so a publish regenerates and uploads only files whose inputs changed. Live publishes every
30 minutes therefore cost one small index; a new monthly baseline regenerates everything,
in parallel processes.

Maps are keyed by ISO week, not by date: estimates are per week of the year, so one file
serves every year. Tiers that depend on the date (seasonal windows) are evaluated for the
``year_basis`` year and are rebuilt with each baseline.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from multiprocessing import get_context
from pathlib import Path

import duckdb

from wildlife_radar.baseline.effort import method_for
from wildlife_radar.policy.statuses import TierService
from wildlife_radar.policy.tiers import PolicyTier
from wildlife_radar.regions import Region
from wildlife_radar.serving.queries import (
    AWARENESS_MESSAGE,
    LEVEL0_LABEL,
    BaselineQueries,
    NotAvailable,
    week_thursday,
)

FORMAT = 3
"""Bump when the shape of a static file changes, so every file is regenerated."""
P_SCALE = 100_000
"""Probabilities are stored as integers: ``p = value / P_SCALE``."""
STATIC_DIR = "static"
INDEX = "index.json"


def _key(*parts) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":"), default=str), encoding="utf-8")
    os.replace(tmp, path)


def _q(v: float | None) -> int | None:
    return None if v is None else int(round(v * P_SCALE))


def _weekly_tiers(q: BaselineQueries, taxon_id: str, year: int) -> list[int]:
    out = []
    for w in range(1, 53):
        try:
            out.append(int(q._tier(taxon_id, week_thursday(year, w))))
        except NotAvailable:
            out.append(int(PolicyTier.WITHHELD))
    return out


def map_doc(q: BaselineQueries, taxon_id: str, year: int, meta: dict) -> dict | None:
    """Format 2: per segment (weeks sharing a tier), cells × periods integer matrices."""
    segments = q.species_matrix(taxon_id, year)
    if not segments:
        return None
    return {
        "format": FORMAT,
        **meta,
        "year_basis": year,
        "p_scale": P_SCALE,
        "segments": [
            {
                "tier": s.tier,
                "granularity": s.granularity,
                "resolution": s.resolution,
                "resolution_km": s.resolution_km,
                "periods": s.periods,
                "cells": s.cells,
                "p": [[_q(v) for v in row] for row in s.p],
                "confidence": s.confidence,
                "ref": {
                    "resolution": s.ref_resolution,
                    "p": {k: [_q(v) for v in vs] for k, vs in s.ref_p.items()},
                },
                "region_p": [_q(v) for v in s.region_p],
            }
            for s in segments
        ],
    }


_LIST_KEYS = ("most_likely", "special_here", "peaking_now")
_CONF = {"insufficient": "i", "low": "l", "medium": "m", "high": "h"}


def _x100(v: float | None) -> int | None:
    return None if v is None else int(round(v * 100))


def place_doc(q: BaselineQueries, place, year: int) -> dict:
    """Format 2: names, groups and resolutions once; each list item a short row
    ``[taxon_id, p, lift×100, seasonal_index×100, confidence, resolution]`` (see
    docs/design/static-products.md)."""
    lat, lon = place.footprint.lat, place.footprint.lon
    taxa: dict[str, dict] = {}
    groups: dict[str, dict] = {}
    resolutions: list[float] = []

    def taxon(item) -> str:
        taxa.setdefault(
            item["taxon_id"],
            {
                "scientific_name": item["scientific_name"],
                "common_name": item["common_name"],
                "group": item["group"],
            },
        )
        return item["taxon_id"]

    def res(km: float) -> int:
        if km not in resolutions:
            resolutions.append(km)
        return resolutions.index(km)

    weeks = []
    for w in range(1, 53):
        lists = q.place_lists(lat, lon, week_thursday(year, w)).model_dump(mode="json")
        week: dict = {"week": w, "groups": {}}
        for g in lists["groups"]:
            groups.setdefault(
                g["group"],
                {k: g[k] for k in ("taxon_group", "effort_class", "label", "method", "license")},
            )
            week["groups"][g["group"]] = {
                key: [
                    [
                        taxon(i),
                        _q(i["p"]),
                        _x100(i["lift"]),
                        _x100(i["seasonal_index"]),
                        _CONF[i["confidence"]],
                        res(i["resolution_km"]),
                    ]
                    for i in g[key]
                ]
                for key in _LIST_KEYS
                if g[key]
            }
        week["awareness"] = [taxon(a) for a in lists["awareness"]]
        week["area_fallback"] = lists["area_fallback"]
        weeks.append(week)
    return {
        "format": FORMAT,
        "place": place.model_dump(mode="json"),
        "year_basis": year,
        "p_scale": P_SCALE,
        "item_fields": ["taxon_id", "p", "lift_x100", "seasonal_index_x100", "confidence", "res"],
        "resolutions_km": resolutions,
        "awareness_message": AWARENESS_MESSAGE,
        "taxa": taxa,
        "groups": groups,
        "weeks": weeks,
    }


# -- Parallel workers: each opens the bundle read-only once. ----------------------------------

_WORKER: dict = {}


def _open(bundle: str, region: Region, now: datetime, profiles) -> BaselineQueries:
    conn = duckdb.connect(bundle, read_only=True)
    tiers = TierService(conn, region.id, profiles=profiles, now=now)
    return BaselineQueries(conn, region, tiers, profiles=profiles)


def _init_worker(bundle: str, region: Region, now: datetime, profiles) -> None:
    _WORKER["q"] = _open(bundle, region, now, profiles)
    _WORKER["region"] = region


def _run_job(job: tuple) -> tuple[str, str, bool, list | None]:
    kind, ident, year, path, meta = job
    q = _WORKER["q"]
    if kind == "map":
        doc = map_doc(q, ident, year, meta)
        if doc is None:
            return kind, ident, False, None
        _write(Path(path), doc)
        return kind, ident, True, season(doc)
    write_place(place_doc(q, _WORKER["region"].place(ident), year), Path(path))
    return kind, ident, True, None


def week_dir(header: str) -> str:
    """A place's week files live next to its header: ``<place>.<key>.json`` →
    ``<place>.<key>/``."""
    return header.removesuffix(".json")


def write_place(doc: dict, header: Path) -> None:
    """Format 3: one small file per week, then the header (names, groups, week paths).
    The header goes last, so a reader (or a reuse check) never finds it without its weeks."""
    weeks = doc.pop("weeks")
    folder = Path(week_dir(str(header)))
    rel_folder = week_dir(header.relative_to(header.parents[2]).as_posix())
    paths = []
    for week in weeks:
        name = f"w{week['week']:02d}.json"
        _write(folder / name, {"format": FORMAT, **week})
        paths.append(f"{rel_folder}/{name}")
    _write(header, {**doc, "weeks": paths})


SEASON_LEVELS = 9


def season(doc: dict) -> list | None:
    """A taxon's regional season, one 0–9 level per ISO week (relative to its own peak week),
    from the map's ``region_p``; ``None`` for weeks withheld or shown only coarsely (tier 2+
    or monthly segments). ``None`` overall when no week qualifies."""
    values: list[int | None] = [None] * 52
    for seg in doc.get("segments") or []:
        if seg.get("tier", 9) >= 2 or seg.get("granularity") != "week":
            continue
        for period, v in zip(seg["periods"], seg.get("region_p") or [], strict=False):
            if 1 <= period <= 52:
                values[period - 1] = v
    peak = max((v for v in values if v is not None), default=None)
    if peak is None:
        return None
    return [
        None
        if v is None
        else 0
        if v <= 0 or not peak
        else max(1, min(SEASON_LEVELS, math.ceil(SEASON_LEVELS * v / peak)))
        for v in values
    ]


def build_static(
    bundle: Path,
    region: Region,
    region_dir: Path,
    version_dir: Path,
    now: datetime,
    *,
    profiles=None,
    log=lambda _m: None,
    version: str | None = None,
    workers: int | None = None,
) -> dict:
    """Write the static products of ``bundle`` (reusing unchanged content-addressed files).

    Shared files go under ``region_dir/static``; the index and search index under
    ``version_dir/static`` (``version`` names it, if ``version_dir`` is a temporary folder).
    ``workers`` processes build new files (default: one per CPU; 0 builds in this process)."""
    q = _open(str(bundle), region, now, profiles)
    try:
        today = now.date()
        year = today.year
        build = [q.model_version, q.as_of.isoformat()]
        taxa = q.list_taxa(today, limit=1_000_000)
        aliases: dict[str, list[str]] = {}
        for alias, canonical in q._aliases.items():
            aliases.setdefault(canonical, []).append(alias)
        search = [
            {
                "id": t.taxon_id,
                "scientific_name": t.scientific_name,
                "common_name": t.common_name,
                "aliases": sorted(aliases.get(t.taxon_id, [])),
                "group": t.group,
                "tier": t.tier,
                "mode": t.mode,
                "records": t.records_visits,
            }
            for t in taxa
        ]
        stats = {"maps": 0, "maps_reused": 0, "places": 0, "places_reused": 0}
        seasons: dict[str, list | None] = {}
        files: dict = {"maps": {}, "places": {}}
        jobs: list[tuple] = []
        all_tiers: dict[str, list[int]] = {}
        # Every taxon with a baseline (not just those visible today): a taxon withheld this
        # week may be shown in others.
        for taxon_id in sorted(q._taxa):
            weekly = _weekly_tiers(q, taxon_id, year)
            all_tiers[taxon_id] = weekly
            if all(t >= PolicyTier.WITHHELD for t in weekly):
                continue
            first_visible = week_thursday(year, weekly.index(min(weekly)) + 1)
            try:
                summary = q.taxon_summary(taxon_id, first_visible)
                group = q._choose_group(taxon_id, None)
            except NotAvailable:
                continue
            meta = {
                "taxon": summary.model_dump(mode="json"),
                "effort_group": group,
                "method": method_for(group),
                "label": LEVEL0_LABEL,
                "license": q.license_for([group]).model_dump(mode="json"),
            }
            key = _key(FORMAT, build, year, weekly, meta)
            rel = f"{STATIC_DIR}/maps/{taxon_id}.{key}.json"
            files["maps"][taxon_id] = rel
            if (region_dir / rel).exists():
                stats["maps_reused"] += 1
                seasons[taxon_id] = season(json.loads((region_dir / rel).read_text("utf-8")))
            else:
                jobs.append(("map", taxon_id, year, str(region_dir / rel), meta))
        names = {t: (q._taxa[t].name, q.common_name(t)) for t in sorted(q._taxa)}
        for place in region.places:
            key = _key(FORMAT, build, year, place.model_dump(mode="json"), all_tiers, names)
            rel = f"{STATIC_DIR}/places/{place.place_id}.{key}.json"
            files["places"][place.place_id] = rel
            if (region_dir / rel).exists():
                stats["places_reused"] += 1
            else:
                jobs.append(("place", place.place_id, year, str(region_dir / rel), None))
        if workers is None:
            workers = os.cpu_count() or 1
        if jobs and workers > 0:
            log(f"static: building {len(jobs)} files in {workers} processes")
            with ProcessPoolExecutor(
                max_workers=workers,
                mp_context=get_context("spawn"),
                initializer=_init_worker,
                initargs=(str(bundle), region, now, profiles),
            ) as pool:
                # Slow jobs (place lists) first, small chunks: no worker ends up with a long
                # tail while the others idle.
                ordered = sorted(jobs, key=lambda j: j[0] != "place")
                chunk = max(1, len(ordered) // (workers * 16))
                results = list(pool.map(_run_job, ordered, chunksize=chunk))
        else:
            _WORKER.update(q=q, region=region)
            results = [_run_job(j) for j in jobs]
        for kind, ident, written, seas in results:
            if written:
                stats["maps" if kind == "map" else "places"] += 1
                if kind == "map":
                    seasons[ident] = seas
            elif kind == "map":
                files["maps"].pop(ident, None)  # nothing visible after all
        photos = _photos(q._conn)
        for entry in search:
            taxon_id = entry["id"]
            if taxon_id in files["maps"]:
                entry["map"] = files["maps"][taxon_id]
            if seasons.get(taxon_id) and entry["tier"] < 2:
                entry["season"] = seasons[taxon_id]
            if taxon_id in photos:
                entry["photo"] = photos[taxon_id]
        out_dir = version_dir / STATIC_DIR
        _write(out_dir / "taxa.json", search)
        version = version or version_dir.name.removeprefix("version=")
        index = {
            "format": FORMAT,
            "region": {"id": region.id, "name": region.name, "bbox": list(region.bbox)},
            "version": version,
            "baseline": {"model_version": q.model_version, "built_at": q.as_of.isoformat()},
            "published_at": now.isoformat(),
            "year_basis": year,
            "p_scale": P_SCALE,
            "paths_relative_to": f"region={region.id}/",
            "taxa": f"version={version}/{STATIC_DIR}/taxa.json",
            "places": {
                p.place_id: {
                    "name": p.name,
                    "kind": p.kind.value,
                    "lat": p.footprint.lat,
                    "lon": p.footprint.lon,
                    "file": files["places"].get(p.place_id),
                }
                for p in region.places
            },
        }
        _write(out_dir / INDEX, index)
        stats["taxa"] = len(search)
        stats["photos"] = sum(1 for e in search if "photo" in e)
        log(f"static: {stats}")
        return stats
    finally:
        q._conn.close()


def before_swap(region: Region, now: datetime, profiles=None, log=lambda _m: None):
    """A ``publish_bundle(before_swap=...)`` hook that adds the static products to the version
    while it is still in its temporary folder (so it never goes live without them)."""
    if profiles is None:
        from wildlife_radar.profiles import ProfileLibrary

        profiles = ProfileLibrary()  # the API's default library, so both apply the same tiers

    def hook(bundle: Path, tmp: Path, final: Path) -> dict:
        return build_static(
            bundle,
            region,
            final.parent,
            tmp,
            now,
            profiles=profiles,
            log=log,
            version=final.name.removeprefix("version="),
        )

    return hook


def referenced(index: dict, taxa: list | None = None) -> set[str]:
    """Shared static files (paths relative to the region folder) a version points at.

    Format 3 keeps map paths in ``taxa.json`` (pass it as ``taxa``); formats 1–2 kept them in
    the index (format 1 nested them by year). A place header's week files are covered by
    ``in_use``."""
    out: set[str] = set()
    for entry in index.get("maps", {}).values():
        out |= set(entry.values()) if isinstance(entry, dict) else {entry}
    for t in taxa or []:
        if t.get("map"):
            out.add(t["map"])
    for p in index.get("places", {}).values():
        if p.get("file"):
            out.add(p["file"])
        out |= set((p.get("files") or {}).values())
    return out


def in_use(rel: str, used: set[str]) -> bool:
    """Is a shared file referenced, directly or as a week file of a referenced place?"""
    if rel in used:
        return True
    folder = rel.rsplit("/", 1)[0]
    return f"{folder}.json" in used


def needs_taxa(index: dict) -> bool:
    """Format 3+ indexes leave map paths to ``taxa.json``."""
    return int(index.get("format") or 0) >= 3


def _photos(conn) -> dict[str, dict]:
    tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    if "taxon_photos" not in tables:
        return {}
    return {
        t: json.loads(p)
        for t, p in conn.execute("SELECT taxon_id, photo FROM taxon_photos").fetchall()
    }
