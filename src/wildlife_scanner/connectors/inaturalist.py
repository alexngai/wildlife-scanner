"""iNaturalist observations (API v1).

Terms: the API is for applications, not bulk scraping. Keep to ≤1 request/second, and use GBIF
snapshots for bulk history. Observations are licensed per record (mostly CC BY-NC); a blank
license means all rights reserved. Obscured coordinates are a random point within a 0.2° cell.

v2 is iNaturalist's preferred API; v1 is used here because its response format is stable and
well documented. Migration is isolated to ``INaturalistConnector``.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

import httpx

from wildlife_scanner.connectors.base import (
    ObservationQuery,
    RateLimiter,
    get_json,
    make_client,
)
from wildlife_scanner.core.geometry import PointFootprint
from wildlife_scanner.core.ids import hash_identifier
from wildlife_scanner.core.licenses import ALL_RIGHTS_RESERVED, parse_license
from wildlife_scanner.core.observations import (
    EvidenceGrade,
    Modality,
    Observation,
    Outcome,
    SensitivityFlags,
)
from wildlife_scanner.core.sources import ObservationProcess, ObservationType, Source, SourceKind
from wildlife_scanner.core.taxa import TaxonRef, TaxonScheme, target_group
from wildlife_scanner.core.time import Precision, TimeWindow, ensure_utc, utcnow

BASE_URL = "https://api.inaturalist.org/v1"
OBSCURED_CELL_DEG = 0.2

SOURCE = Source(
    source_id="inaturalist",
    name="iNaturalist",
    kind=SourceKind.OBSERVATION,
    homepage="https://www.inaturalist.org",
    terms_url="https://www.inaturalist.org/pages/terms",
    per_record_license=True,
    attribution="Observations from iNaturalist (www.inaturalist.org), licensed per observation.",
    coverage="global",
    observation_process=ObservationProcess(
        type=ObservationType.PRESENCE_ONLY,
        bias=("observer_density", "access", "photogenic_taxa"),
        dedup_rule="same observer, taxon, day and ~location",
        reporting_dynamics=("duplicate_reports", "media_spikes"),
        latency="minutes",
    ),
)

_GRADES = {
    "research": EvidenceGrade.C1,
    "needs_id": EvidenceGrade.C3,
    "casual": EvidenceGrade.C3,
}


def obscured_uncertainty_m(lat: float) -> float:
    """Worst-case distance between a displayed obscured point and the true location."""
    dlat_km = OBSCURED_CELL_DEG * 111.32
    dlon_km = OBSCURED_CELL_DEG * 111.32 * math.cos(math.radians(lat))
    return math.hypot(dlat_km, dlon_km) * 1000


def _lat_lon(rec: dict[str, Any]) -> tuple[float, float] | None:
    geo = rec.get("geojson") or {}
    coords = geo.get("coordinates") if isinstance(geo, dict) else None
    if coords and len(coords) == 2:
        return float(coords[1]), float(coords[0])
    loc = rec.get("location")
    if isinstance(loc, str) and "," in loc:
        lat_s, lon_s = loc.split(",", 1)
        return float(lat_s), float(lon_s)
    return None


def _time_window(rec: dict[str, Any], lon: float) -> TimeWindow | None:
    observed_at = rec.get("time_observed_at")
    if observed_at:
        dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return TimeWindow.instant(ensure_utc(dt), Precision.MINUTE)
    observed_on = rec.get("observed_on")
    if observed_on:
        # Local calendar day; approximate the zone offset from longitude.
        return TimeWindow.local_day(date.fromisoformat(observed_on[:10]), round(lon / 15))
    return None


def parse_observation(
    rec: dict[str, Any], ingested_at: datetime | None = None
) -> Observation | None:
    """Convert one API v1 observation record; returns ``None`` if unusable."""
    taxon = rec.get("taxon") or {}
    latlon = _lat_lon(rec)
    if not taxon.get("id") or latlon is None:
        return None
    lat, lon = latlon
    window = _time_window(rec, lon)
    if window is None:
        return None

    geoprivacy = rec.get("geoprivacy")
    taxon_geoprivacy = rec.get("taxon_geoprivacy")
    obscured = bool(rec.get("obscured")) or "obscured" in (geoprivacy, taxon_geoprivacy)
    accuracy = rec.get("public_positional_accuracy") or rec.get("positional_accuracy")
    uncertainty = float(accuracy) if accuracy is not None else None
    if obscured:
        uncertainty = max(uncertainty or 0.0, obscured_uncertainty_m(lat))

    photos, sounds = rec.get("photos") or [], rec.get("sounds") or []
    modality = Modality.HEAR if sounds and not photos else Modality.SEE
    obs_id = str(rec["id"])
    return Observation(
        obs_id=f"inaturalist:{obs_id}",
        source_id=SOURCE.source_id,
        source_record_id=obs_id,
        source_url=rec.get("uri") or f"https://www.inaturalist.org/observations/{obs_id}",
        taxon=TaxonRef(
            scheme=TaxonScheme.INATURALIST,
            id=str(taxon["id"]),
            name=taxon.get("name"),
            rank=taxon.get("rank"),
        ),
        footprint=PointFootprint(lat=lat, lon=lon, uncertainty_m=uncertainty),
        time=window,
        modality=modality,
        method=None,
        outcome=Outcome.PRESENCE_ONLY,
        evidence_grade=_GRADES.get(rec.get("quality_grade", ""), EvidenceGrade.C3),
        license=parse_license(rec.get("license_code"), missing=ALL_RIGHTS_RESERVED),
        sensitivity=SensitivityFlags(
            obscured=obscured, geoprivacy=geoprivacy, taxon_geoprivacy=taxon_geoprivacy
        ),
        ingested_at=ingested_at or utcnow(),
        extras={
            "quality_grade": rec.get("quality_grade"),
            "common_name": taxon.get("preferred_common_name"),
            "n_photos": len(photos),
            "n_sounds": len(sounds),
            "group": target_group(inat_iconic=taxon.get("iconic_taxon_name")),
            "observer_hash": hash_identifier(str((rec.get("user") or {}).get("id") or "")),
        },
    )


class INaturalistConnector:
    source = SOURCE

    def __init__(
        self,
        client: httpx.Client | None = None,
        per_page: int = 200,
        limiter: RateLimiter | None = None,
        quality_grades: tuple[str, ...] = ("research", "needs_id"),
    ) -> None:
        self.client = client or make_client()
        self.per_page = min(per_page, 200)
        self.limiter = limiter if limiter is not None else RateLimiter(1.0)
        self.quality_grades = quality_grades

    def build_params(self, query: ObservationQuery, id_above: int | None = None) -> dict:
        params: dict[str, Any] = {
            "per_page": self.per_page,
            "order_by": "id",
            "order": "asc",
            "quality_grade": ",".join(self.quality_grades),
        }
        if query.source_taxon_id:
            params["taxon_id"] = query.source_taxon_id
        elif query.taxon_name:
            params["taxon_name"] = query.taxon_name
        if query.bbox:
            lon_min, lat_min, lon_max, lat_max = query.bbox
            params |= {"swlat": lat_min, "swlng": lon_min, "nelat": lat_max, "nelng": lon_max}
        if query.start:
            params["d1"] = query.start.isoformat()
        if query.end:
            params["d2"] = query.end.isoformat()
        if query.updated_since:
            params["updated_since"] = ensure_utc(query.updated_since).isoformat()
        if id_above is not None:
            params["id_above"] = id_above
        return params

    def fetch(self, query: ObservationQuery) -> Iterator[Observation]:
        """Keyset-paginated fetch (``id_above``), which avoids the 10k offset cap."""
        id_above: int | None = None
        yielded = 0
        while True:
            payload = get_json(
                self.client,
                f"{BASE_URL}/observations",
                self.build_params(query, id_above),
                self.limiter,
            )
            results = payload.get("results") or []
            if not results:
                return
            ingested_at = utcnow()
            for rec in results:
                obs = parse_observation(rec, ingested_at)
                if obs is None:
                    continue
                yield obs
                yielded += 1
                if query.limit is not None and yielded >= query.limit:
                    return
            id_above = max(int(r["id"]) for r in results)
            if len(results) < self.per_page:
                return
