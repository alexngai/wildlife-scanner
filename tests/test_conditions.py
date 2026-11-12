import math
import random
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from wildlife_radar.conditions import terms_from_profile
from wildlife_radar.conditions.daily import (
    CoopsDailyFetcher,
    ensure_schema,
    moon_on,
    normals,
    store_rows,
)
from wildlife_radar.conditions.levels import run_conditions
from wildlife_radar.conditions.model import OffsetLogit, TermSpec, block_bootstrap
from wildlife_radar.core.geometry import PointFootprint
from wildlife_radar.core.ids import hash_identifier
from wildlife_radar.core.licenses import CC_BY
from wildlife_radar.core.observations import EvidenceGrade, Modality, Observation, Outcome
from wildlife_radar.core.taxa import TaxonRef, TaxonScheme
from wildlife_radar.core.time import Precision, TimeWindow
from wildlife_radar.profiles import ProfileLibrary
from wildlife_radar.storage import ObservationStore

SITE = (32.85, -117.27)
BBOX = (-117.4, 32.7, -117.1, 33.0)
START, END = date(2016, 1, 1), date(2025, 12, 31)
SPLIT = datetime(2023, 1, 1, tzinfo=UTC)


def sst_series(rng: random.Random) -> dict[date, tuple[float, float]]:
    """Daily ``(sst, anomaly)``: a seasonal cycle plus a persistent (AR-1) anomaly."""
    out, anomaly, d = {}, 0.0, START
    while d <= END:
        anomaly = 0.9 * anomaly + rng.gauss(0, 0.6)
        seasonal = 17 + 3 * math.sin(2 * math.pi * (d.timetuple().tm_yday - 120) / 365)
        out[d] = (seasonal + anomaly, anomaly)
        d += timedelta(days=1)
    return out


def observation(n: int, name: str, observer: str, day: date, lat: float, lon: float):
    when = datetime(day.year, day.month, day.day, 18, tzinfo=UTC)
    return Observation(
        obs_id=f"cond:{n}",
        source_id="cond-test",
        source_record_id=str(n),
        taxon=TaxonRef(scheme=TaxonScheme.NAME, id=name, name=name, rank="species"),
        footprint=PointFootprint(lat=lat, lon=lon, uncertainty_m=20),
        time=TimeWindow.instant(when, Precision.MINUTE),
        modality=Modality.SEE,
        outcome=Outcome.PRESENCE_ONLY,
        evidence_grade=EvidenceGrade.C1,
        license=CC_BY,
        extras={"group": "fishes", "observer_hash": observer},
    )


@pytest.fixture(scope="module")
def world():
    rng = random.Random(3)
    sst = sst_series(rng)
    days = sorted(sst)
    # Pulses: a visitor present only during random 10-day events.
    events = set()
    for _ in range(40):
        start = rng.choice(days)
        events |= {start + timedelta(days=k) for k in range(10)}
    records, n = [], 0
    for _ in range(9000):
        day = rng.choice(days)
        observer = hash_identifier(f"diver-{rng.randrange(150)}")
        lat = SITE[0] + rng.gauss(0, 0.01)
        lon = SITE[1] + rng.gauss(0, 0.01)
        anomaly = sst[day][1]
        p = {
            "Piscis communis": 0.9,  # recorded on almost every outing (effort)
            "Piscis calida": 1 / (1 + math.exp(-(-1.6 + 1.1 * anomaly))),
            "Piscis indifferens": 0.25,
            "Piscis pulsans": 0.6 if day in events else 0.02,
        }
        for name, prob in p.items():
            if rng.random() < prob:
                n += 1
                records.append(observation(n, name, observer, day, lat, lon))
    store = ObservationStore()
    store.add(records)
    store_rows(store.conn, [("TEST1", "ocean.sst_c", d, v[0]) for d, v in sst.items()])
    return store


def test_offset_logit_recovers_an_effect():
    rng = np.random.default_rng(0)
    x = rng.normal(size=20000)
    offset = np.full(20000, -1.0)
    y = (rng.random(20000) < 1 / (1 + np.exp(-(-1.0 + 0.8 * x)))).astype(float)
    model = OffsetLogit([TermSpec("x", "x", "linear", "strong")]).fit({"x": x}, y, offset)
    assert model.converged
    curve = model.effect_curve("x", [0.0, 1.0])
    assert 0.65 < curve[1][1] - curve[0][1] < 0.95  # slope ≈ 0.8 per unit
    contributions = model.contributions({"x": np.array([1.0])})
    assert contributions["x"][0] > 0
    lo, hi = block_bootstrap(np.arange(100) % 10, lambda idx: float(np.mean(idx)), reps=50)
    assert lo < hi


def test_normals_use_days_before_cutoff(world):
    conn = world.conn
    clim = normals(conn, "ocean.sst_c", before=date(2020, 1, 1))
    assert ("TEST1", 200) in clim
    # Summer normal is warmer than winter normal.
    assert clim[("TEST1", 200)] > clim[("TEST1", 20)]


def test_levels_and_scorecard(world):
    conn = world.conn
    sst_anomaly = TermSpec("sst_anomaly", "ocean.sst_anomaly_c", "linear", "moderate", True)
    reports = run_conditions(
        conn,
        region_id="cond",
        bbox=BBOX,
        split=SPLIT,
        end=None,
        specs={
            "piscis-calida": [sst_anomaly],
            "piscis-indifferens": [sst_anomaly],
            "piscis-pulsans": [sst_anomaly],
        },
        station_coords={"TEST1": SITE},
        reps=100,
    )
    by_taxon = {r.taxon_id: r for r in reports}
    warm = by_taxon["piscis-calida"]
    assert warm.levels[0].passes, warm  # conditions beat Level 0
    assert warm.scorecard[0].verdict == "supported"
    assert warm.scorecard[0].direction_fitted == "+"
    flat = by_taxon["piscis-indifferens"]
    assert not flat.levels[0].passes
    assert flat.scorecard[0].verdict != "supported"
    pulses = by_taxon["piscis-pulsans"]
    assert pulses.levels[1].passes, pulses  # the nowcast captures the events
    gates = conn.execute(
        "SELECT taxon_id, level, passes FROM conditions_gates WHERE region_id = 'cond' "
        "ORDER BY 1, 2"
    ).fetchall()
    assert ("piscis-calida", 1, True) in gates
    assert conn.execute("SELECT count(*) FROM hypothesis_scorecard").fetchone()[0] == 3
    assert conn.execute("SELECT count(*) FROM conditions_models").fetchone()[0] >= 6


def test_profile_terms_map_daily_signals():
    lib = ProfileLibrary()
    terms, notes = terms_from_profile(lib.resolve("atractoscion-nobilis"))
    signals = {t.signal for t in terms}
    assert "ocean.sst_c" in signals and "astro.moon_illumination" in signals
    assert any("market_squid" in n for n in notes)  # no data source yet
    assert any("hours_since_sunset" in n for n in notes)  # needs timed records


def test_moon_and_coops_parsing():
    import httpx

    from wildlife_radar.connectors.base import RateLimiter, make_client

    full = moon_on(date(2026, 11, 24))  # full moon 2026-11-24
    new = moon_on(date(2026, 11, 9))  # new moon 2026-11-09
    assert full[0] > 0.95 and new[0] < 0.05

    def api(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params["product"] == "predictions":
            return httpx.Response(
                200,
                json={
                    "predictions": [
                        {"t": "2026-06-01 10:00", "v": "-0.3", "type": "L"},
                        {"t": "2026-06-01 16:00", "v": "1.5", "type": "H"},
                        {"t": "2026-06-01 22:00", "v": "0.4", "type": "L"},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"data": [{"t": f"2026-06-01 {h:02d}:00", "v": "18.0"} for h in range(8, 24)]},
        )

    fetcher = CoopsDailyFetcher(
        client=make_client(transport=httpx.MockTransport(api)), limiter=RateLimiter(0)
    )
    tides = fetcher.tides("X", -117.27, date(2026, 6, 1), date(2026, 6, 1))
    assert ("X", "tide.daily_low_m", date(2026, 6, 1), -0.3) in tides
    assert ("X", "tide.daily_range_m", date(2026, 6, 1), 1.8) in tides
    temps = fetcher.observations(
        "X", -117.27, "water_temperature", date(2026, 6, 1), date(2026, 6, 1)
    )
    assert temps == [("X", "ocean.sst_c", date(2026, 6, 1), 18.0)]
    conn = ObservationStore().conn
    ensure_schema(conn)
    assert store_rows(conn, temps) == 1


def test_forecast_uses_gated_levels_and_explains(world):
    from wildlife_radar.policy.statuses import StaticStatusProvider, TierService, build_tier_table
    from wildlife_radar.regions import Region
    from wildlife_radar.serving import BaselineQueries
    from wildlife_radar.serving.forecast import ForecastService

    conn = world.conn
    sst_anomaly = TermSpec("sst_anomaly", "ocean.sst_anomaly_c", "linear", "moderate", True)
    run_conditions(
        conn,
        region_id="cond",
        bbox=BBOX,
        split=SPLIT,
        end=None,
        specs={"piscis-calida": [sst_anomaly], "piscis-indifferens": [sst_anomaly]},
        station_coords={"TEST1": SITE},
        reps=50,
    )
    from wildlife_radar.baseline import build_baseline

    build_baseline(conn, region_id="cond", bbox=BBOX)
    build_tier_table(conn, region_id="cond", scopes=["global"], providers=[StaticStatusProvider()])
    region = Region(id="cond", name="test", bbox=BBOX)
    queries = BaselineQueries(conn, region, TierService(conn, "cond"))
    service = ForecastService(queries, {"TEST1": SITE})
    sst = dict(
        conn.execute(
            "SELECT day, value FROM signal_daily WHERE signal_id = 'ocean.sst_c'"
        ).fetchall()
    )
    # A warm-anomaly summer day vs a cool one in the same week of a year.
    days = [date(2024, 7, d) for d in range(1, 29)]
    warm = max(days, key=lambda d: sst[d])
    cool = min(days, key=lambda d: sst[d])
    hot = service.forecast("piscis-calida", *SITE, warm)
    cold = service.forecast("piscis-calida", *SITE, cool)
    assert hot.level >= 1 and hot.drivers[0].term == "sst_anomaly"
    assert hot.drivers[0].contribution > 0 > cold.drivers[0].contribution
    assert hot.p > hot.p_level0 and cold.p < cold.p_level0
    # No model passed its gate: Level 0, labeled.
    flat = service.forecast("piscis-indifferens", *SITE, warm)
    assert flat.level == 0 and flat.p == flat.p_level0
    assert any("gate" in n for n in flat.notes)


def test_nowcast_for_open_taxa_without_profiles(world):
    from wildlife_radar.baseline import build_baseline
    from wildlife_radar.conditions.nowcast import run_nowcasts
    from wildlife_radar.policy.statuses import StaticStatusProvider, build_tier_table

    conn = world.conn
    build_baseline(conn, region_id="now", bbox=BBOX)
    build_tier_table(conn, region_id="now", scopes=["global"], providers=[StaticStatusProvider()])
    summary = run_nowcasts(
        conn,
        region_id="now",
        bbox=BBOX,
        split=SPLIT,
        exclude={"piscis-calida"},
        min_detections=50,
        pool=4000,
        reps=50,
    )
    assert summary.fitted >= 2
    gates = {
        t: passes
        for t, passes in conn.execute(
            "SELECT taxon_id, passes FROM conditions_gates WHERE region_id = 'now' AND level = 2"
        ).fetchall()
    }
    assert gates["piscis-pulsans"] is True  # pulses: recent sightings predict the next days
    assert gates["piscis-indifferens"] is False  # steady: nothing to gain
    assert "piscis-calida" not in gates  # profiled taxa are handled by run_conditions
    assert [b[0] for b in summary.best][:1] == ["piscis-pulsans"]


def test_recent_activity_from_a_bundle(world, tmp_path):
    import duckdb

    from wildlife_radar.pipeline.publish import publish_bundle
    from wildlife_radar.policy.statuses import TierService
    from wildlife_radar.regions import Region
    from wildlife_radar.serving import BaselineQueries
    from wildlife_radar.serving.forecast import ForecastService, recent_activity

    conn = world.conn  # nowcasts for region "now" were fitted by the previous test
    if not conn.execute("SELECT count(*) FROM conditions_gates WHERE region_id = 'now'").fetchone()[
        0
    ]:
        pytest.skip("needs test_nowcast_for_open_taxa_without_profiles")
    # The busiest day of a pulse in the test period; ask two days later.
    peak = conn.execute(
        "SELECT local_date FROM observations WHERE taxon_id = 'piscis-pulsans' "
        "AND local_date >= '2023-01-01' GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
    ).fetchone()[0]
    on = peak + timedelta(days=2)
    region = Region(id="now", name="test", bbox=BBOX)
    result = publish_bundle(
        conn,
        region,
        tmp_path,
        now=datetime(on.year, on.month, on.day, 12, tzinfo=UTC),
        allow_findings=True,
    )
    bundle = duckdb.connect(str(result.path / "serving.duckdb"), read_only=True)
    queries = BaselineQueries(bundle, region, TierService(bundle, "now"))
    activity = recent_activity(ForecastService(queries, {}), *SITE, on)
    picking = {i.taxon_id: i for i in activity.picking_up}
    reported = {i.taxon_id for i in activity.reported_recently}
    assert "piscis-pulsans" in picking and picking["piscis-pulsans"].odds_boost >= 1.25
    assert picking["piscis-pulsans"].p_now > picking["piscis-pulsans"].p_usual
    assert "piscis-communis" in reported and "piscis-communis" not in picking
    assert activity.data_through < on
