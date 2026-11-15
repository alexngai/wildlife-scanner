"""Time-of-day and tide indices from hourly counts."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import duckdb
from test_publish import NOW, store  # noqa: F401  (fixture)

from wildlife_scanner.conditions import timed
from wildlife_scanner.connectors.astronomy import daily_events
from wildlife_scanner.pipeline.runner import Job, JobContext, run
from wildlife_scanner.policy.statuses import TIERS_SCHEMA
from wildlife_scanner.regions import load_region

LA_JOLLA = (32.867, -117.257)


def _hilo(start: datetime, days: int):
    """Semidiurnal-ish extremes: high 2.0 m, low 0.0 m, every 6 hours."""
    return [
        (start + timedelta(hours=6 * i), "H" if i % 2 == 0 else "L", 2.0 if i % 2 == 0 else 0.0)
        for i in range(days * 4 + 1)
    ]


def test_tide_stage_and_height_between_extremes():
    t0 = datetime(2024, 6, 1, tzinfo=UTC)
    s = timed.HourSignals(*LA_JOLLA, _hilo(t0, 2))
    stage, height = s.tide(t0 + timedelta(minutes=30))
    assert stage == "high" and abs(height - (1.0 + math.cos(math.pi * 0.5 / 6))) < 1e-9
    stage, height = s.tide(t0 + timedelta(hours=3))
    assert stage == "falling" and abs(height - 1.0) < 1e-9
    assert s.tide(t0 + timedelta(hours=5, minutes=30))[0] == "low"
    assert s.tide(t0 + timedelta(hours=9))[0] == "rising"
    assert s.tide(t0 - timedelta(hours=1)) is None  # before the first extreme
    edges = s.height_edges()
    assert len(edges) == 4 and edges == sorted(edges)


def test_diel_phase_and_hours_since_sunset_in_san_diego():
    s = timed.HourSignals(*LA_JOLLA)
    noon = datetime(2024, 6, 15, 20, tzinfo=UTC)  # ~12:00 local
    assert s.diel(noon) == "day" and s.hours_since_sunset(noon) is None
    assert s.diel(datetime(2024, 6, 15, 10, tzinfo=UTC)) == "night"  # ~02:00 local
    sunset = daily_events(*LA_JOLLA, date(2024, 6, 15), -8).sunset
    later = sunset + timedelta(hours=1, minutes=30)
    assert abs(s.hours_since_sunset(later) - 1.5) < 1e-6
    assert s.category("astro.hours_since_sunset", later - timedelta(minutes=30), []) == "1-2h"
    assert s.diel(sunset - timedelta(minutes=30)) == "dusk"


def _counts(s: timed.HourSignals, peak_after_sunset: float):
    """Effort spread over every hour; the taxon only ~``peak`` hours after sunset."""
    taxon, effort = {}, {}
    for d in range(120):
        day = date(2024, 5, 1) + timedelta(days=d)
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        for h in range(24):
            effort[start + timedelta(hours=h)] = 5
        sunset = daily_events(*LA_JOLLA, day, -8).sunset
        hour = (sunset + timedelta(hours=peak_after_sunset)).replace(
            minute=0, second=0, microsecond=0
        )
        taxon[hour] = taxon.get(hour, 0) + 3
    return taxon, effort


def test_index_and_verdicts():
    s = timed.HourSignals(*LA_JOLLA)
    taxon, effort = _counts(s, 1.2)
    rows = timed.category_index(
        taxon,
        effort,
        lambda t: s.category("astro.hours_since_sunset", t, []),
        timed.TIMED_SIGNALS["astro.hours_since_sunset"],
        s.offset,
    )
    by = {r.category: r for r in rows}
    assert by["0-1h"].index > 1 or by["1-2h"].index > 1
    assert by["daylight"].index == 0.0
    spec = SimpleNamespace(params={"at": 1})
    v = timed.judge("hours_after_sunset", spec, "astro.hours_since_sunset", rows)
    assert v.verdict == "supported" and v.review is None
    late = SimpleNamespace(params={"at": 8})
    v = timed.judge("hours_after_sunset", late, "astro.hours_since_sunset", rows)
    assert v.verdict == "contradicted" and "peak" in v.review
    # Diel phase against a trait.
    diel = timed.category_index(
        taxon, effort, lambda t: s.category("astro.diel_phase", t, []), timed.DIEL, s.offset
    )
    assert timed.judge("d", None, "astro.diel_phase", diel, "nocturnal").verdict == "supported"
    assert timed.judge("d", None, "astro.diel_phase", diel, "diurnal").verdict == "contradicted"
    # No pattern: identical shares.
    flat = timed.category_index(
        effort, effort, lambda t: s.category("astro.diel_phase", t, []), timed.DIEL, s.offset
    )
    assert timed.judge("d", None, "astro.diel_phase", flat, "diurnal").verdict == "inconclusive"


class _FakeHistogram:
    def __init__(self, taxon, effort):
        self.taxon, self.effort, self.calls = taxon, effort, []

    def hourly(self, taxon_ids, bbox, start, end):
        self.calls.append(tuple(taxon_ids))
        return self.taxon if taxon_ids == ["9999"] else self.effort


class _FakeTides:
    def predictions(self, station_id, start, end, interval):
        t0 = datetime(start.year, start.month, start.day, tzinfo=UTC)
        days = (end - start).days + 1
        return [
            SimpleNamespace(valid_time=t, attrs={"type": k}, value=h) for t, k, h in _hilo(t0, days)
        ]


def test_timed_job_scores_profiled_species(tmp_path):
    from wildlife_scanner.pipeline import runner
    from wildlife_scanner.storage import ObservationStore

    region = load_region("sandiego")
    db = tmp_path / "store.duckdb"
    with ObservationStore(db) as work:
        work.conn.execute(
            "CREATE TABLE prior_taxa AS SELECT 'sandiego' AS region_id, "
            "'atractoscion-nobilis' AS taxon_id, 'fishes' AS taxon_group, "
            "'Atractoscion nobilis' AS scientific_name, 50 AS n_visits "
            "UNION ALL SELECT 'sandiego', 'larus-occidentalis', 'birds', 'Larus occidentalis', 900"
        )
        work.conn.execute(TIERS_SCHEMA)
        work.conn.execute(
            "INSERT INTO tiers (region_id, taxon_id, tier) "
            "VALUES ('sandiego', 'larus-occidentalis', 0)"
        )
        work.conn.execute(
            "CREATE TABLE inat_taxon_records AS SELECT 'atractoscion-nobilis' AS taxon_id, "
            "'9999' AS inat_id, '{}'::JSON AS record, now()::TIMESTAMP AS fetched_at "
            "UNION ALL SELECT 'larus-occidentalis', '7777', '{}'::JSON, now()::TIMESTAMP"
        )
    s = timed.HourSignals(*LA_JOLLA)
    taxon, effort = _counts(s, 1.2)
    hist = _FakeHistogram(taxon, effort)
    ctx = JobContext(
        region=region,
        region_path=None,
        db=db,
        lake=tmp_path / "lake",
        now=datetime(2024, 9, 1, tzinfo=UTC),
        log=lambda _m: None,
        params={"_histogram": hist, "_tides": _FakeTides()},
    )
    ctx.region.pipeline.since_year = 2024
    result = run("timed", ctx, jobs={"timed": Job("timed", (), runner._timed)})[0]
    out = result["outcome"]
    assert isinstance(out, dict), out
    assert out["taxa"]["atractoscion-nobilis"]["verdicts"]["hours_after_sunset"] == "supported"
    assert "larus-occidentalis" in out["taxa"]  # picked by group, not only profiled species
    assert set(hist.calls) == {("9999",), ("47178", "47273"), ("7777",), ("3",)}
    conn = duckdb.connect(str(db), read_only=True)
    signals = {r[0] for r in conn.execute("SELECT DISTINCT signal FROM timed_index").fetchall()}
    assert signals == {
        "astro.diel_phase",
        "astro.hours_since_sunset",
        "astro.moonlight",
        "tide.stage",
        "tide.height_m",
    }
    # The hourly model ran and was stored (gate outcome depends on the synthetic counts).
    assert "passes" in out["taxa"]["atractoscion-nobilis"]["hourly"]
    stored = conn.execute("SELECT count(*) FROM hourly_models").fetchone()[0]
    assert stored == 2  # the profiled species and the group-picked one


def test_timing_is_published_for_open_and_generalized_taxa_only(store, tmp_path):  # noqa: F811
    import warnings

    from wildlife_scanner.pipeline.publish import current_bundle, publish_bundle

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

    from wildlife_scanner.api import create_app

    st, region = store
    st.conn.execute(timed.TIMED_SCHEMA)
    for taxon in ("vernalis-litoralis", "raritas-orientalis", "secretus-maximus"):
        st.conn.execute(
            "INSERT INTO timed_index VALUES ('socal', ?, 'astro.diel_phase', 'night', "
            "5, 50, 2.0, 1.5, 2.5, now()::TIMESTAMP)",
            [taxon],
        )
    publish_bundle(st.conn, region, tmp_path, now=NOW)
    bundle = duckdb.connect(str(current_bundle(tmp_path / "region=socal")), read_only=True)
    published = {r[0] for r in bundle.execute("SELECT taxon_id FROM timed_index").fetchall()}
    assert published == {"vernalis-litoralis"}  # COARSE and WITHHELD are left out
    bundle.close()
    client = TestClient(create_app(bundle_dir=tmp_path, region_id="socal", now=NOW))
    body = client.get("/species/vernalis-litoralis/timing").json()
    assert body["signals"]["astro.diel_phase"][0]["index"] == 2.0
    assert client.get("/species/raritas-orientalis/timing").status_code == 404
    assert client.get("/species/secretus-maximus/timing").status_code == 404
