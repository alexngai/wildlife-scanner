from datetime import UTC, datetime

import pytest

from wildlife_radar.evaluation import (
    Climatology,
    Event,
    Persistence,
    brier_score,
    brier_skill_score,
    forward_chaining_folds,
    log_loss,
    reliability_table,
)
from wildlife_radar.models import NOWCAST, anomaly, combine, lift, logit, recompute_p, sigmoid


def test_logit_sigmoid_roundtrip():
    for p in (0.01, 0.2, 0.5, 0.97):
        assert sigmoid(logit(p)) == pytest.approx(p)
    assert sigmoid(-1000) == pytest.approx(0.0)


def test_combine_and_explain():
    r = combine(0.2, {"sst": 0.5, NOWCAST: 1.0, "moon": -0.1})
    assert r.p == pytest.approx(sigmoid(logit(0.2) + 1.4))
    assert [k for k, _ in r.top_drivers()] == [NOWCAST, "sst", "moon"]
    assert r.without([NOWCAST]).p == pytest.approx(sigmoid(logit(0.2) + 0.4))
    assert recompute_p(r.contributions, drop=[NOWCAST]) == pytest.approx(r.without([NOWCAST]).p)
    with pytest.raises(ValueError):
        combine(0.2, {"prior": 1.0})


def test_lift_and_anomaly():
    assert lift(0.3, 0.1) == pytest.approx(3.0)
    assert anomaly(0.05, 0.2) == pytest.approx(0.25)


def test_scores():
    y = [1, 0, 1, 0]
    assert brier_score(y, [1, 0, 1, 0]) == 0
    assert brier_score(y, [0.5] * 4) == pytest.approx(0.25)
    assert log_loss([1], [0.5]) == pytest.approx(0.6931, abs=1e-4)
    assert brier_skill_score(y, [0.9, 0.1, 0.8, 0.2], [0.5] * 4) > 0
    assert brier_skill_score(y, [0.1, 0.9, 0.2, 0.8], [0.5] * 4) < 0
    with pytest.raises(ValueError):
        brier_score([1, 2], [0.1, 0.2])


def test_reliability_table():
    bins = reliability_table([0, 0, 1, 1], [0.05, 0.15, 0.85, 1.0], bins=10)
    assert [(b.lo, b.n) for b in bins] == [(0.0, 1), (0.1, 1), (0.8, 1), (0.9, 1)]
    assert bins[-1].observed_rate == 1.0


def test_forward_chaining_folds():
    times = [datetime(2020 + i, 6, 1, tzinfo=UTC) for i in range(5)]
    bounds = [datetime(y, 1, 1, tzinfo=UTC) for y in (2022, 2023, 2025)]
    folds = forward_chaining_folds(times, bounds)
    assert [f.train_idx for f in folds] == [(0, 1), (0, 1, 2)]
    assert [f.test_idx for f in folds] == [(2,), (3, 4)]
    with pytest.raises(ValueError):
        forward_chaining_folds(times, [bounds[1], bounds[0]])


def test_baselines():
    events = [
        Event(key="cove", period=1, detected=True),
        Event(key="cove", period=1, detected=True),
        Event(key="shores", period=1, detected=False),
        Event(key="shores", period=2, detected=False),
    ]
    clim = Climatology(strength=2).fit(events)
    assert clim.base == pytest.approx(0.5)
    assert clim.predict("cove") == pytest.approx((2 + 2 * 0.5) / (2 + 2))
    assert clim.predict("never-seen") == pytest.approx(0.5)
    pers = Persistence(default=0.1).fit(events)
    assert pers.predict("cove", 2) == 1.0
    assert pers.predict("cove", 1) == 0.1


def test_distinctiveness_prefers_likely_and_distinctive():
    from wildlife_radar.serving.queries import distinctiveness

    rare_fluke = distinctiveness(0.012, 80.0)  # rarely recorded, huge ratio
    local_specialty = distinctiveness(0.21, 50.0)  # e.g. pygmy nuthatch in the pines
    common_everywhere = distinctiveness(0.6, 1.1)
    assert local_specialty > max(rare_fluke, common_everywhere) > 0
    assert distinctiveness(0.5, 0.8) == 0.0 and distinctiveness(0.5, None) == 0.0
