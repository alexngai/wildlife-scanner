"""NOAA CO-OPS tide predictions (US federal data, public domain).

Harmonic tide predictions are deterministic and published years ahead, so they carry
``DETERMINISTIC_ISSUE_TIME``. Requests are chunked to ≤31 days to stay within API size limits.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import httpx

from wildlife_radar.connectors.base import ConnectorError, RateLimiter, get_json, make_client
from wildlife_radar.core.licenses import PUBLIC_DOMAIN_US_GOV
from wildlife_radar.core.signals import SignalDefinition, SignalKind, SignalValue
from wildlife_radar.core.sources import Source, SourceKind
from wildlife_radar.core.time import DETERMINISTIC_ISSUE_TIME

BASE_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
MAX_CHUNK_DAYS = 31

SOURCE = Source(
    source_id="noaa-coops",
    name="NOAA CO-OPS Tides & Currents",
    kind=SourceKind.SIGNAL,
    homepage="https://tidesandcurrents.noaa.gov",
    terms_url="https://tidesandcurrents.noaa.gov/disclaimers.html",
    license=PUBLIC_DOMAIN_US_GOV,
    attribution="Tide predictions from NOAA/NOS/CO-OPS.",
    coverage="US coastal stations",
)

SIGNALS = (
    SignalDefinition(
        signal_id="tide.height_m",
        units="m above MLLW",
        description="Predicted tide height (hourly or 6-minute)",
        kind=SignalKind.RAW,
        source_id=SOURCE.source_id,
    ),
    SignalDefinition(
        signal_id="tide.extreme_m",
        units="m above MLLW",
        description="Predicted high/low tide events (attrs.type is H or L)",
        kind=SignalKind.RAW,
        source_id=SOURCE.source_id,
    ),
)

Interval = Literal["h", "6", "hilo"]


def station_key(station_id: str) -> str:
    return f"station:noaa-coops:{station_id}"


def _chunks(start: date, end: date) -> Iterator[tuple[date, date]]:
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=MAX_CHUNK_DAYS - 1), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


def parse_predictions(payload: dict, station_id: str, interval: Interval) -> list[SignalValue]:
    if "error" in payload:
        message = payload["error"].get("message", "unknown error")
        raise ConnectorError(f"NOAA CO-OPS error for station {station_id}: {message}")
    signal_id = "tide.extreme_m" if interval == "hilo" else "tide.height_m"
    out = []
    for row in payload.get("predictions", []):
        valid = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        attrs: dict[str, str | float] = {"datum": "MLLW"}
        if interval == "hilo" and row.get("type"):
            attrs["type"] = row["type"]
        out.append(
            SignalValue(
                signal_id=signal_id,
                location_key=station_key(station_id),
                valid_time=valid,
                issue_time=DETERMINISTIC_ISSUE_TIME,
                value=float(row["v"]) if row.get("v") not in (None, "") else None,
                attrs=attrs,
            )
        )
    return out


class CoopsTideConnector:
    source = SOURCE

    def __init__(
        self,
        client: httpx.Client | None = None,
        application: str = "wildlife-radar",
        limiter: RateLimiter | None = None,
    ) -> None:
        self.client = client or make_client()
        self.application = application
        self.limiter = limiter if limiter is not None else RateLimiter(0.5)

    def build_params(self, station_id: str, start: date, end: date, interval: Interval) -> dict:
        return {
            "product": "predictions",
            "station": station_id,
            "begin_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
            "datum": "MLLW",
            "time_zone": "gmt",
            "units": "metric",
            "interval": interval,
            "format": "json",
            "application": self.application,
        }

    def predictions(
        self, station_id: str, start: date, end: date, interval: Interval = "h"
    ) -> list[SignalValue]:
        if end < start:
            raise ValueError("end before start")
        values: list[SignalValue] = []
        for a, b in _chunks(start, end):
            payload = get_json(
                self.client, BASE_URL, self.build_params(station_id, a, b, interval), self.limiter
            )
            values.extend(parse_predictions(payload, station_id, interval))
        return values
