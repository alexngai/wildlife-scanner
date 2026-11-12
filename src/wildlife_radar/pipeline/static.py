"""Static products for the CDN, built from a finished serving bundle (data-platform.md §5–6).

They are read from the bundle through the same query layer as the API, so they pass the same
policy by construction: withheld taxa are absent, sensitive taxa appear only at their tier's
resolution and time granularity, and tiers are evaluated per week (seasonal raises apply).

Layout under ``publish/region=<id>/``::

    version=<v>/static/index.json    entry point: what exists and where (small, per version)
    version=<v>/static/taxa.json     search index: names, aliases, group, tier
    static/maps/<taxon>/<year>.<key>.json       weekly (or monthly) H3 maps for a year
    static/places/<place>/<year>.<key>.json     weekly place lists for a year

Maps and place lists are **content-addressed**: ``key`` hashes everything that determines the
file (baseline build, the taxon's tier for each week, names, gates, licenses, format version),
so a publish regenerates and uploads only files whose inputs changed. Live publishes every
30 minutes therefore cost one small index; a new monthly baseline regenerates everything.

Maps are H3 cells (``[cell, p, lift, seasonal_index, confidence]``), which the frontend can
draw directly (e.g. h3-js or deck.gl's H3 layer); no tile pipeline is needed at these sizes.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from wildlife_radar.policy.statuses import TierService
from wildlife_radar.policy.tiers import PolicyTier
from wildlife_radar.regions import Region
from wildlife_radar.serving.queries import BaselineQueries, NotAvailable, week_thursday

FORMAT = 1
"""Bump when the shape of a static file changes, so every file is regenerated."""
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


def years_for(now: date) -> list[int]:
    """The current year, plus the next one during the last eight weeks of the year."""
    return sorted({now.year, (now + timedelta(weeks=8)).year})


def _weekly_tiers(q: BaselineQueries, taxon_id: str, year: int) -> list[int]:
    out = []
    for w in range(1, 53):
        try:
            out.append(int(q._tier(taxon_id, week_thursday(year, w))))
        except NotAvailable:
            out.append(int(PolicyTier.WITHHELD))
    return out


def _map_doc(q: BaselineQueries, taxon_id: str, year: int) -> dict | None:
    maps = q.species_maps(taxon_id, year)
    if not maps:
        return None
    first = maps[0]
    return {
        "format": FORMAT,
        "taxon": first.taxon.model_dump(mode="json"),
        "year": year,
        "effort_group": first.effort_group,
        "method": first.method,
        "label": first.label,
        "license": first.license.model_dump(mode="json"),
        "periods": [
            {
                "start": m.time_window.start.date().isoformat(),
                "end": (m.time_window.end - timedelta(seconds=1)).date().isoformat(),
                "tier": m.taxon.tier,
                "resolution_km": m.resolution_km,
                "cells": [
                    [c.cell, c.p, c.lift, c.seasonal_index, c.confidence.value] for c in m.cells
                ],
            }
            for m in sorted(maps, key=lambda m: m.time_window.start)
        ],
    }


def _place_doc(q: BaselineQueries, place, year: int) -> dict:
    lat, lon = place.footprint.lat, place.footprint.lon
    weeks = []
    for w in range(1, 53):
        lists = q.place_lists(lat, lon, week_thursday(year, w))
        doc = lists.model_dump(mode="json")
        for g in doc["groups"]:
            g.pop("new_for_you", None)  # needs a life list: API only
        weeks.append(doc)
    return {
        "format": FORMAT,
        "place": place.model_dump(mode="json"),
        "year": year,
        "weeks": weeks,
    }


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
) -> dict:
    """Write the static products of ``bundle`` (reusing unchanged content-addressed files).

    Shared files go under ``region_dir/static``; the index and search index under
    ``version_dir/static`` (``version`` names it, if ``version_dir`` is a temporary folder)."""
    conn = duckdb.connect(str(bundle), read_only=True)
    try:
        tiers = TierService(conn, region.id, profiles=profiles, now=now)
        q = BaselineQueries(conn, region, tiers, profiles=profiles)
        today = now.date()
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
        all_tiers: dict[int, dict[str, list[int]]] = {}
        # Every taxon with a baseline (not just those visible today): a taxon withheld this
        # week may be shown in others.
        for taxon_id in sorted(q._taxa):
            for year in years_for(today):
                weekly = _weekly_tiers(q, taxon_id, year)
                all_tiers.setdefault(year, {})[taxon_id] = weekly
                if all(t >= PolicyTier.WITHHELD for t in weekly):
                    continue
                first_visible = week_thursday(year, weekly.index(min(weekly)) + 1)
                try:
                    summary = q.taxon_summary(taxon_id, first_visible)
                    group = q._choose_group(taxon_id, None)
                except NotAvailable:
                    continue
                key = _key(
                    FORMAT,
                    build,
                    year,
                    weekly,
                    summary.model_dump(mode="json"),
                    q.license_for([group]).model_dump(mode="json"),
                )
                rel = f"{STATIC_DIR}/maps/{taxon_id}/{year}.{key}.json"
                if (region_dir / rel).exists():
                    stats["maps_reused"] += 1
                else:
                    doc = _map_doc(q, taxon_id, year)
                    if doc is None:
                        continue
                    _write(region_dir / rel, doc)
                    stats["maps"] += 1
                files["maps"].setdefault(taxon_id, {})[str(year)] = rel
        names = {t: (q._taxa[t].name, q.common_name(t)) for t in sorted(q._taxa)}
        for place in region.places:
            for year in years_for(today):
                key = _key(
                    FORMAT, build, year, place.model_dump(mode="json"), all_tiers[year], names
                )
                rel = f"{STATIC_DIR}/places/{place.place_id}/{year}.{key}.json"
                if (region_dir / rel).exists():
                    stats["places_reused"] += 1
                else:
                    _write(region_dir / rel, _place_doc(q, place, year))
                    stats["places"] += 1
                files["places"].setdefault(place.place_id, {})[str(year)] = rel
        out_dir = version_dir / STATIC_DIR
        _write(out_dir / "taxa.json", search)
        version = version or version_dir.name.removeprefix("version=")
        index = {
            "format": FORMAT,
            "region": {"id": region.id, "name": region.name, "bbox": list(region.bbox)},
            "version": version,
            "baseline": {"model_version": q.model_version, "built_at": q.as_of.isoformat()},
            "published_at": now.isoformat(),
            "paths_relative_to": f"region={region.id}/",
            "taxa": f"version={version}/{STATIC_DIR}/taxa.json",
            "maps": files["maps"],
            "places": {
                p.place_id: {
                    "name": p.name,
                    "kind": p.kind.value,
                    "files": files["places"].get(p.place_id, {}),
                }
                for p in region.places
            },
        }
        _write(out_dir / INDEX, index)
        stats["taxa"] = len(search)
        log(f"static: {stats}")
        return stats
    finally:
        conn.close()


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
    """Shared static files (paths relative to the region folder) an index points at."""
    out = {rel for years in index.get("maps", {}).values() for rel in years.values()}
    out |= {rel for p in index.get("places", {}).values() for rel in p["files"].values()}
    return out
