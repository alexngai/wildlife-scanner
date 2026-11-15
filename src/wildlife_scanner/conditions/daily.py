"""Daily environmental signals at stations (the Phase-3 conditions inputs).

Observation records from GBIF snapshots carry dates, not times, so conditions are daily:

========================  ===========================================  ==========  ========
signal                    source                                       family      reach
========================  ===========================================  ==========  ========
``ocean.sst_c``           NOAA CO-OPS water temperature, daily mean    marine      25 km
``ocean.sst_anomaly_c``   minus the station's day-of-year normal       marine      25 km
``air.temp_c``            NOAA CO-OPS air temperature, daily mean      air         40 km
``air.temp_anomaly_c``    minus the station's day-of-year normal       air         40 km
``wind.speed_ms``         NOAA CO-OPS wind speed, daily mean           air         40 km
``tide.daily_low_m``      lowest predicted low water (MLLW)            tide        40 km
``tide.daily_range_m``    highest high minus lowest low                tide        40 km
``astro.moon_illumination``  computed (Astronomy Engine), local midnight  astro    anywhere
``astro.moon_phase``      phase angle (cyclic), local midnight          astro       anywhere
========================  ===========================================  ==========  ========

Days are local days (UTC offset from the station's longitude). Anomaly normals are computed
from days before a cutoff, so backtests don't learn from the future.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import duckdb
import httpx

from wildlife_scanner.connectors.base import ConnectorError, RateLimiter, get_json, make_client

COOPS_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

SIGNAL_DAILY_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_daily (
    station_id VARCHAR, signal_id VARCHAR, day DATE, value DOUBLE,
    PRIMARY KEY (station_id, signal_id, day)
)
"""


@dataclass(frozen=True)
class DailySignal:
    signal_id: str
    family: str
    reach_km: float | None
    """Maximum distance from a station; ``None`` = computed anywhere."""
    base: str | None = None
    """For anomalies: the signal they are computed from."""
    description: str = ""


DAILY_SIGNALS: dict[str, DailySignal] = {
    s.signal_id: s
    for s in (
        DailySignal("ocean.sst_c", "marine", 25, description="daily mean water temperature (°C)"),
        DailySignal(
            "ocean.sst_anomaly_c",
            "marine",
            25,
            base="ocean.sst_c",
            description="water temperature minus the day-of-year normal (°C)",
        ),
        DailySignal("air.temp_c", "air", 40, description="daily mean air temperature (°C)"),
        DailySignal(
            "air.temp_anomaly_c",
            "air",
            40,
            base="air.temp_c",
            description="air temperature minus the day-of-year normal (°C)",
        ),
        DailySignal("wind.speed_ms", "air", 40, description="daily mean wind speed (m/s)"),
        DailySignal("tide.daily_low_m", "tide", 40, description="lowest predicted low (m MLLW)"),
        DailySignal("tide.daily_range_m", "tide", 40, description="daily tidal range (m)"),
        DailySignal("astro.moon_illumination", "astro", None, description="0 (new) to 1 (full)"),
        DailySignal("astro.moon_phase", "astro", None, description="phase angle (degrees)"),
    )
}

#: CO-OPS product → (signal, value field).
COOPS_PRODUCTS = {
    "water_temperature": ("ocean.sst_c", "v"),
    "air_temperature": ("air.temp_c", "v"),
    "wind": ("wind.speed_ms", "s"),
}


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(SIGNAL_DAILY_SCHEMA)


def local_day(t: datetime, lon: float) -> date:
    return (t + timedelta(hours=round(lon / 15))).date()


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


class CoopsDailyFetcher:
    """Hourly CO-OPS observations and hi/lo tide predictions, aggregated to local days."""

    def __init__(self, client: httpx.Client | None = None, limiter: RateLimiter | None = None):
        self.client = client or make_client(timeout=90)
        self.limiter = limiter if limiter is not None else RateLimiter(0.5)

    def _get(self, params: dict) -> dict:
        payload = get_json(
            self.client,
            COOPS_URL,
            {
                **params,
                "units": "metric",
                "time_zone": "gmt",
                "format": "json",
                "application": "wildlife-scanner",
            },
            self.limiter,
        )
        if "error" in payload:
            raise ConnectorError(payload["error"].get("message", "CO-OPS error"))
        return payload

    def observations(
        self, station_id: str, lon: float, product: str, start: date, end: date
    ) -> list[tuple[str, str, date, float]]:
        signal_id, field = COOPS_PRODUCTS[product]
        sums: dict[date, list[float]] = defaultdict(list)
        for year_start, year_end in _years(start, end):
            try:
                payload = self._get(
                    {
                        "product": product,
                        "station": station_id,
                        "begin_date": year_start.strftime("%Y%m%d"),
                        "end_date": year_end.strftime("%Y%m%d"),
                        "interval": "h",
                    }
                )
            except ConnectorError:
                continue  # product not offered for this period
            for row in payload.get("data") or []:
                try:
                    value = float(row[field])
                except (KeyError, TypeError, ValueError):
                    continue
                sums[local_day(_parse_time(row["t"]), lon)].append(value)
        # Days with too few hourly values are dropped (partial outages).
        return [
            (station_id, signal_id, d, sum(v) / len(v))
            for d, v in sorted(sums.items())
            if len(v) >= 12
        ]

    def tides(
        self, station_id: str, lon: float, start: date, end: date
    ) -> list[tuple[str, str, date, float]]:
        lows: dict[date, list[float]] = defaultdict(list)
        highs: dict[date, list[float]] = defaultdict(list)
        for year_start, year_end in _years(start, end):
            payload = self._get(
                {
                    "product": "predictions",
                    "station": station_id,
                    "datum": "MLLW",
                    "interval": "hilo",
                    "begin_date": year_start.strftime("%Y%m%d"),
                    "end_date": year_end.strftime("%Y%m%d"),
                }
            )
            for row in payload.get("predictions") or []:
                d = local_day(_parse_time(row["t"]), lon)
                (lows if row.get("type") == "L" else highs)[d].append(float(row["v"]))
        out = []
        for d in sorted(set(lows) | set(highs)):
            if lows.get(d):
                out.append((station_id, "tide.daily_low_m", d, min(lows[d])))
                if highs.get(d):
                    out.append((station_id, "tide.daily_range_m", d, max(highs[d]) - min(lows[d])))
        return out


def _years(start: date, end: date) -> Iterable[tuple[date, date]]:
    year = start.year
    while year <= end.year:
        yield max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
        year += 1


def store_rows(conn: duckdb.DuckDBPyConnection, rows: Sequence[tuple]) -> int:
    ensure_schema(conn)
    if rows:
        conn.executemany("INSERT OR REPLACE INTO signal_daily VALUES (?, ?, ?, ?)", rows)
    return len(rows)


def moon_on(day: date, lon: float = -117.0) -> tuple[float, float]:
    """``(illumination 0–1, phase angle °)`` at local midnight starting ``day``."""
    from wildlife_scanner.connectors.astronomy import astro_state

    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(hours=round(lon / 15))
    state = astro_state(0.0, lon, midnight + timedelta(days=1))
    return state.moon_illumination, state.moon_phase_angle_deg


def normals(
    conn: duckdb.DuckDBPyConnection, signal_id: str, before: date | None, half_window: int = 15
) -> dict[tuple[str, int], float]:
    """``(station, day of year) → mean`` over days before ``before``, smoothed ±``half_window``."""
    rows = conn.execute(
        """
        SELECT station_id, dayofyear(day) AS doy, avg(value), count(*) FROM signal_daily
        WHERE signal_id = ? AND (?::DATE IS NULL OR day < ?::DATE) GROUP BY 1, 2
        """,
        [signal_id, before, before],
    ).fetchall()
    by_station: dict[str, dict[int, tuple[float, int]]] = defaultdict(dict)
    for station, doy, mean, n in rows:
        by_station[station][int(doy)] = (float(mean), int(n))
    out: dict[tuple[str, int], float] = {}
    for station, days in by_station.items():
        for doy in range(1, 367):
            total = weight = 0.0
            for k in range(-half_window, half_window + 1):
                d = (doy - 1 + k) % 366 + 1
                if d in days:
                    mean, n = days[d]
                    total += mean * n
                    weight += n
            if weight:
                out[(station, doy)] = total / weight
    return out


def circular(angle_deg: float) -> tuple[float, float]:
    rad = math.radians(angle_deg)
    return math.sin(rad), math.cos(rad)
