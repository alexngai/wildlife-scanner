from datetime import UTC, datetime

import h3
import pytest

from wildlife_radar.baseline import BaselineConfig, backtest_baseline, build_baseline, estimate
from wildlife_radar.storage import ObservationStore
from wildlife_radar.synthetic import SyntheticWorld


def spearman(a, b):
    def ranks(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0] * len(x)
        for k, i in enumerate(order):
            r[i] = k
        return r

    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb)


@pytest.fixture(scope="module")
def world_store():
    world = SyntheticWorld(seed=7)
    store = ObservationStore()
    store.add(world.generate())
    report = build_baseline(store.conn, region_id="test", bbox=world.bbox)
    return world, store, report


def test_build_report(world_store):
    _, store, report = world_store
    assert report.taxa == 3
    assert report.cells > 50
    assert report.hit_rows > 0 and report.effort_rows > 0
    stored = store.conn.execute(
        "SELECT count(*) FROM prior_cells WHERE region_id = 'test' "
        "GROUP BY cell HAVING count(DISTINCT parent_cell) > 1"
    ).fetchall()
    assert stored == []


def test_target_group_correction_beats_raw_counts(world_store):
    world, store, _ = world_store
    # A resident species living mostly where observers rarely go: raw record counts track
    # observer effort, while the target-group-corrected baseline tracks where it really is.
    species = next(s for s in world.species if s.name == "Raritas orientalis")
    by_cell: dict[str, list[float]] = {}
    for e in estimate(store.conn, "test", "cell", 5.0, taxon_ids=[species.taxon_id]):
        by_cell.setdefault(e.cell, []).append(e.p)
    cells = sorted(by_cell)
    annual = [sum(by_cell[c]) / len(by_cell[c]) for c in cells]
    raw = dict(
        store.conn.execute(
            "SELECT cell_r6, count(*) FROM observations WHERE taxon_id = ? GROUP BY 1",
            [species.taxon_id],
        ).fetchall()
    )
    truth = [species.p_true(*h3.cell_to_latlng(c), 20) for c in cells]
    rho_est = spearman(annual, truth)
    rho_raw = spearman([raw.get(c, 0) for c in cells], truth)
    assert rho_est > 0.5
    assert rho_est > rho_raw + 0.2


def test_seasonality_recovered(world_store):
    _, store, _ = world_store
    est = estimate(store.conn, "test", "context", 5.0, taxon_ids=["vernalis-litoralis"])
    by_week = {}
    for e in est:
        by_week.setdefault(e.week, []).append(e.p)
    mean = {w: sum(v) / len(v) for w, v in by_week.items()}
    peak = max(mean, key=mean.get)
    assert abs(peak - 20) <= 2
    assert mean[peak] > 3 * mean[46]


def test_levels_are_consistent(world_store):
    _, store, _ = world_store
    fine = estimate(store.conn, "test", "cell", 5.0, taxon_ids=["vernalis-litoralis"], weeks=[20])
    ctx = {
        e.cell: e.p
        for e in estimate(
            store.conn, "test", "context", 5.0, taxon_ids=["vernalis-litoralis"], weeks=[20]
        )
    }
    for e in fine:
        assert e.p_context == pytest.approx(ctx[h3.cell_to_parent(e.cell, 3)])
        assert e.lift == pytest.approx(e.p / e.p_context)


def test_backtest_gates(world_store):
    world, store, _ = world_store
    scores = {
        s.taxon_id: s
        for s in backtest_baseline(
            store.conn, region_id="test", bbox=world.bbox, split=datetime(2025, 1, 1, tzinfo=UTC)
        )
    }
    seasonal = scores["vernalis-litoralis"]
    assert seasonal.bss > 0.2 and seasonal.passes
    assert all(s.n_test > 1000 for s in scores.values())
    gates = store.conn.execute(
        "SELECT count(*) FROM baseline_gates WHERE region_id = 'test'"
    ).fetchone()[0]
    assert gates == 3
    leftovers = store.conn.execute(
        "SELECT count(*) FROM prior_effort WHERE region_id LIKE '%backtest%'"
    ).fetchone()[0]
    assert leftovers == 0


def test_cutoff_and_min_visits():
    world = SyntheticWorld(seed=3, observers=20, visits_per_observer=30)
    store = ObservationStore()
    store.add(world.generate())
    early = build_baseline(
        store.conn, region_id="a", bbox=world.bbox, cutoff=datetime(2023, 6, 1, tzinfo=UTC)
    )
    full = build_baseline(store.conn, region_id="b", bbox=world.bbox)
    assert early.visits < full.visits
    recent = build_baseline(
        store.conn, region_id="d", bbox=world.bbox, config=BaselineConfig(since_year=2025)
    )
    assert recent.visits < full.visits
    strict = build_baseline(
        store.conn, region_id="c", bbox=world.bbox, config=BaselineConfig(min_visits=10_000)
    )
    assert strict.taxa == 0


def test_config_validation():
    with pytest.raises(ValueError):
        BaselineConfig(res=8)  # finer than the visit resolution
    with pytest.raises(ValueError):
        BaselineConfig(res=5, parent_res=5)
    weights = BaselineConfig().kernel()
    assert sum(w for _, w in weights) == pytest.approx(1.0)


def test_specimens_and_captives_are_excluded():
    from datetime import timedelta

    from wildlife_radar.core import Observation, Outcome, TaxonRef, TaxonScheme, TimeWindow
    from wildlife_radar.core.licenses import CC_BY

    world = SyntheticWorld(seed=9, observers=10, visits_per_observer=20)
    obs = world.generate()
    start = datetime(2024, 3, 1, 17, tzinfo=UTC)
    zoo = [
        Observation(
            obs_id=f"zoo:{i}",
            source_id="zoo",
            taxon=TaxonRef(scheme=TaxonScheme.NAME, id="x", name="Canis lupus", rank="species"),
            footprint={"kind": "point", "lat": 32.74, "lon": -117.15, "uncertainty_m": 10},
            time=TimeWindow.instant(start + timedelta(days=i)),
            outcome=Outcome.PRESENCE_ONLY,
            license=CC_BY,
            extras={"group": "birds", "basis_of_record": basis, "observer_hash": f"z{i}"},
        )
        for i, basis in enumerate(["LIVING_SPECIMEN"] * 6 + ["PRESERVED_SPECIMEN"] * 6)
    ]
    store = ObservationStore()
    store.add([*obs, *zoo])
    build_baseline(store.conn, region_id="z", bbox=world.bbox)
    taxa = {r[0] for r in store.conn.execute("SELECT taxon_id FROM prior_taxa").fetchall()}
    assert "canis-lupus" not in taxa
    build_baseline(
        store.conn, region_id="z2", bbox=world.bbox, config=BaselineConfig(exclude_basis=())
    )
    taxa = {
        r[0]
        for r in store.conn.execute(
            "SELECT taxon_id FROM prior_taxa WHERE region_id = 'z2'"
        ).fetchall()
    }
    assert "canis-lupus" in taxa
