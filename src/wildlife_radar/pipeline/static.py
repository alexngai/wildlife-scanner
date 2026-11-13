"""Static products for the CDN, built from a finished serving bundle (data-platform.md §5–6).

They are read from the bundle through the same query layer as the API, so they pass the same
policy by construction: withheld taxa are absent, sensitive taxa appear only at their tier's
resolution and time granularity, and tiers are evaluated per week (seasonal raises apply).
The file formats are documented for frontend use in ``docs/design/static-products.md``.

Layout under ``publish/region=<id>/``::

    version=<v>/static/index.json      entry point: what exists and where (small, per version)
    version=<v>/static/taxa.json       search index: names, aliases, group, tier
    static/maps/<taxon>.<key>.json     the year's maps as cells × weeks (or months) matrices
    static/places/<place>.<key>.json   weekly place lists

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
    LEVEL0_LABEL,
    BaselineQueries,
    NotAvailable,
    week_thursday,
)

FORMAT = 2
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


def place_doc(q: BaselineQueries, place, year: int) -> dict:
    lat, lon = place.footprint.lat, place.footprint.lon
    weeks = []
    for w in range(1, 53):
        doc = q.place_lists(lat, lon, week_thursday(year, w)).model_dump(mode="json")
        doc.pop("date", None)  # weeks, not dates: the file serves every year
        for g in doc["groups"]:
            g.pop("new_for_you", None)  # needs a life list: API only
        weeks.append(doc)
    return {
        "format": FORMAT,
        "place": place.model_dump(mode="json"),
        "year_basis": year,
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


def _run_job(job: tuple) -> tuple[str, str, bool]:
    kind, ident, year, path, meta = job
    q = _WORKER["q"]
    if kind == "map":
        doc = map_doc(q, ident, year, meta)
    else:
        doc = place_doc(q, _WORKER["region"].place(ident), year)
    if doc is None:
        return kind, ident, False
    _write(Path(path), doc)
    return kind, ident, True


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
        for kind, ident, written in results:
            if written:
                stats["maps" if kind == "map" else "places"] += 1
            elif kind == "map":
                files["maps"].pop(ident, None)  # nothing visible after all
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
            "maps": files["maps"],
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


def referenced(index: dict) -> set[str]:
    """Shared static files (paths relative to the region folder) an index points at
    (format 2; format-1 indexes nested files by year)."""
    out: set[str] = set()
    for entry in index.get("maps", {}).values():
        out |= set(entry.values()) if isinstance(entry, dict) else {entry}
    for p in index.get("places", {}).values():
        if p.get("file"):
            out.add(p["file"])
        out |= set((p.get("files") or {}).values())
    return out
