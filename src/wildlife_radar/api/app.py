"""FastAPI service: species-first and place-first queries over the Level-0 baseline.

Everything returned has passed the policy layer. The service is AGPL-3.0: every response carries
a link to the corresponding source (AGPL §13) in the ``X-Source-Code`` header, and ``/source``
describes it. Set ``WILDLIFE_RADAR_SOURCE_URL`` when running a modified version.

Browsers may call the API from the origins listed in ``WILDLIFE_RADAR_CORS_ORIGINS``
(comma-separated, e.g. the frontend's Cloudflare Pages domain); none by default.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException, Query, Request

from wildlife_radar import __version__
from wildlife_radar.baseline.effort import DatasetRegistry
from wildlife_radar.connectors import ALL_SOURCES
from wildlife_radar.pipeline.publish import current_bundle
from wildlife_radar.policy.statuses import TierService
from wildlife_radar.profiles import ProfileLibrary
from wildlife_radar.regions import load_region, pack_file, region_dir
from wildlife_radar.serving.forecast import (
    Forecast,
    ForecastService,
    RecentActivity,
    recent_activity,
)
from wildlife_radar.serving.queries import (
    BaselineQueries,
    Calendar,
    NotAvailable,
    PlaceLists,
    SpeciesMap,
    TaxonSummary,
)

SOURCE_URL_ENV = "WILDLIFE_RADAR_SOURCE_URL"
CORS_ENV = "WILDLIFE_RADAR_CORS_ORIGINS"
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


class _Services:
    """Everything the endpoints query, opened read-only from one database or bundle file."""

    def __init__(self, db_path: Path, region, profiles, now: datetime | None) -> None:
        self.db_path = db_path
        self.conn = duckdb.connect(str(db_path), read_only=True)
        tiers = TierService(self.conn, region.id, profiles=profiles, now=now)
        self.queries = BaselineQueries(self.conn, region, tiers, profiles=profiles)
        self.forecasts = ForecastService(
            self.queries,
            {s.station_id: (s.lat, s.lon) for s in region.tide_stations},
            registry=DatasetRegistry.load(
                pack_file(region, "datasets.yaml") or region_dir(region.id) / "datasets.yaml"
            ),
        )


def create_app(
    db_path: str | Path | None = None,
    region_id: str = "socal",
    profiles_dir: str | Path | None = None,
    source_url: str | None = None,
    now: datetime | None = None,
    bundle_dir: str | Path | None = None,
) -> FastAPI:
    """Serve a region from a database file, or from published bundles (``bundle_dir`` is the
    publish root): the API then follows the region's ``CURRENT`` pointer and reopens when a new
    version is published."""
    region = load_region(region_id)
    profiles = ProfileLibrary(profiles_dir) if profiles_dir else ProfileLibrary()
    region_bundles = Path(bundle_dir) / f"region={region.id}" if bundle_dir else None

    def resolve() -> Path:
        if region_bundles is None:
            return Path(db_path)  # type: ignore[arg-type]
        path = current_bundle(region_bundles)
        if path is None:
            raise RuntimeError(f"no published bundle for region {region.id!r}")
        return path

    state = {"svc": _Services(resolve(), region, profiles, now)}

    def svc() -> _Services:
        if region_bundles is not None:
            path = resolve()
            if path != state["svc"].db_path:
                old = state["svc"]
                state["svc"] = _Services(path, region, profiles, now)
                old.conn.close()
        return state["svc"]

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
    app.state.services = svc
    origins = [o.strip() for o in os.environ.get(CORS_ENV, "").split(",") if o.strip()]
    if origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET"],
            expose_headers=["X-Source-Code"],
        )

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
            "model_version": svc().queries.model_version,
            "built_at": svc().queries.as_of.isoformat(),
            "bundle": svc().db_path.parent.name,
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
        return svc().queries.list_taxa(_parse_date(date), q=q, group=group, limit=limit)

    @app.get("/taxa/{taxon_id}", response_model=TaxonSummary)
    def taxon(taxon_id: str, date: str | None = None):
        try:
            return svc().queries.taxon_summary(taxon_id, _parse_date(date))
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None

    @app.get("/species/{taxon_id}/map", response_model=SpeciesMap)
    def species_map(taxon_id: str, date: str | None = None, method: str | None = None):
        try:
            return svc().queries.species_map(taxon_id, _parse_date(date), method=method)
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None

    @app.get("/species/{taxon_id}/calendar", response_model=Calendar)
    def calendar(
        taxon_id: str,
        lat: float | None = None,
        lon: float | None = None,
        place_id: str | None = None,
        year: int | None = None,
        method: str | None = None,
    ):
        lat, lon = _location(lat, lon, place_id)
        try:
            return svc().queries.calendar(
                taxon_id, lat, lon, year or datetime.now(UTC).year, method=method
            )
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/species/{taxon_id}/forecast", response_model=Forecast)
    def forecast(
        taxon_id: str,
        lat: float | None = None,
        lon: float | None = None,
        place_id: str | None = None,
        date: str | None = None,
        method: str | None = None,
    ):
        """Daily forecast at the highest gated level (0 baseline, 1 conditions, 2 nowcast)."""
        lat, lon = _location(lat, lon, place_id)
        try:
            return svc().forecasts.forecast(taxon_id, lat, lon, _parse_date(date), method=method)
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/nearby/recent", response_model=RecentActivity)
    def nearby_recent(lat: float, lon: float, date: str | None = None):
        """Recently reported species near a point, and which are picking up today."""
        try:
            return recent_activity(svc().forecasts, lat, lon, _parse_date(date))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/places/{place_id}/recent", response_model=RecentActivity)
    def place_recent(place_id: str, date: str | None = None):
        lat, lon = _location(None, None, place_id)
        try:
            return recent_activity(svc().forecasts, lat, lon, _parse_date(date))
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
            return svc().queries.place_lists(
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
