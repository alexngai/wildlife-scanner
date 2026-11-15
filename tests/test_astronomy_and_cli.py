from datetime import UTC, date, datetime

import pytest

from wildlife_scanner.cli import main
from wildlife_scanner.connectors.astronomy import (
    astro_state,
    astronomy_signals,
    daily_events,
    hours_since_sunset,
)
from wildlife_scanner.core.time import DETERMINISTIC_ISSUE_TIME

LA_JOLLA = (32.8505, -117.272)


def test_moon_phases():
    full = astro_state(*LA_JOLLA, datetime(2025, 1, 13, 22, 27, tzinfo=UTC))
    new = astro_state(*LA_JOLLA, datetime(2025, 1, 29, 12, 36, tzinfo=UTC))
    assert full.moon_illumination > 0.99
    assert full.moon_phase_angle_deg == pytest.approx(180, abs=1)
    assert new.moon_illumination < 0.01


def test_solstice_sun_events_at_la_jolla():
    ev = daily_events(*LA_JOLLA, date(2026, 6, 21), utc_offset_hours=-7)
    assert (
        datetime(2026, 6, 22, 2, 50, tzinfo=UTC)
        < ev.sunset
        < datetime(2026, 6, 22, 3, 10, tzinfo=UTC)
    )
    assert (
        datetime(2026, 6, 21, 12, 30, tzinfo=UTC)
        < ev.sunrise
        < datetime(2026, 6, 21, 12, 50, tzinfo=UTC)
    )
    assert ev.civil_dawn < ev.sunrise and ev.civil_dusk > ev.sunset


def test_hours_since_sunset():
    h = hours_since_sunset(*LA_JOLLA, datetime(2026, 6, 22, 4, 0, tzinfo=UTC))
    assert h == pytest.approx(1.0, abs=0.05)


def test_astronomy_signals():
    t = datetime(2026, 6, 22, 4, 0, tzinfo=UTC)
    values = astronomy_signals(*LA_JOLLA, [t], "point:la-jolla")
    assert {v.signal_id for v in values} == {
        "astro.sun_altitude_deg",
        "astro.moon_altitude_deg",
        "astro.moon_illumination",
        "astro.moon_phase_angle_deg",
        "astro.hours_since_sunset",
    }
    assert all(v.issue_time == DETERMINISTIC_ISSUE_TIME for v in values)


def test_cli_offline_commands(capsys):
    assert main(["astro", "--lat", "32.85", "--lon", "-117.27", "--date", "2026-11-15"]) == 0
    assert "sunset" in capsys.readouterr().out
    assert main(["profiles", "list"]) == 0
    assert "puma-concolor" in capsys.readouterr().out
    rc = main(
        ["profiles", "tier", "atractoscion-nobilis", "--region", "socal", "--date", "2026-05-01"]
    )
    assert rc == 0 and "GENERALIZED" in capsys.readouterr().out
    assert main(["profiles", "show", "canis-lupus"]) == 0
    assert "sign_survey" in capsys.readouterr().out
    assert main(["sources"]) == 0
    assert "noaa-coops" in capsys.readouterr().out
    assert main(["profiles", "show", "no-such-profile"]) == 1
