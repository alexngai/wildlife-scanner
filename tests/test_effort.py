from datetime import UTC, date, datetime

import h3
import pytest

from wildlife_radar.baseline import (
    DatasetEntry,
    DatasetRegistry,
    backtest_baseline,
    build_baseline,
    estimate,
    label_for,
    method_for,
)
from wildlife_radar.baseline.effort import EBIRD_EOD_DATASET, create_dataset_classes
from wildlife_radar.policy.statuses import StaticStatusProvider, TierService, build_tier_table
from wildlife_radar.regions import load_region
from wildlife_radar.serving import BaselineQueries
from wildlife_radar.storage import ObservationStore
from wildlife_radar.synthetic import DEFAULT_SPECIES, SyntheticSpecies, SyntheticWorld

KELP_FISH = SyntheticSpecies(
    name="Piscis kelpensis",
    group="fishes",
    centers=((32.85, -117.27, 5.0),),
    base=0.7,
    floor=0.05,
    peak_week=30,
    season_sigma_weeks=6,
)
COMMON_FISH = SyntheticSpecies(name="Piscis communis", group="fishes", floor=0.5)
SITES = ((32.85, -117.27), (32.70, -117.26), (33.0, -117.29))
REGISTRY = DatasetRegistry(
    datasets={"synthetic-dive-survey": DatasetEntry(effort_class="dive_survey")}
)


@pytest.fixture(scope="module")
def world_store():
    # The kelp fish is also seen casually by observers (so it has two effort groups).
    casual_fish = SyntheticSpecies(
        name="Piscis kelpensis", group="fishes", centers=((32.85, -117.27, 5.0),), base=0.2
    )
    world = SyntheticWorld(
        species=(*DEFAULT_SPECIES, casual_fish),
        survey_sites=SITES,
        survey_species=(KELP_FISH, COMMON_FISH),
    )
    store = ObservationStore()
    store.add(world.generate())
    report = build_baseline(store.conn, region_id="socal", bbox=world.bbox, registry=REGISTRY)
    return world, store, report


def test_effort_groups_built(world_store):
    _, store, report = world_store
    assert report.survey_trials > 0
    assert set(report.groups) == {"birds:casual", "fishes:casual", "fishes:dive_survey"}
    rows = dict(
        store.conn.execute(
            "SELECT group_id, effort_class FROM prior_taxa WHERE taxon_id = 'piscis-kelpensis'"
        ).fetchall()
    )
    assert rows == {"fishes:casual": "casual", "fishes:dive_survey": "dive_survey"}


def test_survey_effort_is_per_species(world_store):
    _, store, _ = world_store
    shared, per_taxon = store.conn.execute(
        """
        SELECT count(*) FILTER (WHERE taxon_id IS NULL),
               count(*) FILTER (WHERE taxon_id IS NOT NULL)
        FROM prior_effort WHERE group_id = 'fishes:dive_survey'
        """
    ).fetchone()
    assert shared == 0 and per_taxon > 0
    # Annual rate = detections / the species' own trials (common fish detected ~50% of trials).
    rate = store.conn.execute(
        "SELECT annual_rate FROM prior_taxa WHERE taxon_id = 'piscis-communis'"
    ).fetchone()[0]
    assert 0.4 < rate < 0.6


def test_survey_estimates_rank_sites_correctly(world_store):
    _, store, _ = world_store
    est = estimate(
        store.conn,
        "socal",
        "cell",
        5.0,
        taxon_ids=["piscis-kelpensis"],
        groups=["fishes:dive_survey"],
        weeks=[30],
    )
    by_truth = sorted(est, key=lambda e: KELP_FISH.p_true(*h3.cell_to_latlng(e.cell), 30))
    assert by_truth[-1].p == max(e.p for e in est)  # the true hotspot gets the top estimate


def test_backtest_scores_survey_trials(world_store):
    world, store, _ = world_store
    scores = backtest_baseline(
        store.conn,
        region_id="socal",
        bbox=world.bbox,
        split=datetime(2025, 1, 1, tzinfo=UTC),
        registry=REGISTRY,
    )
    survey = {s.taxon_id: s for s in scores if s.group_id == "fishes:dive_survey"}
    # 3 sites × 24 surveys in 2025, one trial per species per survey.
    assert survey["piscis-communis"].n_test == 72
    assert survey["piscis-kelpensis"].bss > 0


def test_method_selects_effort_group(world_store):
    _, store, _ = world_store
    build_tier_table(
        store.conn,
        region_id="socal",
        scopes=["global"],
        providers=[StaticStatusProvider()],
    )
    region = load_region("socal")
    q = BaselineQueries(store.conn, region, TierService(store.conn, "socal"))
    on = date(2026, 7, 20)
    assert q.species_map("piscis-kelpensis", on, method="scuba_dive").effort_group == (
        "fishes:dive_survey"
    )
    assert q.species_map("piscis-kelpensis", on, method="casual").effort_group == "fishes:casual"
    summary = q.taxon_summary("piscis-kelpensis", on)
    assert {g.group_id for g in summary.effort_groups} == {"fishes:casual", "fishes:dive_survey"}
    lists = q.place_lists(32.85, -117.27, on, group="scuba_dive")
    assert [g.group for g in lists.groups] == ["fishes:dive_survey"]
    assert lists.groups[0].method == "scuba_dive"


def test_dataset_classification_and_exclusion():
    store = ObservationStore()
    store.conn.execute(
        """
        INSERT INTO observations (dedupe_key, obs_id, source_id, dataset_key, outcome, modality)
        VALUES ('1', '1', 'gbif', ?, 'presence_only', 'see'),
               ('2', '2', 'gbif', 'surveyish', 'not_detected', 'see'),
               ('3', '3', 'gbif', 'surveyish', 'detected', 'see'),
               ('4', '4', 'gbif', 'machines', 'presence_only', 'sensor'),
               ('5', '5', 'gbif', 'meta-event', 'presence_only', 'see'),
               ('6', '6', 'gbif', 'trawl', 'presence_only', 'see'),
               ('7', '7', 'inaturalist', NULL, 'presence_only', 'see')
        """,
        [EBIRD_EOD_DATASET],
    )
    store.conn.execute(
        "CREATE TABLE dataset_meta (dataset_key VARCHAR PRIMARY KEY, title VARCHAR, "
        "type VARCHAR, license VARCHAR, fetched_at TIMESTAMP)"
    )
    store.conn.execute(
        "INSERT INTO dataset_meta VALUES ('meta-event', 't', 'SAMPLING_EVENT', NULL, NULL)"
    )
    registry = DatasetRegistry(datasets={"trawl": DatasetEntry(exclude=True)})
    create_dataset_classes(store.conn, registry)
    classes = {
        k: (c, x)
        for k, c, x in store.conn.execute(
            "SELECT ds_id, effort_class, excluded FROM _dsclass"
        ).fetchall()
    }
    assert classes[EBIRD_EOD_DATASET] == ("checklist", False)
    assert classes["surveyish"] == ("survey", False)
    assert classes["machines"] == ("sensor", False)
    assert classes["meta-event"] == ("survey", False)
    assert classes["trawl"][1] is True
    assert classes["inaturalist"] == ("casual", False)
    with pytest.raises(ValueError):
        DatasetRegistry(datasets={"x": DatasetEntry(effort_class="snorkel_party")}).check()


def test_labels_and_methods():
    assert method_for("birds:checklist") == "birding_checklist"
    assert method_for("fishes:dive_survey") == "scuba_dive"
    assert method_for("mollusks:intertidal_survey") == "tidepooling"
    assert label_for("fishes:dive_survey") == "fishes · dive surveys"


def test_bundled_registry_is_valid():
    from wildlife_radar.regions import region_dir

    registry = DatasetRegistry.load(region_dir("socal") / "datasets.yaml")
    registry.check()
    assert any(e.effort_class == "dive_survey" for e in registry.datasets.values())
    assert any(e.exclude for e in registry.datasets.values())
