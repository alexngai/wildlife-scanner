"""FastAPI service: species-first and place-first queries over the Level-0 baseline.

Everything returned has passed the policy layer. The service is AGPL-3.0: every response carries
a link to the corresponding source (AGPL §13) in the ``X-Source-Code`` header, and ``/source``
describes it. Set ``WILDLIFE_RADAR_SOURCE_URL`` when running a modified version.

Browsers may call the API from the origins listed in ``WILDLIFE_RADAR_CORS_ORIGINS``
(comma-separated, e.g. the frontend's Cloudflare Pages domain); none by default.
"""

from __future__ import annotations

import os
import threading
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
    HourlyForecast,
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


class _RegionHandle:
    """One served region: its bundle (or database), opened lazily, following ``CURRENT``."""

    def __init__(self, region, profiles, now, db_path, bundle_dir) -> None:
        self.region = region
        self.profiles = profiles
        self.now = now
        self.db_path = Path(db_path) if db_path else None
        self.bundles = Path(bundle_dir) / f"region={region.id}" if bundle_dir else None
        self._svc: _Services | None = None
        self._lock = threading.Lock()

    def resolve(self) -> Path:
        if self.bundles is None:
            return self.db_path  # type: ignore[return-value]
        path = current_bundle(self.bundles)
        if path is None:
            raise NotPublished(self.region.id)
        return path

    def svc(self) -> _Services:
        path = self.resolve()
        with self._lock:
            if self._svc is None or self._svc.db_path != path:
                old, self._svc = self._svc, _Services(path, self.region, self.profiles, self.now)
                if old is not None:
                    old.conn.close()
            return self._svc


class NotPublished(RuntimeError):
    pass


def _area(region) -> float:
    lon_min, lat_min, lon_max, lat_max = region.bbox
    return (lon_max - lon_min) * (lat_max - lat_min)


def create_app(
    db_path: str | Path | None = None,
    region_id: str | list[str] = "socal",
    profiles_dir: str | Path | None = None,
    source_url: str | None = None,
    now: datetime | None = None,
    bundle_dir: str | Path | None = None,
) -> FastAPI:
    """Serve one or more regions from published bundles (``bundle_dir`` is the publish root;
    each region follows its ``CURRENT`` pointer and reopens when a new version is published),
    or a single region from a database file.

    With several regions, point and place requests go to the smallest region containing the
    point (or the place's region); taxon-level requests name a ``region``."""
    ids = [region_id] if isinstance(region_id, str) else list(region_id)
    if db_path is not None and len(ids) > 1:
        raise ValueError("a database file serves one region; use bundles for several")
    profiles = ProfileLibrary(profiles_dir) if profiles_dir else ProfileLibrary()
    handles = {
        r.id: _RegionHandle(r, profiles, now, db_path, bundle_dir)
        for r in (load_region(i) for i in ids)
    }
    place_regions: dict[str, str] = {}
    for h in handles.values():
        for p in h.region.places:
            if p.place_id in place_regions:
                raise ValueError(f"place id {p.place_id!r} is in two served regions")
            place_regions[p.place_id] = h.region.id
    by_size = sorted(handles.values(), key=lambda h: _area(h.region))
    first = next(iter(handles.values()))
    if len(handles) == 1:
        first.svc()  # fail fast, as before, when the only region has nothing to serve

    def svc() -> _Services:
        """The first served region (kept for single-region callers)."""
        return first.svc()

    def _open(h: _RegionHandle) -> _Services:
        try:
            return h.svc()
        except NotPublished:
            raise HTTPException(
                status_code=503, detail=f"region {h.region.id} has no published data yet"
            ) from None

    def for_region(region: str | None) -> _Services:
        if region is None:
            if len(handles) > 1:
                raise HTTPException(
                    status_code=400, detail=f"give region (one of {', '.join(handles)})"
                )
            return _open(first)
        if region not in handles:
            raise HTTPException(status_code=404, detail="unknown region")
        return _open(handles[region])

    def for_point(lat: float, lon: float) -> _Services:
        for h in by_size:
            if h.region.contains(lat, lon):
                return _open(h)
        raise HTTPException(status_code=400, detail="location is outside the served regions")

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
    app.state.regions = handles
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
        regions = []
        for h in handles.values():
            try:
                s = h.svc()
            except NotPublished:
                regions.append({"region": h.region.id, "status": "not published"})
                continue
            fresh = _freshness(s)
            regions.append(
                {
                    "region": h.region.id,
                    "status": "stale" if any(f["status"] == "stale" for f in fresh) else "ok",
                    "model_version": s.queries.model_version,
                    "built_at": s.queries.as_of.isoformat(),
                    "bundle": s.db_path.parent.name,
                    "freshness": fresh,
                }
            )
        out = {"status": "ok", "version": __version__, "regions": regions}
        if len(regions) == 1:
            out.update(regions[0])  # single-region fields at the top level, as before
        return out

    def _freshness(s: _Services) -> list[dict]:
        from wildlife_radar.pipeline.freshness import report

        tables = {r[0] for r in s.conn.execute("SHOW TABLES").fetchall()}
        if "freshness" not in tables:
            return []
        rows = s.conn.cursor().execute("SELECT * FROM freshness").fetchall()
        return report(rows, now or datetime.now(UTC))

    @app.get("/regions")
    def regions() -> list[dict]:
        return [
            {"region": h.region.id, "name": h.region.name, "bbox": list(h.region.bbox)}
            for h in handles.values()
        ]

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
        region: str | None = None,
    ):
        return for_region(region).queries.list_taxa(
            _parse_date(date), q=q, group=group, limit=limit
        )

    @app.get("/taxa/{taxon_id}", response_model=TaxonSummary)
    def taxon(taxon_id: str, date: str | None = None, region: str | None = None):
        try:
            return for_region(region).queries.taxon_summary(taxon_id, _parse_date(date))
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None

    @app.get("/species/{taxon_id}/map", response_model=SpeciesMap)
    def species_map(
        taxon_id: str,
        date: str | None = None,
        method: str | None = None,
        region: str | None = None,
    ):
        try:
            return for_region(region).queries.species_map(
                taxon_id, _parse_date(date), method=method
            )
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None

    @app.get("/species/{taxon_id}/timing")
    def timing(taxon_id: str, region: str | None = None) -> dict:
        """When in the day (and tide) a species is recorded, relative to its group.

        Index > 1: recorded relatively more often then than other species of its group. Mixes
        activity with detectability; open and generalized taxa only."""
        target = for_region(region)
        try:
            summary = target.queries.taxon_summary(taxon_id, _parse_date(None))
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        tables = {r[0] for r in target.conn.execute("SHOW TABLES").fetchall()}
        if "timed_index" not in tables:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE)
        rows = (
            target.conn.cursor()
            .execute(
                "SELECT signal, category, n_taxon, n_effort, idx, ci_lo, ci_hi FROM timed_index "
                "WHERE region_id = ? AND taxon_id = ? ORDER BY signal",
                [target.queries.region.id, summary.taxon_id],
            )
            .fetchall()
        )
        if not rows:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE)
        signals: dict[str, list] = {}
        for signal, cat, nt, ne, idx, lo, hi in rows:
            signals.setdefault(signal, []).append(
                {
                    "category": cat,
                    "records": nt,
                    "group_records": ne,
                    "index": None if idx is None else round(idx, 3),
                    "ci": None if lo is None else [round(lo, 3), round(hi, 3)],
                }
            )
        verdicts = (
            target.conn.cursor()
            .execute(
                "SELECT term, signal, expected, peak, verdict FROM timed_scorecard "
                "WHERE region_id = ? AND taxon_id = ?",
                [target.queries.region.id, summary.taxon_id],
            )
            .fetchall()
        )
        return {
            "taxon": summary.model_dump(mode="json"),
            "signals": signals,
            "hypotheses": [
                dict(zip(("term", "signal", "expected", "peak", "verdict"), v, strict=True))
                for v in verdicts
            ],
            "note": (
                "Index > 1 means the species is recorded relatively more often in that period "
                "than others of its group (iNaturalist records with times). It reflects "
                "activity and detectability together."
            ),
        }

    @app.get("/species/{taxon_id}/calendar", response_model=Calendar)
    def calendar(
        taxon_id: str,
        lat: float | None = None,
        lon: float | None = None,
        place_id: str | None = None,
        year: int | None = None,
        method: str | None = None,
    ):
        lat, lon, target = _location(lat, lon, place_id)
        try:
            return target.queries.calendar(
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
        lat, lon, target = _location(lat, lon, place_id)
        try:
            return target.forecasts.forecast(taxon_id, lat, lon, _parse_date(date), method=method)
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/species/{taxon_id}/forecast/hourly", response_model=HourlyForecast)
    def forecast_hourly(
        taxon_id: str,
        lat: float | None = None,
        lon: float | None = None,
        place_id: str | None = None,
        date: str | None = None,
        method: str | None = None,
    ):
        """The day's forecast by local hour: when in the day (and on which tide, under which
        moon) the species is recorded relatively more often. Openly mapped species only."""
        lat, lon, target = _location(lat, lon, place_id)
        try:
            return target.forecasts.hourly(taxon_id, lat, lon, _parse_date(date), method=method)
        except NotAvailable:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/nearby/recent", response_model=RecentActivity)
    def nearby_recent(lat: float, lon: float, date: str | None = None):
        """Recently reported species near a point, and which are picking up today."""
        lat, lon, target = _location(lat, lon, None)
        try:
            return recent_activity(target.forecasts, lat, lon, _parse_date(date))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/places/{place_id}/recent", response_model=RecentActivity)
    def place_recent(place_id: str, date: str | None = None):
        lat, lon, target = _location(None, None, place_id)
        try:
            return recent_activity(target.forecasts, lat, lon, _parse_date(date))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/places")
    def places() -> list[dict]:
        return [
            {
                "place_id": p.place_id,
                "name": p.name,
                "kind": p.kind.value,
                "notes": p.notes,
                "region": h.region.id,
            }
            for h in handles.values()
            for p in h.region.places
        ]

    @app.get("/places/{place_id}/lists", response_model=PlaceLists)
    def place_lists(
        place_id: str,
        date: str | None = None,
        life_list: str | None = None,
        group: str | None = None,
    ):
        return _lists(*_location(None, None, place_id), date, life_list, group)

    @app.get("/nearby", response_model=PlaceLists)
    def nearby(
        lat: float,
        lon: float,
        date: str | None = None,
        life_list: str | None = None,
        group: str | None = None,
    ):
        return _lists(*_location(lat, lon, None), date, life_list, group)

    def _lists(
        lat: float,
        lon: float,
        target: _Services,
        day: str | None,
        life_list: str | None,
        group: str | None,
    ) -> PlaceLists:
        try:
            return target.queries.place_lists(
                lat, lon, _parse_date(day), _life_list(life_list), group=group
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    def _location(
        lat: float | None, lon: float | None, place_id: str | None
    ) -> tuple[float, float, _Services]:
        """The point to answer for, and the region that answers: the place's own region, or
        the smallest served region containing the point."""
        if place_id:
            if place_id not in place_regions:
                raise HTTPException(status_code=404, detail="unknown place")
            handle = handles[place_regions[place_id]]
            fp = handle.region.place(place_id).footprint
            return fp.lat, fp.lon, _open(handle)  # region places are point footprints
        if lat is None or lon is None:
            raise HTTPException(status_code=400, detail="give lat and lon, or place_id")
        return lat, lon, for_point(lat, lon)

    return app
