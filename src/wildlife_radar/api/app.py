"""FastAPI service: species-first and place-first queries over the Level-0 baseline.

Everything returned has passed the policy layer. The service is AGPL-3.0: every response carries
a link to the corresponding source (AGPL §13) in the ``X-Source-Code`` header, and ``/source``
describes it. Set ``WILDLIFE_RADAR_SOURCE_URL`` when running a modified version.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException, Query, Request

from wildlife_radar import __version__
from wildlife_radar.connectors import ALL_SOURCES
from wildlife_radar.policy.statuses import TierService
from wildlife_radar.profiles import ProfileLibrary
from wildlife_radar.regions import load_region
from wildlife_radar.serving.queries import (
    BaselineQueries,
    Calendar,
    NotAvailable,
    PlaceLists,
    SpeciesMap,
    TaxonSummary,
)

SOURCE_URL_ENV = "WILDLIFE_RADAR_SOURCE_URL"
DEFAULT_SOURCE_URL = "https://github.com/alexngai/wildlife-radar"
NOT_AVAILABLE = "Not available: unknown taxon, sensitive taxon, or no data for this request."


def _parse_date(value: str | None) -> date:
    if not value:
        return datetime.now(UTC).date()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from None


def _life_list(value: str | None) -> set[str]:
    return {v.strip() for v in (value or "").split(",") if v.strip()}


def create_app(
    db_path: str | Path,
    region_id: str = "socal",
    profiles_dir: str | Path | None = None,
    source_url: str | None = None,
    now: datetime | None = None,
) -> FastAPI:
    region = load_region(region_id)
    profiles = ProfileLibrary(profiles_dir) if profiles_dir else ProfileLibrary()
    conn = duckdb.connect(str(db_path), read_only=True)
    tiers = TierService(conn, region.id, profiles=profiles, now=now)
    queries = BaselineQueries(conn, region, tiers, profiles=profiles)
    source = source_url or os.environ.get(SOURCE_URL_ENV) or DEFAULT_SOURCE_URL

    app = FastAPI(
        title="wildlife-radar",
        version=__version__,
        description=(
            "Where and when to encounter wildlife — a free, non-commercial, educational "
            "service. Outputs are generalized for sensitive species."
        ),
        license_info={"name": "AGPL-3.0-only", "identifier": "AGPL-3.0-only"},
    )
    app.state.queries = queries

    @app.middleware("http")
    async def source_header(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Source-Code"] = source
        return response

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "region": region.id,
            "model_version": queries.model_version,
            "built_at": queries.as_of.isoformat(),
        }

    @app.get("/source")
    def source_info() -> dict:
        return {
            "source_url": source,
            "license": "AGPL-3.0-only",
            "notice": "This service's source code is available under the GNU AGPL v3.",
        }

    @app.get("/sources")
    def sources() -> list[dict]:
        return [
            {
                "source_id": s.source_id,
                "name": s.name,
                "attribution": s.attribution,
                "terms_url": s.terms_url,
            }
            for s in ALL_SOURCES.values()
        ]

    @app.get("/taxa", response_model=list[TaxonSummary])
    def taxa(
        q: str | None = None,
        group: str | None = None,
        limit: int = Query(50, ge=1, le=500),
        date: str | None = None,
    ):
        return queries.list_taxa(_parse_date(date), q=q, group=group, limit=limit)

    @app.get("/taxa/{taxon_id}", response_model=TaxonSummary)
    def taxon(taxon_id: str, date: str | None = None):
        try:
            return queries.taxon_summary(taxon_id, _parse_date(date))
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None

    @app.get("/species/{taxon_id}/map", response_model=SpeciesMap)
    def species_map(taxon_id: str, date: str | None = None):
        try:
            return queries.species_map(taxon_id, _parse_date(date))
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None

    @app.get("/species/{taxon_id}/calendar", response_model=Calendar)
    def calendar(
        taxon_id: str,
        lat: float | None = None,
        lon: float | None = None,
        place_id: str | None = None,
        year: int | None = None,
    ):
        lat, lon = _location(lat, lon, place_id)
        try:
            return queries.calendar(taxon_id, lat, lon, year or datetime.now(UTC).year)
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/places")
    def places() -> list[dict]:
        return [
            {"place_id": p.place_id, "name": p.name, "kind": p.kind.value, "notes": p.notes}
            for p in region.places
        ]

    @app.get("/places/{place_id}/lists", response_model=PlaceLists)
    def place_lists(
        place_id: str,
        date: str | None = None,
        life_list: str | None = None,
        group: str | None = None,
    ):
        lat, lon = _location(None, None, place_id)
        return _lists(lat, lon, date, life_list, group)

    @app.get("/nearby", response_model=PlaceLists)
    def nearby(
        lat: float,
        lon: float,
        date: str | None = None,
        life_list: str | None = None,
        group: str | None = None,
    ):
        return _lists(lat, lon, date, life_list, group)

    def _lists(
        lat: float, lon: float, day: str | None, life_list: str | None, group: str | None
    ) -> PlaceLists:
        try:
            return queries.place_lists(
                lat, lon, _parse_date(day), _life_list(life_list), group=group
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    def _location(
        lat: float | None, lon: float | None, place_id: str | None
    ) -> tuple[float, float]:
        if place_id:
            try:
                place = region.place(place_id)
            except KeyError:
                raise HTTPException(status_code=404, detail="unknown place") from None
            fp = place.footprint
            return fp.lat, fp.lon  # region places are point footprints
        if lat is None or lon is None:
            raise HTTPException(status_code=400, detail="give lat and lon, or place_id")
        return lat, lon

    return app
