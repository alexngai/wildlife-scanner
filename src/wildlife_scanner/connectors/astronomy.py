"""Sun and moon signals computed locally with Astronomy Engine (MIT). No network needed.

Moon phase angle: 0° new, 90° first quarter, 180° full, 270° last quarter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import astronomy

from wildlife_scanner.core.licenses import CC0
from wildlife_scanner.core.signals import SignalDefinition, SignalKind, SignalValue
from wildlife_scanner.core.sources import Source, SourceKind
from wildlife_scanner.core.time import DETERMINISTIC_ISSUE_TIME, ensure_utc

SOURCE = Source(
    source_id="astronomy",
    name="Local astronomical computation (Astronomy Engine)",
    kind=SourceKind.SIGNAL,
    homepage="https://github.com/cosinekitty/astronomy",
    license=CC0,
    attribution="Sun/moon values computed with Astronomy Engine (MIT License).",
    coverage="global",
)

_DEFS = [
    ("astro.sun_altitude_deg", "deg", "Sun altitude above the horizon (refraction-corrected)"),
    ("astro.moon_altitude_deg", "deg", "Moon altitude above the horizon (refraction-corrected)"),
    ("astro.moon_illumination", "fraction", "Illuminated fraction of the lunar disk"),
    ("astro.moon_phase_angle_deg", "deg", "Moon phase angle: 0 new, 180 full"),
    ("astro.hours_since_sunset", "h", "Hours since the most recent sunset"),
]
SIGNALS = tuple(
    SignalDefinition(
        signal_id=sid,
        units=units,
        description=desc,
        kind=SignalKind.RAW,
        source_id=SOURCE.source_id,
    )
    for sid, units, desc in _DEFS
)

#: Sun altitude at civil twilight.
CIVIL_TWILIGHT_DEG = -6.0


def _to_time(dt: datetime) -> astronomy.Time:
    dt = ensure_utc(dt)
    seconds = dt.second + dt.microsecond / 1e6
    return astronomy.Time.Make(dt.year, dt.month, dt.day, dt.hour, dt.minute, seconds)


def _to_datetime(t: astronomy.Time | None) -> datetime | None:
    return None if t is None else t.Utc().replace(tzinfo=UTC)


def _altitude(body: astronomy.Body, obs: astronomy.Observer, t: astronomy.Time) -> float:
    eq = astronomy.Equator(body, t, obs, True, True)
    return astronomy.Horizon(t, obs, eq.ra, eq.dec, astronomy.Refraction.Normal).altitude


@dataclass(frozen=True)
class AstroState:
    sun_altitude_deg: float
    moon_altitude_deg: float
    moon_illumination: float
    moon_phase_angle_deg: float

    @property
    def is_night(self) -> bool:
        return self.sun_altitude_deg < CIVIL_TWILIGHT_DEG


def astro_state(lat: float, lon: float, when: datetime) -> AstroState:
    obs = astronomy.Observer(lat, lon, 0.0)
    t = _to_time(when)
    return AstroState(
        sun_altitude_deg=_altitude(astronomy.Body.Sun, obs, t),
        moon_altitude_deg=_altitude(astronomy.Body.Moon, obs, t),
        moon_illumination=astronomy.Illumination(astronomy.Body.Moon, t).phase_fraction,
        moon_phase_angle_deg=astronomy.MoonPhase(t),
    )


@dataclass(frozen=True)
class DailyEvents:
    sunrise: datetime | None
    sunset: datetime | None
    civil_dawn: datetime | None
    civil_dusk: datetime | None
    moonrise: datetime | None
    moonset: datetime | None


def daily_events(lat: float, lon: float, day: date, utc_offset_hours: float = 0.0) -> DailyEvents:
    """Rise/set/twilight events within the local calendar day (given its UTC offset)."""
    obs = astronomy.Observer(lat, lon, 0.0)
    start_dt = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(
        hours=utc_offset_hours
    )
    start = _to_time(start_dt)
    end_dt = start_dt + timedelta(days=1)

    def within(t: astronomy.Time | None) -> datetime | None:
        dt = _to_datetime(t)
        return dt if dt is not None and start_dt <= dt < end_dt else None

    rise, set_ = astronomy.Direction.Rise, astronomy.Direction.Set
    sun, moon = astronomy.Body.Sun, astronomy.Body.Moon
    return DailyEvents(
        sunrise=within(astronomy.SearchRiseSet(sun, obs, rise, start, 1)),
        sunset=within(astronomy.SearchRiseSet(sun, obs, set_, start, 1)),
        civil_dawn=within(astronomy.SearchAltitude(sun, obs, rise, start, 1, CIVIL_TWILIGHT_DEG)),
        civil_dusk=within(astronomy.SearchAltitude(sun, obs, set_, start, 1, CIVIL_TWILIGHT_DEG)),
        moonrise=within(astronomy.SearchRiseSet(moon, obs, rise, start, 1)),
        moonset=within(astronomy.SearchRiseSet(moon, obs, set_, start, 1)),
    )


def hours_since_sunset(lat: float, lon: float, when: datetime) -> float | None:
    """Hours since the most recent sunset (``None`` in polar day/night without a sunset)."""
    when = ensure_utc(when)
    obs = astronomy.Observer(lat, lon, 0.0)
    search_from = _to_time(when - timedelta(days=1, hours=1))
    last: datetime | None = None
    t = astronomy.SearchRiseSet(astronomy.Body.Sun, obs, astronomy.Direction.Set, search_from, 2)
    while t is not None:
        dt = _to_datetime(t)
        if dt is None or dt > when:
            break
        last = dt
        t = astronomy.SearchRiseSet(
            astronomy.Body.Sun, obs, astronomy.Direction.Set, t.AddDays(0.01), 2
        )
    if last is None:
        return None
    return (when - last).total_seconds() / 3600


def astronomy_signals(
    lat: float, lon: float, times: Iterable[datetime], location_key: str
) -> list[SignalValue]:
    """All astro.* signals at the given times, keyed to ``location_key``."""
    out: list[SignalValue] = []
    for when in times:
        when = ensure_utc(when)
        state = astro_state(lat, lon, when)
        values = {
            "astro.sun_altitude_deg": state.sun_altitude_deg,
            "astro.moon_altitude_deg": state.moon_altitude_deg,
            "astro.moon_illumination": state.moon_illumination,
            "astro.moon_phase_angle_deg": state.moon_phase_angle_deg,
            "astro.hours_since_sunset": hours_since_sunset(lat, lon, when),
        }
        for sid, value in values.items():
            out.append(
                SignalValue(
                    signal_id=sid,
                    location_key=location_key,
                    valid_time=when,
                    issue_time=DETERMINISTIC_ISSUE_TIME,
                    value=value,
                )
            )
    return out
