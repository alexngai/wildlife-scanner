"""Connector tests use recorded-style payloads and httpx.MockTransport — no network access."""

from datetime import UTC, date, datetime

import httpx
import pytest

from wildlife_radar.connectors.base import (
    ConnectorError,
    ObservationQuery,
    RateLimiter,
    make_client,
    user_agent,
)
from wildlife_radar.connectors.gbif import GBIFConnector, parse_dwc_record, parse_event_date
from wildlife_radar.connectors.inaturalist import (
    INaturalistConnector,
    obscured_uncertainty_m,
    parse_observation,
)
from wildlife_radar.connectors.noaa_coops import CoopsTideConnector, parse_predictions
from wildlife_radar.core import EvidenceGrade, Modality, Outcome
from wildlife_radar.core.time import DETERMINISTIC_ISSUE_TIME, Precision
from wildlife_radar.signals import SignalStore
from wildlife_radar.signals.derived import tide_stage

NO_WAIT = RateLimiter(0)

# --------------------------------------------------------------------------- iNaturalist

INAT_REC = {
    "id": 101,
    "uri": "https://www.inaturalist.org/observations/101",
    "observed_on": "2025-05-03",
    "time_observed_at": "2025-05-03T19:45:00-07:00",
    "geojson": {"type": "Point", "coordinates": [-117.272, 32.851]},
    "location": "32.851,-117.272",
    "positional_accuracy": 25,
    "public_positional_accuracy": 25,
    "obscured": False,
    "geoprivacy": None,
    "taxon_geoprivacy": None,
    "quality_grade": "research",
    "license_code": "cc-by-nc",
    "taxon": {"id": 99999, "name": "Atractoscion nobilis", "rank": "species"},
    "photos": [{"id": 1}],
    "sounds": [],
}


def test_inat_parse_basic():
    o = parse_observation(INAT_REC)
    assert o.obs_id == "inaturalist:101"
    assert o.taxon.id == "99999" and o.taxon.name == "Atractoscion nobilis"
    assert (o.footprint.lat, o.footprint.lon, o.footprint.uncertainty_m) == (32.851, -117.272, 25)
    assert o.time.start == datetime(2025, 5, 4, 2, 45, tzinfo=UTC)
    assert o.time.precision is Precision.MINUTE
    assert o.license.id == "CC-BY-NC-4.0"
    assert o.evidence_grade is EvidenceGrade.C1
    assert o.outcome is Outcome.PRESENCE_ONLY and o.modality is Modality.SEE


def test_inat_obscured_and_date_only_and_unlicensed():
    rec = {
        **INAT_REC,
        "obscured": True,
        "taxon_geoprivacy": "obscured",
        "time_observed_at": None,
        "license_code": None,
        "public_positional_accuracy": 1000,
        "quality_grade": "needs_id",
        "photos": [],
        "sounds": [{"id": 9}],
    }
    o = parse_observation(rec)
    assert o.sensitivity.obscured
    assert o.footprint.uncertainty_m == pytest.approx(obscured_uncertainty_m(32.851))
    assert o.footprint.uncertainty_m > 28_000
    assert o.time.precision is Precision.DAY
    assert o.time.start == datetime(2025, 5, 3, 8, tzinfo=UTC)  # local day, offset from longitude
    assert o.license.id == "ALL-RIGHTS-RESERVED"
    assert o.evidence_grade is EvidenceGrade.C3
    assert o.modality is Modality.HEAR


def test_inat_unusable_records():
    assert parse_observation({**INAT_REC, "taxon": None}) is None
    assert parse_observation({**INAT_REC, "geojson": None, "location": None}) is None


def _inat_pages(request: httpx.Request) -> httpx.Response:
    id_above = int(request.url.params.get("id_above", 0))
    ids = [i for i in (1, 2, 3) if i > id_above][:2]
    return httpx.Response(200, json={"results": [{**INAT_REC, "id": i} for i in ids]})


def test_inat_keyset_pagination():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return _inat_pages(request)

    conn = INaturalistConnector(
        client=make_client(transport=httpx.MockTransport(handler)), per_page=2, limiter=NO_WAIT
    )
    query = ObservationQuery(taxon_name="Atractoscion nobilis", bbox=(-121, 32.4, -117, 34.6))
    got = [o.source_record_id for o in conn.fetch(query)]
    assert got == ["1", "2", "3"]
    assert "id_above" not in seen[0] and seen[1]["id_above"] == "2"
    assert seen[0]["taxon_name"] == "Atractoscion nobilis"
    assert seen[0]["swlat"] == "32.4" and seen[0]["nelng"] == "-117.0"

    limited = list(conn.fetch(query.model_copy(update={"limit": 1})))
    assert len(limited) == 1


def test_http_errors_become_connector_errors():
    conn = INaturalistConnector(
        client=make_client(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
        limiter=NO_WAIT,
    )
    with pytest.raises(ConnectorError, match="429"):
        list(conn.fetch(ObservationQuery(taxon_name="X y")))


def test_query_validation():
    with pytest.raises(ValueError):
        ObservationQuery()
    with pytest.raises(ValueError):
        ObservationQuery(taxon_name="X y", bbox=(-117, 32, -121, 34))


def test_user_agent_override(monkeypatch):
    assert user_agent().startswith("wildlife-radar/")
    monkeypatch.setenv("WILDLIFE_RADAR_USER_AGENT", "my-deployment (ops@example.org)")
    assert user_agent() == "my-deployment (ops@example.org)"


# --------------------------------------------------------------------------- GBIF

GBIF_REC = {
    "key": 4000000001,
    "gbifID": "4000000001",
    "datasetKey": "50c9509d-22c7-4a22-a47d-8c48425ef4a7",
    "occurrenceID": "https://www.inaturalist.org/observations/101",
    "basisOfRecord": "HUMAN_OBSERVATION",
    "occurrenceStatus": "PRESENT",
    "taxonKey": 5000001,
    "speciesKey": 5000001,
    "species": "Atractoscion nobilis",
    "taxonRank": "SPECIES",
    "decimalLatitude": 32.85,
    "decimalLongitude": -117.27,
    "coordinateUncertaintyInMeters": 30.0,
    "eventDate": "2024-06-01T18:30:00Z",
    "license": "http://creativecommons.org/licenses/by-nc/4.0/legalcode",
    "issues": ["COORDINATE_ROUNDED"],
}


def test_gbif_api_record():
    o = parse_dwc_record(GBIF_REC)
    assert o.obs_id == "gbif:4000000001"
    assert o.taxon.id == "5000001" and o.taxon.rank == "species"
    assert o.time.start == datetime(2024, 6, 1, 18, 30, tzinfo=UTC)
    assert o.evidence_grade is EvidenceGrade.C1  # iNaturalist research-grade dataset
    assert o.license.id == "CC-BY-NC-4.0"
    assert o.outcome is Outcome.PRESENCE_ONLY
    assert o.extras["issues"] == ["COORDINATE_ROUNDED"]


def test_gbif_snapshot_style_absence_record():
    snapshot_row = {
        "gbifid": "7",
        "specieskey": 5000001,
        "decimallatitude": 33.0,
        "decimallongitude": -118.0,
        "eventdate": "2023-07",
        "occurrencestatus": "ABSENT",
        "basisofrecord": "HUMAN_OBSERVATION",
        "license": "CC_BY_4_0",
        "samplingprotocol": "Reef transect",
        "samplingeffort": "30 minutes",
    }
    o = parse_dwc_record(snapshot_row)
    assert o.outcome is Outcome.NOT_DETECTED
    assert o.time.precision is Precision.MONTH
    assert o.effort.duration_min == 30
    assert o.license.id == "CC-BY-4.0"
    assert o.evidence_grade is EvidenceGrade.C3


def test_gbif_event_dates():
    w = parse_event_date("2020-05-01/2020-05-03", -117.27)
    assert w.start == datetime(2020, 5, 1, 8, tzinfo=UTC)
    assert w.end == datetime(2020, 5, 4, 8, tzinfo=UTC)
    year = parse_event_date("2024", 0.0)
    assert (year.end - year.start).days == 366
    assert parse_event_date(None, 0.0) is None
    assert parse_dwc_record({**GBIF_REC, "decimalLatitude": None}) is None


def test_gbif_offset_pagination():
    offsets = []

    def handler(request):
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        if offset == 0:
            body = {"results": [GBIF_REC, {**GBIF_REC, "gbifID": "2"}], "endOfRecords": False}
        else:
            body = {"results": [{**GBIF_REC, "gbifID": "3"}], "endOfRecords": True}
        return httpx.Response(200, json=body)

    conn = GBIFConnector(
        client=make_client(transport=httpx.MockTransport(handler)), page_size=2, limiter=NO_WAIT
    )
    got = list(conn.fetch(ObservationQuery(taxon_name="Atractoscion nobilis")))
    assert [o.source_record_id for o in got] == ["4000000001", "2", "3"]
    assert offsets == [0, 2]


# --------------------------------------------------------------------------- NOAA CO-OPS

HOURLY = {
    "predictions": [
        {"t": "2026-11-15 00:00", "v": "1.234"},
        {"t": "2026-11-15 01:00", "v": "1.100"},
    ]
}
HILO = {
    "predictions": [
        {"t": "2026-11-15 03:12", "v": "1.650", "type": "H"},
        {"t": "2026-11-15 09:40", "v": "-0.120", "type": "L"},
    ]
}


def test_coops_parse():
    hourly = parse_predictions(HOURLY, "9410230", "h")
    assert [v.value for v in hourly] == [1.234, 1.1]
    assert hourly[0].signal_id == "tide.height_m"
    assert hourly[0].location_key == "station:noaa-coops:9410230"
    assert hourly[0].issue_time == DETERMINISTIC_ISSUE_TIME
    extremes = parse_predictions(HILO, "9410230", "hilo")
    assert [v.attrs["type"] for v in extremes] == ["H", "L"]

    store = SignalStore()
    store.add(extremes)
    series = store.as_of("tide.extreme_m", "station:noaa-coops:9410230", datetime.now(UTC))
    assert tide_stage(series, datetime(2026, 11, 15, 6, tzinfo=UTC)) == "falling"


def test_coops_error_payload():
    with pytest.raises(ConnectorError, match="No Predictions"):
        parse_predictions({"error": {"message": "No Predictions data was found"}}, "1", "h")


def test_coops_chunks_long_ranges():
    calls = []

    def handler(request):
        calls.append((request.url.params["begin_date"], request.url.params["end_date"]))
        return httpx.Response(200, json={"predictions": []})

    conn = CoopsTideConnector(
        client=make_client(transport=httpx.MockTransport(handler)), limiter=NO_WAIT
    )
    conn.predictions("9410230", date(2026, 1, 1), date(2026, 3, 11), "hilo")
    assert calls == [("20260101", "20260131"), ("20260201", "20260303"), ("20260304", "20260311")]
