from datetime import UTC, date, datetime

import h3
import pytest

from wildlife_scanner.baseline import (
    DatasetEntry,
    DatasetRegistry,
    backtest_baseline,
    build_baseline,
    estimate,
    label_for,
    method_for,
)
from wildlife_scanner.baseline.effort import EBIRD_EOD_DATASET, create_dataset_classes
from wildlife_scanner.policy.statuses import StaticStatusProvider, TierService, build_tier_table
from wildlife_scanner.regions import load_region
from wildlife_scanner.serving import BaselineQueries
from wildlife_scanner.storage import ObservationStore
from wildlife_scanner.synthetic import DEFAULT_SPECIES, SyntheticSpecies, SyntheticWorld

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
    assert classes["meta-event"] == ("casual", False)  # sampling event without absences
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
    from wildlife_scanner.regions import region_dir

    registry = DatasetRegistry.load(region_dir("california") / "datasets.yaml")
    registry.check()
    assert any(e.effort_class == "dive_survey" for e in registry.datasets.values())
    assert any(e.exclude for e in registry.datasets.values())


def test_backtest_can_score_selected_groups(world_store):
    world, store, _ = world_store
    backtest_baseline(
        store.conn,
        region_id="socal",
        bbox=world.bbox,
        split=datetime(2025, 1, 1, tzinfo=UTC),
        registry=REGISTRY,
    )
    before = store.conn.execute(
        "SELECT count(*) FROM baseline_gates WHERE group_id = 'birds:casual'"
    ).fetchone()[0]
    scores = backtest_baseline(
        store.conn,
        region_id="socal",
        bbox=world.bbox,
        split=datetime(2024, 1, 1, tzinfo=UTC),
        registry=REGISTRY,
        groups=["fishes:dive_survey"],
    )
    assert {s.group_id for s in scores} == {"fishes:dive_survey"}
    after = store.conn.execute(
        "SELECT count(*) FROM baseline_gates WHERE group_id = 'birds:casual'"
    ).fetchone()[0]
    assert before == after > 0


def test_survey_groups_have_flat_seasonality(world_store):
    # Survey campaign dates don't measure seasonality, so survey estimates are flat over weeks.
    _, store, _ = world_store
    est = estimate(
        store.conn,
        "socal",
        "cell",
        5.0,
        taxon_ids=["piscis-kelpensis"],
        groups=["fishes:dive_survey"],
        weeks=[5, 30],
    )
    by_cell: dict[str, set[float]] = {}
    for e in est:
        by_cell.setdefault(e.cell, set()).add(round(e.p, 9))
    assert by_cell and all(len(ps) == 1 for ps in by_cell.values())


def test_placeholder_dates_are_dropped_and_detected():
    from datetime import timedelta

    from wildlife_scanner.baseline.builder import BaselineConfig, create_training_view
    from wildlife_scanner.baseline.effort import date_spikes
    from wildlife_scanner.core.time import Precision, TimeWindow

    world = SyntheticWorld(
        observers=5,
        visits_per_observer=10,
        survey_sites=SITES,
        survey_species=(KELP_FISH, COMMON_FISH),
    )
    records = world.generate()
    # Re-stamp a quarter of the survey records with a "release date".
    stamp = datetime(2024, 11, 30, 8, tzinfo=UTC)
    survey = [r for r in records if r.source_id == "synthetic-survey"]
    restamped = {r.obs_id for r in survey[::4]}
    window = TimeWindow(start=stamp, end=stamp + timedelta(days=1), precision=Precision.DAY)
    records = [
        r.model_copy(update={"time": window}) if r.obs_id in restamped else r for r in records
    ]
    store = ObservationStore()
    store.add(records)
    spikes = date_spikes(store.conn, min_records=10)
    assert [(k, d) for k, d, _, _ in spikes] == [("synthetic-dive-survey", date(2024, 11, 30))]

    def count(registry):
        create_training_view(store.conn, BaselineConfig(), world.bbox, registry)
        return store.conn.execute(
            "SELECT count(*) FROM _obs WHERE effort_class = 'dive_survey'"
        ).fetchone()[0]

    fixed = DatasetRegistry(
        datasets={
            "synthetic-dive-survey": DatasetEntry(
                effort_class="dive_survey", placeholder_dates=[date(2024, 11, 30)]
            )
        }
    )
    assert count(REGISTRY) - count(fixed) == len(restamped)


def test_survey_taxa_without_absences_use_casual_effort(world_store):
    # A program that records absences for fishes but only presences for a snail: the snail's
    # records can't support a detections/trials estimate.
    from wildlife_scanner.baseline.builder import BaselineConfig, create_training_view

    world, store, _ = world_store
    store.conn.execute(
        """
        CREATE TEMP TABLE _snail AS
        SELECT * REPLACE ('snail-' || dedupe_key AS dedupe_key, 'snail-' || obs_id AS obs_id,
                          'megastraea-undosa' AS taxon_id, 'mollusks' AS group_id,
                          'presence_only' AS outcome)
        FROM observations WHERE dataset_key = 'synthetic-dive-survey' AND outcome = 'detected'
        LIMIT 20
        """
    )
    store.conn.execute("INSERT INTO observations SELECT * FROM _snail")
    try:
        create_training_view(store.conn, BaselineConfig(), world.bbox, REGISTRY)
        classes = dict(
            store.conn.execute(
                "SELECT taxon_id, any_value(effort_class) FROM _obs "
                "WHERE dedupe_key LIKE 'snail-%' OR taxon_id = 'piscis-communis' GROUP BY 1"
            ).fetchall()
        )
    finally:
        store.conn.execute("DELETE FROM observations WHERE dedupe_key LIKE 'snail-%'")
    assert classes == {"megastraea-undosa": "casual", "piscis-communis": "dive_survey"}


def test_redate_from_event_ids_and_fetch_partitions():
    from datetime import timedelta

    import httpx

    from wildlife_scanner.connectors.base import RateLimiter, make_client
    from wildlife_scanner.connectors.gbif_events import fetch_event_ids
    from wildlife_scanner.core.time import Precision, TimeWindow
    from wildlife_scanner.storage.repair import (
        missing_event_ids,
        redate_from_event_ids,
        set_event_ids,
    )

    world = SyntheticWorld(
        observers=2, visits_per_observer=5, survey_sites=SITES, survey_species=(COMMON_FISH,)
    )
    records = [r for r in world.generate() if r.source_id == "synthetic-survey"][:40]
    stamp = datetime(2024, 11, 30, 8, tzinfo=UTC)
    placeholder = TimeWindow(start=stamp, end=stamp + timedelta(days=1), precision=Precision.DAY)
    true_dates = {r.source_record_id: r.time.start.date() for r in records}
    records = [r.model_copy(update={"time": placeholder}) for r in records]
    store = ObservationStore()
    store.add(records)
    conn = store.conn
    key = "synthetic-dive-survey"
    assert missing_event_ids(conn, key, [date(2024, 11, 30)]) == 40

    # Events are listed with a facet query, then each event's records are paged.
    event_of = {
        r.source_record_id: f"SITE_{true_dates[r.source_record_id]:%Y%m%d}_swath" for r in records
    }

    def api(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("facet") == "eventId":
            counts: dict[str, int] = {}
            for event in event_of.values():
                counts[event.lower()] = counts.get(event.lower(), 0) + 1
            names = sorted(counts)[int(params["facetOffset"]) :][: int(params["facetLimit"])]
            return httpx.Response(
                200,
                json={"facets": [{"counts": [{"name": n, "count": counts[n]} for n in names]}]},
            )
        members = [k for k, e in event_of.items() if e.lower() == params["eventId"]]
        offset, limit = int(params["offset"]), int(params["limit"])
        return httpx.Response(
            200,
            json={
                "results": [
                    {"key": int(k), "eventID": event_of[k]}
                    for k in members[offset : offset + limit]
                ]
            },
        )

    pairs = list(
        fetch_event_ids(
            key,
            "2024-11-30",
            world.bbox,
            client=make_client(transport=httpx.MockTransport(api)),
            limiter=RateLimiter(0),
            workers=1,
        )
    )
    assert len(pairs) == 40
    assert set_event_ids(conn, key, pairs) == 40
    assert redate_from_event_ids(conn, key, r"_(\d{8})_", [date(2024, 11, 30)]) == 40
    rows = conn.execute(
        "SELECT source_record_id, local_date, week, visit_key, time_start FROM observations"
    ).fetchall()
    for record_id, d, week, visit_key, start in rows:
        assert d == true_dates[record_id]
        assert week == min(d.isocalendar().week, 52)
        assert f"|{d.isoformat()}|" in visit_key
        assert start.date() == d  # local midnight at -117° is 08:00 UTC the same day
    assert missing_event_ids(conn, key, [date(2024, 11, 30)]) == 0
