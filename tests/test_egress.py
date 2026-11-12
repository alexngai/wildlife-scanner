from datetime import UTC, datetime, timedelta

import h3
import pytest

from wildlife_radar.core import (
    CellsFootprint,
    Observation,
    Outcome,
    Prediction,
    SensitivityFlags,
    TaxonRef,
    TaxonScheme,
    TimeWindow,
    parse_license,
)
from wildlife_radar.core.spatial import cell_for_point
from wildlife_radar.core.time import Precision
from wildlife_radar.models import NOWCAST, logit, sigmoid
from wildlife_radar.policy import EgressFilter, PolicyTier, allowed_in_place_first_special

NOW = datetime(2026, 11, 11, tzinfo=UTC)
TIERS = {
    "open-sp": PolicyTier.OPEN,
    "gen-sp": PolicyTier.GENERALIZED,
    "coarse-sp": PolicyTier.COARSE,
    "withheld-sp": PolicyTier.WITHHELD,
}


@pytest.fixture
def egress():
    return EgressFilter(lambda t: TIERS.get(t, PolicyTier.COARSE))


def make_obs(taxon_id, age=timedelta(days=40), uncertainty=None, **flags):
    return Observation(
        obs_id="src:42",
        source_id="src",
        source_record_id="42",
        source_url="https://example.org/obs/42",
        taxon=TaxonRef(scheme=TaxonScheme.NAME, id="x"),
        taxon_id=taxon_id,
        footprint={"kind": "point", "lat": 32.8505, "lon": -117.272, "uncertainty_m": uncertainty},
        time=TimeWindow.instant(NOW - age),
        outcome=Outcome.PRESENCE_ONLY,
        license=parse_license("cc-by"),
        sensitivity=SensitivityFlags(**flags),
        extras={"note": "raw"},
    )


def only_cell(obs):
    assert isinstance(obs.footprint, CellsFootprint)
    (cell,) = obs.footprint.cells
    return cell


def test_open_tier_keeps_links_and_uses_local_resolution(egress):
    (out,), report = egress.filter_observations([make_obs("open-sp", timedelta(days=3))], NOW)
    assert h3.get_resolution(only_cell(out)) == 7
    assert out.time.precision is Precision.HOUR
    assert out.source_url is not None
    assert out.extras == {}
    assert report.kept == 1


def test_recent_open_sightings_are_delayed(egress):
    out, report = egress.filter_observations([make_obs("open-sp", timedelta(hours=2))], NOW)
    assert out == [] and report.dropped["too_recent"] == 1


def test_generalized_tier_coarsens_and_redacts(egress):
    (out,), _ = egress.filter_observations([make_obs("gen-sp", timedelta(days=10))], NOW)
    assert h3.get_resolution(only_cell(out)) == 5
    assert out.time.precision is Precision.WEEK
    assert out.source_url is None and out.source_record_id is None
    assert out.obs_id.startswith("redacted:") and "42" not in out.obs_id
    assert out.sensitivity.obscured


def test_coarse_and_unresolved_taxa(egress):
    (out,), _ = egress.filter_observations([make_obs("coarse-sp")], NOW)
    assert h3.get_resolution(only_cell(out)) == 3
    assert out.time.precision is Precision.MONTH
    (unknown,), _ = egress.filter_observations([make_obs(None)], NOW)
    assert h3.get_resolution(only_cell(unknown)) == 3


def test_coarse_tier_waits_a_month(egress):
    out, report = egress.filter_observations([make_obs("coarse-sp", timedelta(days=20))], NOW)
    assert out == [] and report.dropped["too_recent"] == 1


def test_obscured_upstream_records_are_never_refined(egress):
    (out,), _ = egress.filter_observations(
        [make_obs("open-sp", timedelta(days=3), uncertainty=29_000, obscured=True)], NOW
    )
    assert h3.get_resolution(only_cell(out)) <= 3


@pytest.mark.parametrize(
    ("taxon", "flags", "reason"),
    [
        ("withheld-sp", {}, "tier_withheld"),
        ("open-sp", {"contexts": frozenset({"den"})}, "sensitive_context"),
        ("open-sp", {"individual_id": "P-22"}, "named_or_collared_individual"),
        ("open-sp", {"embargoed_until": NOW + timedelta(days=1)}, "embargoed"),
        ("open-sp", {"geoprivacy": "private"}, "private_geoprivacy"),
    ],
)
def test_always_dropped(egress, taxon, flags, reason):
    out, report = egress.filter_observations([make_obs(taxon, **flags)], NOW)
    assert out == [] and report.dropped[reason] == 1


def pred(taxon_id, cell, p=0.3, nowcast=1.0, place_id=None):
    contributions = {"prior": logit(p), "sst": 0.2, NOWCAST: nowcast}
    return Prediction(
        taxon_id=taxon_id,
        cell=cell,
        place_id=place_id,
        time=TimeWindow.instant(datetime(2026, 11, 12, 18, tzinfo=UTC)),
        method_id="scuba_dive",
        as_of=NOW,
        p=sigmoid(sum(contributions.values())),
        contributions=contributions,
        maturity_level=2,
    )


def test_predictions_for_generalized_tier_drop_nowcast_and_aggregate(egress):
    parent = cell_for_point(32.85, -117.27, 5)
    a, b = sorted(h3.cell_to_children(parent, 9))[:2]
    out, report = egress.filter_predictions([pred("gen-sp", a), pred("gen-sp", b, nowcast=3.0)])
    assert report.kept == 1
    (agg,) = out
    assert agg.cell == parent
    assert NOWCAST not in agg.contributions
    assert agg.p == pytest.approx(sigmoid(logit(0.3) + 0.2))
    assert agg.policy_tier_applied == int(PolicyTier.GENERALIZED)
    assert agg.time.precision is Precision.WEEK


def test_open_predictions_keep_nowcast(egress):
    cell9 = cell_for_point(32.85, -117.27, 9)
    (out,), _ = egress.filter_predictions([pred("open-sp", cell9)])
    assert h3.get_resolution(out.cell) == 7
    assert NOWCAST in out.contributions


def test_prediction_drops(egress):
    cell = cell_for_point(32.85, -117.27, 7)
    out, report = egress.filter_predictions(
        [
            pred("withheld-sp", cell),
            pred("gen-sp", None, place_id="la-jolla-cove"),
            pred("open-sp", None, place_id="la-jolla-cove"),
        ]
    )
    assert [p.taxon_id for p in out] == ["open-sp"]
    assert report.dropped == {"tier_withheld": 1, "place_only_prediction_for_sensitive_tier": 1}


def test_place_first_special_lists():
    assert allowed_in_place_first_special(PolicyTier.GENERALIZED)
    assert not allowed_in_place_first_special(PolicyTier.COARSE)
