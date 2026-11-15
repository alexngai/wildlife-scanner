from datetime import UTC, datetime, timedelta

import pytest

from wildlife_scanner.core.signals import SignalDefinition, SignalKind, SignalValue
from wildlife_scanner.signals import SignalRegistry, SignalStore, builtin_registry
from wildlife_scanner.signals.derived import interpolate_linear, tide_stage


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def sv(valid, issue, value, sid="ocean.sst_c", key="h3:x", **attrs):
    return SignalValue(
        signal_id=sid,
        location_key=key,
        valid_time=valid,
        issue_time=issue,
        value=value,
        attrs=attrs,
    )


@pytest.fixture
def store():
    s = SignalStore()
    friday = utc(2026, 5, 8, 12)
    s.add(
        [
            sv(friday, utc(2026, 5, 5), 15.0),  # Tuesday forecast
            sv(friday, utc(2026, 5, 7), 16.0),  # Thursday revision
            sv(friday, utc(2026, 5, 8, 13), 16.5),  # observation after the fact
            sv(friday + timedelta(hours=1), utc(2026, 5, 5), 15.2),
        ]
    )
    return s


def test_as_of_returns_latest_known_version(store):
    friday = utc(2026, 5, 8, 12)
    get = lambda as_of: store.value_at("ocean.sst_c", "h3:x", friday, as_of)  # noqa: E731
    assert get(utc(2026, 5, 4)) is None
    assert get(utc(2026, 5, 6)).value == 15.0
    assert get(utc(2026, 5, 7, 1)).value == 16.0
    assert get(utc(2026, 5, 9)).value == 16.5


def test_as_of_range_filter(store):
    vals = store.as_of(
        "ocean.sst_c", "h3:x", utc(2026, 5, 6), start=utc(2026, 5, 8, 12, 30), end=utc(2026, 5, 9)
    )
    assert [v.value for v in vals] == [15.2]


def test_value_at_tolerance(store):
    v = store.value_at(
        "ocean.sst_c", "h3:x", utc(2026, 5, 8, 12, 40), utc(2026, 5, 6), timedelta(hours=1)
    )
    assert v.value == 15.2  # 13:00 is nearer than 12:00
    assert store.value_at("ocean.sst_c", "h3:x", utc(2026, 5, 8, 12, 40), utc(2026, 5, 6)) is None


def test_same_issue_time_replaces(store):
    n = len(store)
    store.add([sv(utc(2026, 5, 8, 12), utc(2026, 5, 5), 99.0)])
    assert len(store) == n
    assert store.value_at("ocean.sst_c", "h3:x", utc(2026, 5, 8, 12), utc(2026, 5, 6)).value == 99


def test_interpolation_and_tide_stage():
    series = [
        sv(utc(2026, 1, 1, h), utc(1970, 1, 1), float(h), sid="tide.height_m") for h in (0, 2)
    ]
    assert interpolate_linear(series, utc(2026, 1, 1, 1)) == pytest.approx(1.0)
    assert interpolate_linear(series, utc(2026, 1, 1, 3)) is None
    extremes = [
        sv(utc(2026, 1, 1, 3), utc(1970, 1, 1), 1.6, sid="tide.extreme_m", type="H"),
        sv(utc(2026, 1, 1, 9), utc(1970, 1, 1), -0.1, sid="tide.extreme_m", type="L"),
    ]
    assert tide_stage(extremes, utc(2026, 1, 1, 5)) == "falling"
    assert tide_stage(extremes, utc(2026, 1, 1, 10)) == "rising"
    assert tide_stage(extremes, utc(2026, 1, 1, 1)) is None


def test_registry():
    reg = builtin_registry()
    assert "tide.stage" in reg and "astro.moon_illumination" in reg
    with pytest.raises(ValueError):
        reg.register(SignalDefinition(signal_id="tide.stage", units="m", description="different"))
    cyclic = SignalRegistry(
        [
            SignalDefinition(
                signal_id="a", units="", description="", kind=SignalKind.DERIVED, depends_on=("b",)
            ),
            SignalDefinition(
                signal_id="b", units="", description="", kind=SignalKind.DERIVED, depends_on=("a",)
            ),
        ]
    )
    with pytest.raises(ValueError, match="cycle"):
        cyclic.check_dependencies()
    with pytest.raises(ValueError, match="unknown"):
        SignalRegistry(
            [SignalDefinition(signal_id="a", units="", description="", depends_on=("zz",))]
        ).check_dependencies()
