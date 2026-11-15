from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from wildlife_scanner.core.time import (
    Granularity,
    Precision,
    TimeWindow,
    coarsen_window,
    ensure_utc,
    floor_time,
    in_seasonal_window,
)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        TimeWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2))


def test_window_normalizes_to_utc():
    pst = timezone(timedelta(hours=-8))
    w = TimeWindow.instant(datetime(2026, 1, 1, 8, tzinfo=pst))
    assert w.start == utc(2026, 1, 1, 16)
    assert w.is_instant


def test_window_end_before_start_is_rejected():
    with pytest.raises(ValueError):
        TimeWindow(start=utc(2026, 1, 2), end=utc(2026, 1, 1))


def test_local_day_uses_offset():
    w = TimeWindow.local_day(date(2026, 5, 1), -8)
    assert w.start == utc(2026, 5, 1, 8)
    assert w.end == utc(2026, 5, 2, 8)
    assert w.precision is Precision.DAY


def test_contains_and_overlaps():
    w = TimeWindow(start=utc(2026, 1, 1), end=utc(2026, 1, 2))
    assert w.contains(utc(2026, 1, 1, 12))
    assert not w.contains(utc(2026, 1, 2))  # half-open
    assert w.overlaps(TimeWindow.instant(utc(2026, 1, 1, 23)))
    assert not w.overlaps(TimeWindow(start=utc(2026, 1, 2), end=utc(2026, 1, 3)))


def test_floor_time():
    dt = utc(2026, 11, 11, 15, 30)  # a Wednesday
    assert floor_time(dt, Granularity.HOUR) == utc(2026, 11, 11, 15)
    assert floor_time(dt, Granularity.DAY) == utc(2026, 11, 11)
    assert floor_time(dt, Granularity.WEEK) == utc(2026, 11, 9)
    assert floor_time(dt, Granularity.MONTH) == utc(2026, 11, 1)


def test_coarsen_instant_to_week():
    w = coarsen_window(TimeWindow.instant(utc(2026, 11, 11, 15, 30)), Granularity.WEEK)
    assert (w.start, w.end) == (utc(2026, 11, 9), utc(2026, 11, 16))
    assert w.precision is Precision.WEEK


def test_coarsen_keeps_aligned_end():
    w = TimeWindow(start=utc(2026, 11, 9), end=utc(2026, 11, 16))
    assert coarsen_window(w, Granularity.WEEK) == TimeWindow(
        start=utc(2026, 11, 9), end=utc(2026, 11, 16), precision=Precision.WEEK
    )


def test_coarsen_month_rolls_over_year():
    w = coarsen_window(TimeWindow.instant(utc(2026, 12, 15)), Granularity.MONTH)
    assert (w.start, w.end) == (utc(2026, 12, 1), utc(2027, 1, 1))


def test_seasonal_windows():
    assert in_seasonal_window(date(2026, 6, 15), "03-15", "06-15")
    assert not in_seasonal_window(date(2026, 6, 16), "03-15", "06-15")
    # wrapping the new year
    assert in_seasonal_window(date(2026, 1, 5), "11-01", "02-28")
    assert not in_seasonal_window(date(2026, 6, 1), "11-01", "02-28")
    with pytest.raises(ValueError):
        in_seasonal_window(date(2026, 1, 1), "02-30", "03-01")
