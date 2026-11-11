from datetime import UTC, datetime

import pytest

from wildlife_radar.core import (
    STANDARD_METHODS,
    Effort,
    Observation,
    Outcome,
    Prediction,
    SignalValue,
    TaxonRef,
    TaxonScheme,
    TimeWindow,
    parse_license,
)
from wildlife_radar.core.geometry import PointFootprint
from wildlife_radar.core.spatial import cell_for_point
from wildlife_radar.core.taxa import slugify_name

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def obs(**kw):
    base = dict(
        obs_id="x:1",
        source_id="x",
        taxon=TaxonRef(scheme=TaxonScheme.NAME, id="Puma concolor"),
        footprint={"kind": "point", "lat": 34.1, "lon": -118.6},
        time=TimeWindow.instant(T0),
        outcome=Outcome.PRESENCE_ONLY,
        license=parse_license("cc-by"),
    )
    base.update(kw)
    return Observation(**base)


def test_observation_footprint_discriminator_and_detection():
    o = obs()
    assert isinstance(o.footprint, PointFootprint)
    assert o.is_detection
    assert not obs(outcome=Outcome.NOT_DETECTED).is_detection
    assert not obs(outcome=Outcome.COUNT, count=0).is_detection


def test_count_outcome_requires_count():
    with pytest.raises(ValueError):
        obs(outcome=Outcome.COUNT)


def test_observation_is_immutable():
    o = obs()
    with pytest.raises(ValueError):
        o.taxon_id = "puma-concolor"


def test_prediction_validation():
    cell = cell_for_point(34.1, -118.6, 7)
    p = Prediction(
        taxon_id="puma-concolor",
        cell=cell,
        time=TimeWindow.instant(T0),
        method_id="sign_survey",
        as_of=T0,
        p=0.1,
        interval=(0.05, 0.2),
    )
    assert p.cell == cell
    with pytest.raises(ValueError):
        Prediction(taxon_id="x", time=p.time, method_id="m", as_of=T0, p=0.1)  # no cell/place
    with pytest.raises(ValueError):
        p.model_copy(update={}).model_validate({**p.model_dump(), "cell": "bogus"})
    with pytest.raises(ValueError):
        Prediction(**{**p.model_dump(), "interval": (0.3, 0.2)})


def test_signal_value_requires_aware_times():
    with pytest.raises(ValueError):
        SignalValue(
            signal_id="s",
            location_key="k",
            valid_time=datetime(2026, 1, 1),
            issue_time=T0,
            value=1.0,
        )


def test_effort_and_methods():
    assert Effort().is_empty()
    assert not Effort(duration_min=60).is_empty()
    assert {"scuba_dive", "sign_survey", "camera_trap", "birding_checklist"} <= set(
        STANDARD_METHODS
    )


def test_slugify():
    assert slugify_name("Puma concolor") == "puma-concolor"
    assert slugify_name(" Canis lupus  baileyi ") == "canis-lupus-baileyi"
