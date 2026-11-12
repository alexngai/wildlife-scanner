"""GBIF occurrences (search API) and a Darwin Core record parser.

``parse_dwc_record`` accepts both the API's camelCase records and the lower-case columns of the
monthly GBIF Parquet snapshots, so the same parser serves small API pulls and bulk ingestion.

The search API is for modest queries: it caps offset paging (~100k records). For bulk work use
GBIF downloads (which get a citable DOI) or the cloud snapshots, and cite per GBIF guidelines.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterator, Mapping
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from wildlife_radar.connectors.base import ObservationQuery, RateLimiter, get_json, make_client
from wildlife_radar.core.geometry import PointFootprint
from wildlife_radar.core.ids import hash_identifier
from wildlife_radar.core.licenses import UNKNOWN, parse_license
from wildlife_radar.core.observations import (
    Effort,
    EvidenceGrade,
    Modality,
    Observation,
    Outcome,
)
from wildlife_radar.core.sources import ObservationProcess, ObservationType, Source, SourceKind
from wildlife_radar.core.taxa import TaxonRef, TaxonScheme, target_group
from wildlife_radar.core.time import Precision, TimeWindow, ensure_utc, utcnow

BASE_URL = "https://api.gbif.org/v1"
MAX_OFFSET = 100_000
INATURALIST_RG_DATASET = "50c9509d-22c7-4a22-a47d-8c48425ef4a7"

SOURCE = Source(
    source_id="gbif",
    name="GBIF — Global Biodiversity Information Facility",
    kind=SourceKind.OBSERVATION,
    homepage="https://www.gbif.org",
    terms_url="https://www.gbif.org/terms",
    per_record_license=True,
    attribution="GBIF.org occurrence data; cite download DOIs per GBIF citation guidelines.",
    coverage="global",
    observation_process=ObservationProcess(
        type=ObservationType.PRESENCE_ONLY,
        bias=("observer_density", "access", "publisher_mix"),
        dedup_rule="occurrenceID / catalogNumber; iNaturalist records duplicate the iNat API",
        latency="days to months (publisher dependent)",
    ),
    notes=(
        "Mostly presence-only; survey datasets with occurrenceStatus=ABSENT carry non-detections."
    ),
)

_SPECIMEN_LIKE = {"PRESERVED_SPECIMEN", "FOSSIL_SPECIMEN", "LIVING_SPECIMEN", "MATERIAL_CITATION"}
_MINUTES = re.compile(r"(\d+(?:\.\d+)?)\s*(min|minute|minutes|h|hr|hrs|hour|hours)\b", re.I)


class _CI(Mapping[str, Any]):
    """Case-insensitive view over a record (API camelCase vs. snapshot lowercase)."""

    def __init__(self, rec: Mapping[str, Any]) -> None:
        self._d = {str(k).lower(): v for k, v in rec.items()}

    def __getitem__(self, key: str) -> Any:
        return self._d[key.lower()]

    def __iter__(self):
        return iter(self._d)

    def __len__(self) -> int:
        return len(self._d)

    def get(self, key: str, default: Any = None) -> Any:
        v = self._d.get(key.lower(), default)
        return default if v == "" else v


def parse_event_date(value: Any, lon: float) -> TimeWindow | None:
    """Parse DwC ``eventDate``: instants, dates, months, years and ``a/b`` intervals."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return TimeWindow.local_day(value.date(), round(lon / 15))
        return TimeWindow.instant(ensure_utc(value), Precision.MINUTE)
    s = str(value).strip()
    if "/" in s:
        a, b = s.split("/", 1)
        wa, wb = parse_event_date(a, lon), parse_event_date(b, lon)
        if wa is None or wb is None:
            return None
        end = wb.end if not wb.is_instant else wb.start
        return TimeWindow(start=wa.start, end=max(end, wa.start), precision=Precision.DAY)
    if "T" in s:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return TimeWindow.local_day(dt.date(), round(lon / 15))
        return TimeWindow.instant(ensure_utc(dt), Precision.MINUTE)
    parts = s.split("-")
    offset = round(lon / 15)
    if len(parts) == 3:
        return TimeWindow.local_day(date.fromisoformat(s), offset)
    if len(parts) == 2:
        y, m = int(parts[0]), int(parts[1])
        start = TimeWindow.local_day(date(y, m, 1), offset).start
        nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        end = TimeWindow.local_day(nxt, offset).start
        return TimeWindow(start=start, end=end, precision=Precision.MONTH)
    if len(parts) == 1 and parts[0].isdigit():
        y = int(parts[0])
        start = TimeWindow.local_day(date(y, 1, 1), offset).start
        return TimeWindow(
            start=start,
            end=start + timedelta(days=366 if calendar.isleap(y) else 365),
            precision=Precision.YEAR,
        )
    return None


def _effort(rec: _CI) -> Effort | None:
    text = rec.get("samplingEffort")
    if not text:
        return None
    m = _MINUTES.search(str(text))
    if not m:
        return None
    qty = float(m.group(1))
    minutes = qty if m.group(2).lower().startswith("m") else qty * 60
    return Effort(duration_min=minutes)


def parse_dwc_record(
    record: Mapping[str, Any], ingested_at: datetime | None = None, source_id: str = "gbif"
) -> Observation | None:
    rec = _CI(record)
    lat, lon = rec.get("decimalLatitude"), rec.get("decimalLongitude")
    taxon_key = rec.get("speciesKey") or rec.get("taxonKey")
    if lat is None or lon is None or taxon_key is None:
        return None
    lat, lon = float(lat), float(lon)
    window = _record_window(rec, lon)
    if window is None:
        return None

    basis = str(rec.get("basisOfRecord") or "").upper()
    status = str(rec.get("occurrenceStatus") or "PRESENT").upper()
    count = rec.get("individualCount")
    effort = _effort(rec)
    if status == "ABSENT":
        outcome = Outcome.NOT_DETECTED
    elif effort is not None or rec.get("samplingProtocol"):
        outcome = Outcome.DETECTED
    else:
        outcome = Outcome.PRESENCE_ONLY

    if basis in _SPECIMEN_LIKE or basis == "MATERIAL_SAMPLE":
        grade = EvidenceGrade.C1
    elif basis == "MACHINE_OBSERVATION":
        grade = EvidenceGrade.M
    elif (
        rec.get("datasetKey") == INATURALIST_RG_DATASET or rec.get("media") or rec.get("mediaType")
    ):
        grade = EvidenceGrade.C1
    else:
        grade = EvidenceGrade.C3

    modality = {
        "HUMAN_OBSERVATION": Modality.SEE,
        "MACHINE_OBSERVATION": Modality.SENSOR,
        "MATERIAL_SAMPLE": Modality.DNA,
    }.get(basis, Modality.UNKNOWN)

    gbif_id = str(rec.get("gbifID") or rec.get("key") or "")
    uncertainty = rec.get("coordinateUncertaintyInMeters")
    return Observation(
        obs_id=f"{source_id}:{gbif_id}" if gbif_id else f"{source_id}:{rec.get('occurrenceID')}",
        source_id=source_id,
        source_record_id=gbif_id or None,
        source_url=f"https://www.gbif.org/occurrence/{gbif_id}" if gbif_id else None,
        taxon=TaxonRef(
            scheme=TaxonScheme.GBIF,
            id=str(taxon_key),
            name=rec.get("species") or rec.get("scientificName"),
            rank=(str(rec.get("taxonRank")).lower() if rec.get("taxonRank") else None),
        ),
        footprint=PointFootprint(
            lat=lat, lon=lon, uncertainty_m=float(uncertainty) if uncertainty else None
        ),
        time=window,
        modality=modality,
        method=rec.get("samplingProtocol"),
        effort=effort,
        outcome=outcome,
        count=float(count) if count not in (None, "") else None,
        evidence_grade=grade,
        license=parse_license(rec.get("license"), missing=UNKNOWN),
        ingested_at=ingested_at or utcnow(),
        extras={
            "dataset_key": rec.get("datasetKey"),
            "occurrence_id": rec.get("occurrenceID"),
            "basis_of_record": basis or None,
            "event_id": rec.get("eventID") or None,
            "issues": list(rec.get("issues") or rec.get("issue") or []),
            "license_raw": rec.get("license"),
            "group": target_group(rec.get("kingdom"), rec.get("phylum"), rec.get("class")),
            "observer_hash": hash_identifier(
                rec.get("recordedByID") or rec.get("recordedBy") or None
            ),
        },
    )


def _record_window(rec: _CI, lon: float) -> TimeWindow | None:
    """Event time, honoring GBIF's year/month/day columns when the day is unknown.

    In snapshots ``eventDate`` is a naive timestamp set to the 1st of the month (or year) when
    the day is unknown; the separate ``year``/``month``/``day`` fields carry the real precision.
    """
    has_ymd = any(k in rec for k in ("year", "month", "day"))
    if has_ymd and rec.get("day") is None:
        year, month = rec.get("year"), rec.get("month")
        if year and month:
            return parse_event_date(f"{int(year):04d}-{int(month):02d}", lon)
        if year:
            return parse_event_date(f"{int(year):04d}", lon)
        return None
    return parse_event_date(rec.get("eventDate"), lon)


class GBIFConnector:
    source = SOURCE

    def __init__(
        self,
        client: httpx.Client | None = None,
        page_size: int = 300,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.client = client or make_client()
        self.page_size = min(page_size, 300)
        self.limiter = limiter if limiter is not None else RateLimiter(0.5)

    def build_params(self, query: ObservationQuery, offset: int = 0) -> dict:
        params: dict[str, Any] = {
            "limit": self.page_size,
            "offset": offset,
            "hasCoordinate": "true",
            "hasGeospatialIssue": "false",
        }
        if query.source_taxon_id:
            params["taxonKey"] = query.source_taxon_id
        elif query.taxon_name:
            params["scientificName"] = query.taxon_name
        if query.bbox:
            lon_min, lat_min, lon_max, lat_max = query.bbox
            params["decimalLatitude"] = f"{lat_min},{lat_max}"
            params["decimalLongitude"] = f"{lon_min},{lon_max}"
        if query.start or query.end:
            start = (query.start or date(1700, 1, 1)).isoformat()
            end = (query.end or utcnow().date()).isoformat()
            params["eventDate"] = f"{start},{end}"
        if query.updated_since:
            since = ensure_utc(query.updated_since).date().isoformat()
            params["lastInterpreted"] = f"{since},*"
        return params

    def fetch(self, query: ObservationQuery) -> Iterator[Observation]:
        offset = 0
        yielded = 0
        while offset < MAX_OFFSET:
            payload = get_json(
                self.client,
                f"{BASE_URL}/occurrence/search",
                self.build_params(query, offset),
                self.limiter,
            )
            results = payload.get("results") or []
            ingested_at = utcnow()
            for rec in results:
                obs = parse_dwc_record(rec, ingested_at)
                if obs is None:
                    continue
                yield obs
                yielded += 1
                if query.limit is not None and yielded >= query.limit:
                    return
            if payload.get("endOfRecords", True) or not results:
                return
            offset += len(results)
