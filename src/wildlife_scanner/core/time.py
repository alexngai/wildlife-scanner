"""Time utilities: UTC normalization, time windows, coarsening and seasonal windows.

Conventions:
- Every datetime inside the framework is timezone-aware UTC. Naive datetimes are rejected.
- Windows are half-open ``[start, end)``; an instant has ``start == end``.
- Signals carry both ``valid_time`` (what time the value describes) and ``issue_time`` (when it
  became known). Values computable arbitrarily far in advance use ``DETERMINISTIC_ISSUE_TIME``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

#: Issue time for values computable arbitrarily far ahead (astronomy, harmonic tide predictions).
DETERMINISTIC_ISSUE_TIME = datetime(1970, 1, 1, tzinfo=UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` converted to UTC; raise if it is naive."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"naive datetime not allowed (got {dt!r}); attach a timezone")
    return dt.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Precision(StrEnum):
    """How precisely a time window is known."""

    INSTANT = "instant"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class Granularity(StrEnum):
    """Bins used when coarsening time (e.g., by the policy layer)."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class TimeWindow(BaseModel):
    """Half-open UTC interval ``[start, end)``. An instant has ``start == end``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime
    end: datetime
    precision: Precision = Precision.INSTANT

    @field_validator("start", "end")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)

    @model_validator(mode="after")
    def _ordered(self) -> TimeWindow:
        if self.end < self.start:
            raise ValueError("time window end is before start")
        return self

    @classmethod
    def instant(cls, dt: datetime, precision: Precision = Precision.INSTANT) -> TimeWindow:
        dt = ensure_utc(dt)
        return cls(start=dt, end=dt, precision=precision)

    @classmethod
    def local_day(cls, d: date, utc_offset_hours: float = 0.0) -> TimeWindow:
        """The 24 h window of calendar day ``d`` in a zone with the given UTC offset."""
        start = datetime.combine(d, time(0), tzinfo=UTC) - timedelta(hours=utc_offset_hours)
        return cls(start=start, end=start + timedelta(days=1), precision=Precision.DAY)

    @property
    def is_instant(self) -> bool:
        return self.start == self.end

    @property
    def midpoint(self) -> datetime:
        return self.start + (self.end - self.start) / 2

    def contains(self, dt: datetime) -> bool:
        dt = ensure_utc(dt)
        if self.is_instant:
            return dt == self.start
        return self.start <= dt < self.end

    def overlaps(self, other: TimeWindow) -> bool:
        if self.is_instant:
            return other.contains(self.start) or (other.is_instant and other.start == self.start)
        if other.is_instant:
            return self.contains(other.start)
        return self.start < other.end and other.start < self.end


_GRANULARITY_PRECISION = {
    Granularity.HOUR: Precision.HOUR,
    Granularity.DAY: Precision.DAY,
    Granularity.WEEK: Precision.WEEK,
    Granularity.MONTH: Precision.MONTH,
}


def floor_time(dt: datetime, granularity: Granularity) -> datetime:
    """Floor a UTC datetime to the start of its hour/day/ISO week (Monday)/month."""
    dt = ensure_utc(dt)
    if granularity is Granularity.HOUR:
        return dt.replace(minute=0, second=0, microsecond=0)
    day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity is Granularity.DAY:
        return day
    if granularity is Granularity.WEEK:
        return day - timedelta(days=day.weekday())
    if granularity is Granularity.MONTH:
        return day.replace(day=1)
    raise ValueError(f"unknown granularity {granularity!r}")


def add_granularity(dt: datetime, granularity: Granularity) -> datetime:
    """Advance ``dt`` by one bin of the given granularity."""
    if granularity is Granularity.HOUR:
        return dt + timedelta(hours=1)
    if granularity is Granularity.DAY:
        return dt + timedelta(days=1)
    if granularity is Granularity.WEEK:
        return dt + timedelta(weeks=1)
    if granularity is Granularity.MONTH:
        if dt.month == 12:
            return dt.replace(year=dt.year + 1, month=1)
        return dt.replace(month=dt.month + 1)
    raise ValueError(f"unknown granularity {granularity!r}")


_PRECISION_ORDER = list(Precision)


def coarsen_window(window: TimeWindow, granularity: Granularity) -> TimeWindow:
    """Smallest window aligned to ``granularity`` bins that contains ``window``.

    Windows whose precision is already at least as coarse as ``granularity`` are returned as-is.
    """
    target = _GRANULARITY_PRECISION[granularity]
    if _PRECISION_ORDER.index(window.precision) >= _PRECISION_ORDER.index(target):
        return window
    start = floor_time(window.start, granularity)
    end_floor = floor_time(window.end, granularity)
    if window.is_instant or end_floor != window.end:
        end = add_granularity(end_floor, granularity)
    else:
        end = end_floor
    if end <= start:
        end = add_granularity(start, granularity)
    return TimeWindow(start=start, end=end, precision=_GRANULARITY_PRECISION[granularity])


def parse_mmdd(value: str) -> tuple[int, int]:
    """Parse ``"MM-DD"`` into ``(month, day)``, validating against a leap year."""
    month_s, day_s = value.split("-")
    month, day = int(month_s), int(day_s)
    date(2000, month, day)  # raises ValueError if invalid
    return month, day


def in_seasonal_window(d: date, start_mmdd: str, end_mmdd: str) -> bool:
    """Whether ``d`` falls within an inclusive ``MM-DD`` range; ranges may wrap the new year."""
    start = parse_mmdd(start_mmdd)
    end = parse_mmdd(end_mmdd)
    key = (d.month, d.day)
    if start <= end:
        return start <= key <= end
    return key >= start or key <= end
