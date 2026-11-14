"""Level 1 (conditions) and Level 2 (live nowcast): fit, gate, and score hypotheses.

For each taxon × effort group:

1. **Trials.** Outing-based groups: every outing of the group, ``y`` = the taxon was recorded.
   Survey groups: the taxon's present/absent records. Training trials are dated before the
   split, test trials after it. Negatives are subsampled and up-weighted.
2. **Level 0 offset.** The Level-0 baseline built on training data only (cell → parent →
   context → range-only fallback, as in the Level-0 backtest).
3. **Level 1** adds the profile's condition terms for which daily signals exist near the trial
   (nearest station within the signal's reach). Anomaly normals use training days only.
4. **Level 2** adds a nowcast: detections of the taxon and outings recording its taxon group in
   the same parent cell during the previous ``nowcast_days`` days (strictly before the trial's
   date; no same-day contagion), from live sources only (as available when forecasting).
5. **Gates** (framework.md §5.4): Level 1 must beat Level 0 (recalibrated) and Level 2 must
   beat Level 1 out of sample, with the lower end of a 90% block-bootstrap interval (blocks =
   test days) above 0 and a Brier improvement of at least ``min_skill`` (0.5%); Level 2 must
   also beat persistence (the shrunk recent rate).
6. **Hypothesis scorecard**: each term is dropped in turn; the change in held-out log loss
   (with its interval) says whether the term earns its place: supported, contradicted or
   inconclusive.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime

import duckdb
import h3
import numpy as np

from wildlife_radar.baseline.builder import BaselineConfig, build_baseline, create_training_view
from wildlife_radar.baseline.effort import SURVEY_CLASSES, DatasetRegistry, split_egroup
from wildlife_radar.baseline.estimate import estimate_query
from wildlife_radar.conditions.daily import DAILY_SIGNALS, moon_on, normals
from wildlife_radar.conditions.model import (
    OffsetLogit,
    TermSpec,
    block_bootstrap,
    brier,
    log_loss,
    logit,
)
from wildlife_radar.core.spatial import haversine_km
from wildlife_radar.core.time import utcnow
from wildlife_radar.storage.observations import naive_utc

CONDITIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS conditions_gates (
    region_id VARCHAR, taxon_id VARCHAR, group_id VARCHAR, level SMALLINT, n_train BIGINT,
    n_test BIGINT, n_pos BIGINT, brier_ref DOUBLE, brier DOUBLE, skill DOUBLE, ci_lo DOUBLE,
    ci_hi DOUBLE, passes BOOLEAN, split TIMESTAMP, evaluated_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS conditions_models (
    region_id VARCHAR, taxon_id VARCHAR, group_id VARCHAR, level SMALLINT, model JSON,
    fitted_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS hypothesis_scorecard (
    region_id VARCHAR, taxon_id VARCHAR, group_id VARCHAR, term VARCHAR, signal VARCHAR,
    hypothesis BOOLEAN, n_test BIGINT, delta_log_loss DOUBLE, ci_lo DOUBLE, ci_hi DOUBLE,
    direction_expected VARCHAR, direction_fitted VARCHAR, verdict VARCHAR,
    evaluated_at TIMESTAMP, review VARCHAR
);
ALTER TABLE hypothesis_scorecard ADD COLUMN IF NOT EXISTS review VARCHAR;
"""

NOWCAST_TERMS = [
    TermSpec("recent_detections", "nowcast.log_detections", "linear", "moderate"),
    TermSpec("recent_effort", "nowcast.log_effort", "linear", "moderate"),
]


@dataclass(frozen=True)
class Station:
    station_id: str
    lat: float
    lon: float
    signals: frozenset[str]


@dataclass
class LevelResult:
    level: int
    n_test: int
    n_pos: int
    brier_ref: float
    brier: float
    skill: float
    ci: tuple[float, float]
    passes: bool


@dataclass
class TermScore:
    term: str
    signal: str
    hypothesis: bool
    delta_log_loss: float
    ci: tuple[float, float]
    direction_expected: str | None
    direction_fitted: str | None
    verdict: str

    @property
    def review(self) -> str | None:
        """Why the profile's claim for this term needs a human look, if it does. A term can
        improve predictions for a reason other than the one the profile gives."""
        if self.verdict == "contradicted":
            return "the term makes held-out predictions worse"
        if (
            self.direction_expected
            and self.direction_fitted
            and self.direction_expected != self.direction_fitted
        ):
            return (
                f"fitted direction {self.direction_fitted} contradicts the profile's "
                f"{self.direction_expected}"
            )
        return None


@dataclass
class ConditionsReport:
    taxon_id: str
    group_id: str
    terms: list[str]
    n_train: int = 0
    n_test: int = 0
    n_pos_test: int = 0
    levels: list[LevelResult] = field(default_factory=list)
    scorecard: list[TermScore] = field(default_factory=list)
    brier_persistence: float | None = None
    brier_level0: float | None = None
    """Held-out Brier of Level 0 as built (before recalibration), for reference."""
    notes: list[str] = field(default_factory=list)
    models: dict[int, OffsetLogit] = field(default_factory=dict)


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(CONDITIONS_SCHEMA)


def stations_in_store(
    conn: duckdb.DuckDBPyConnection, coords: dict[str, tuple[float, float]]
) -> list[Station]:
    rows = conn.execute(
        "SELECT station_id, list(DISTINCT signal_id) FROM signal_daily GROUP BY 1"
    ).fetchall()
    present = {s: set(sig) for s, sig in rows}
    out = []
    for sid, (lat, lon) in coords.items():
        sigs = present.get(sid, set())
        # Anomalies are derived from their base signal at the same station.
        sigs |= {k for k, d in DAILY_SIGNALS.items() if d.base and d.base in sigs}
        if sigs:
            out.append(Station(sid, lat, lon, frozenset(sigs)))
    return out


def nearest_station(lat: float, lon: float, stations: list[Station], signal: str) -> str | None:
    spec = DAILY_SIGNALS[signal]
    best, best_km = None, math.inf
    for s in stations:
        if signal not in s.signals:
            continue
        km = haversine_km(lat, lon, s.lat, s.lon)
        if km < best_km:
            best, best_km = s.station_id, km
    if spec.reach_km is not None and best_km > spec.reach_km:
        return None
    return best


class SignalLookup:
    """Daily signal values for (cell, date), with anomaly normals from training days only."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        stations: list[Station],
        signals: list[str],
        normals_before: date | None,
    ) -> None:
        self.stations = stations
        self.signals = signals
        self.values: dict[tuple[str, str, date], float] = {}
        bases = {DAILY_SIGNALS[s].base or s for s in signals if DAILY_SIGNALS[s].family != "astro"}
        if bases:
            for sid, sig, day, value in conn.execute(
                "SELECT station_id, signal_id, day, value FROM signal_daily "
                "WHERE signal_id IN (SELECT unnest(?))",
                [sorted(bases)],
            ).fetchall():
                self.values[(sid, sig, day)] = value
        self.normals = {
            s: normals(conn, DAILY_SIGNALS[s].base, normals_before)
            for s in signals
            if DAILY_SIGNALS[s].base
        }
        self._cell_station: dict[tuple[str, str], str | None] = {}
        self._moon: dict[date, tuple[float, float]] = {}

    def station_for(self, cell: str, signal: str) -> str | None:
        key = (cell, signal)
        if key not in self._cell_station:
            lat, lon = h3.cell_to_latlng(cell)
            self._cell_station[key] = nearest_station(lat, lon, self.stations, signal)
        return self._cell_station[key]

    def value(self, cell: str, day: date, signal: str) -> float:
        spec = DAILY_SIGNALS[signal]
        if spec.family == "astro":
            if day not in self._moon:
                self._moon[day] = moon_on(day)
            illum, phase = self._moon[day]
            return illum if signal == "astro.moon_illumination" else phase
        station = self.station_for(cell, signal)
        if station is None:
            return math.nan
        raw = self.values.get((station, spec.base or signal, day))
        if raw is None:
            return math.nan
        if spec.base:
            normal = self.normals[signal].get((station, day.timetuple().tm_yday))
            return raw - normal if normal is not None else math.nan
        return raw

    def matrix(self, cells: list[str], days: list[date]) -> dict[str, np.ndarray]:
        return {
            s: np.array([self.value(c, d, s) for c, d in zip(cells, days, strict=True)])
            for s in self.signals
        }


def _direction(model: OffsetLogit, term: TermSpec, x: np.ndarray) -> str | None:
    finite = x[np.isfinite(x)]
    if term.shape not in ("linear", "monotone") or len(finite) < 10:
        return None
    lo, hi = np.percentile(finite, [10, 90])
    curve = model.effect_curve(term.name, [float(lo), float(hi)])
    return "+" if curve[1][1] > curve[0][1] else "-"


def _trials(
    conn: duckdb.DuckDBPyConnection,
    taxon_id: str,
    group_id: str,
    split: datetime,
    neg_per_pos: int,
    max_neg: int,
    seed: int,
) -> list[tuple]:
    """``(c, c1, c2, week, day, y, weight, is_test)`` rows for one taxon × group."""
    _, effort_class = split_egroup(group_id)
    split_d = naive_utc(split).date()
    if effort_class in SURVEY_CLASSES:
        rows = conn.execute(
            """
            SELECT c, c1, c2, week, local_date, detected::INTEGER FROM _all
            WHERE taxon_id = ? AND egroup = ? AND local_date IS NOT NULL
            """,
            [taxon_id, group_id],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            WITH v AS (
                SELECT visit_key, any_value(c) AS c, any_value(c1) AS c1,
                       any_value(c2) AS c2, any_value(week) AS week, any_value(local_date) AS d
                FROM _all WHERE egroup = ? AND local_date IS NOT NULL GROUP BY visit_key
            ),
            h AS (
                SELECT DISTINCT visit_key FROM _all
                WHERE taxon_id = ? AND egroup = ? AND detected
            )
            SELECT v.c, v.c1, v.c2, v.week, v.d, (h.visit_key IS NOT NULL)::INTEGER
            FROM v LEFT JOIN h USING (visit_key)
            """,
            [group_id, taxon_id, group_id],
        ).fetchall()
    rng = np.random.default_rng(seed)
    out = []
    for is_test in (False, True):
        part = [r for r in rows if (r[4] >= split_d) == is_test]
        pos = [r for r in part if r[5]]
        neg = [r for r in part if not r[5]]
        keep = min(len(neg), max(neg_per_pos * max(len(pos), 1), 1000), max_neg)
        idx = rng.choice(len(neg), size=keep, replace=False) if keep < len(neg) else range(len(neg))
        w = len(neg) / keep if keep else 1.0
        out += [(*r, 1.0, is_test) for r in pos]
        out += [(*neg[i], w, is_test) for i in idx]
    return out


def _level0(
    conn: duckdb.DuckDBPyConnection,
    bt: str,
    taxon_id: str,
    group_id: str,
    cfg: BaselineConfig,
    floor: float,
) -> np.ndarray:
    for name, level, col in (
        ("_ce0", "cell", "c"),
        ("_ce1", "parent", "c1"),
        ("_ce2", "context", "c2"),
    ):
        sql, params = estimate_query(
            bt,
            level,
            cfg.shrinkage,
            taxon_ids=[taxon_id],
            groups=[group_id],
            cells_subquery=f"SELECT DISTINCT {col} FROM _ctrials",
        )
        conn.execute(f"CREATE OR REPLACE TEMP TABLE {name} AS {sql}", params)
    rows = conn.execute(
        """
        SELECT coalesce(e0.p, e1.p, e2.p,
            CASE WHEN m.context_cell IS NOT NULL THEN t.annual_rate ELSE ? END)
        FROM _ctrials tr
        LEFT JOIN prior_taxa t ON t.region_id = ? AND t.taxon_id = ? AND t.group_id = ?
        LEFT JOIN prior_mask m ON m.region_id = ? AND m.taxon_id = ? AND m.context_cell = tr.c2
        LEFT JOIN _ce0 e0 ON e0.cell = tr.c AND e0.week = tr.week
        LEFT JOIN _ce1 e1 ON e1.cell = tr.c1 AND e1.week = tr.week
        LEFT JOIN _ce2 e2 ON e2.cell = tr.c2 AND e2.week = tr.week
        ORDER BY tr.i
        """,
        [floor, bt, taxon_id, group_id, bt, taxon_id],
    ).fetchall()
    return np.array([r[0] if r[0] is not None else floor for r in rows], dtype=float)


def _nowcast(
    conn: duckdb.DuckDBPyConnection, taxon_id: str, group_id: str, days: int
) -> tuple[np.ndarray, np.ndarray]:
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _cdet AS
        SELECT c1, local_date AS d, count(DISTINCT visit_key) AS k FROM _all
        WHERE taxon_id = ? AND detected AND live GROUP BY ALL
        """,
        [taxon_id],
    )
    # Only live sources (as available when forecasting): outings of the taxon group.
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _ceff AS
        SELECT c1, local_date AS d, count(DISTINCT visit_key) AS n FROM _all
        WHERE live AND taxon_group = ? GROUP BY ALL
        """,
        [split_egroup(group_id)[0]],
    )

    def window_sum(table: str, col: str) -> np.ndarray:
        rows = conn.execute(
            f"""
            SELECT tr.i, coalesce(sum(x.{col}), 0) FROM _ctrials tr
            LEFT JOIN {table} x ON x.c1 = tr.c1
                AND x.d BETWEEN tr.d - {int(days)} AND tr.d - 1
            GROUP BY tr.i ORDER BY tr.i
            """
        ).fetchall()
        return np.array([r[1] for r in rows], dtype=float)

    return window_sum("_cdet", "k"), window_sum("_ceff", "n")


def evaluate_taxon(
    conn: duckdb.DuckDBPyConnection,
    *,
    bt: str,
    taxon_id: str,
    group_id: str,
    terms: list[TermSpec],
    lookup: SignalLookup,
    split: datetime,
    cfg: BaselineConfig,
    nowcast_days: int = 14,
    neg_per_pos: int = 20,
    max_neg: int = 60_000,
    min_pos: int = 20,
    reps: int = 200,
    floor: float = 1e-4,
    seed: int = 7,
    min_skill: float = 0.005,
) -> ConditionsReport:
    report = ConditionsReport(taxon_id, group_id, [t.name for t in terms])
    rows = _trials(conn, taxon_id, group_id, split, neg_per_pos, max_neg, seed)
    if not rows:
        report.notes.append("no trials")
        return report
    conn.execute(
        "CREATE OR REPLACE TEMP TABLE _ctrials (i INTEGER, c VARCHAR, c1 VARCHAR, c2 VARCHAR, "
        "week SMALLINT, d DATE)"
    )
    conn.executemany(
        "INSERT INTO _ctrials VALUES (?, ?, ?, ?, ?, ?)",
        [(i, r[0], r[1], r[2], r[3], r[4]) for i, r in enumerate(rows)],
    )
    y = np.array([r[5] for r in rows], dtype=float)
    w = np.array([r[6] for r in rows], dtype=float)
    test = np.array([r[7] for r in rows], dtype=bool)
    days = [r[4] for r in rows]
    p0 = _level0(conn, bt, taxon_id, group_id, cfg, floor)
    sig = lookup.matrix([r[0] for r in rows], days)
    k, n = _nowcast(conn, taxon_id, group_id, nowcast_days)
    sig["nowcast.log_detections"] = np.log1p(k)
    sig["nowcast.log_effort"] = np.log1p(n)

    # Only trials where every condition signal is available (coverage of the stations).
    covered = np.ones(len(rows), dtype=bool)
    for t in terms:
        covered &= np.isfinite(sig[t.signal])
    train, held = covered & ~test, covered & test
    report.n_train, report.n_test = int(train.sum()), int(held.sum())
    report.n_pos_test = int(y[held].sum())
    if y[train].sum() < min_pos or report.n_pos_test < min_pos:
        report.notes.append(
            f"too few detections with condition data (train {int(y[train].sum())}, "
            f"test {report.n_pos_test}; need {min_pos})"
        )
        return report

    def sub(mask):
        return {s: v[mask] for s, v in sig.items()}

    off = logit(p0)
    # Level 1 refits an intercept, which alone recalibrates Level 0 to recent years. The gate
    # compares against that recalibrated Level 0, so only the condition terms earn the pass.
    m0 = OffsetLogit([]).fit(sub(train), y[train], off[train], w[train])
    m1 = OffsetLogit(terms).fit(sub(train), y[train], off[train], w[train])
    yt, wt, p0t = y[held], w[held], p0[held]
    p0r = m0.predict(sub(held), off[held])
    p1 = m1.predict(sub(held), off[held])
    kt, nt = k[held], n[held]
    persistence = (kt + 5 * p0r) / (nt + 5)
    blocks = np.array([d.toordinal() for d, h in zip(days, held, strict=True) if h])

    def level(level_no, p_ref, p) -> LevelResult:
        b_ref, b = brier(yt, p_ref, wt), brier(yt, p, wt)

        def skill(idx):
            ref = brier(yt[idx], p_ref[idx], wt[idx])
            return 1 - brier(yt[idx], p[idx], wt[idx]) / ref if ref > 0 else 0.0

        ci = block_bootstrap(blocks, skill, reps=reps, seed=seed)
        skill_all = 1 - b / b_ref if b_ref > 0 else 0.0
        # A level must beat the one below reliably (interval above zero) *and* by a margin
        # worth labeling: tiny gains on rare taxa would otherwise switch levels on.
        passes = bool(ci[0] > 0 and skill_all >= min_skill)
        return LevelResult(level_no, len(yt), int(yt.sum()), b_ref, b, skill_all, ci, passes)

    l1 = level(1, p0r, p1)
    # Level 2 builds on the best level below it: the conditions model if Level 1 passed,
    # otherwise the recalibrated Level 0 (recent sightings can help without conditions).
    base_terms, p_base = (terms, p1) if l1.passes else ([], p0r)
    m2 = OffsetLogit([*base_terms, *NOWCAST_TERMS]).fit(sub(train), y[train], off[train], w[train])
    p2 = m2.predict(sub(held), off[held])
    l2 = level(2, p_base, p2)
    report.brier_persistence = brier(yt, persistence, wt)
    report.brier_level0 = brier(yt, p0t, wt)
    l2.passes = l2.passes and l2.brier < report.brier_persistence
    report.levels = [l1, l2]
    held_sig = sub(held)
    for t in terms:
        others = [u for u in terms if u.name != t.name]
        m_wo = OffsetLogit(others).fit(sub(train), y[train], off[train], w[train])
        p_wo = m_wo.predict(held_sig, off[held])

        def gain(idx, p_wo=p_wo):
            return log_loss(yt[idx], p_wo[idx], wt[idx]) - log_loss(yt[idx], p1[idx], wt[idx])

        delta = log_loss(yt, p_wo, wt) - log_loss(yt, p1, wt)
        ci = block_bootstrap(blocks, gain, reps=reps, seed=seed)
        verdict = "supported" if ci[0] > 0 else "contradicted" if ci[1] < 0 else "inconclusive"
        report.scorecard.append(
            TermScore(
                term=t.name,
                signal=t.signal,
                hypothesis=t.hypothesis,
                delta_log_loss=delta,
                ci=ci,
                direction_expected=t.direction,
                direction_fitted=_direction(m1, t, sig[t.signal][train]),
                verdict=verdict,
            )
        )
    report.models = {1: m1, 2: m2}
    return report


def run_conditions(
    conn: duckdb.DuckDBPyConnection,
    *,
    region_id: str,
    bbox: tuple[float, float, float, float],
    split: datetime,
    end: datetime | None,
    specs: dict[str, list[TermSpec]],
    station_coords: dict[str, tuple[float, float]],
    config: BaselineConfig | None = None,
    registry: DatasetRegistry | None = None,
    groups: dict[str, list[str]] | None = None,
    **kwargs,
) -> list[ConditionsReport]:
    """Fit and gate Levels 1–2 for ``specs`` (taxon → terms); results are persisted."""
    cfg = config or BaselineConfig()
    ensure_schema(conn)
    bt = f"{region_id}__conditions"
    build_baseline(conn, region_id=bt, bbox=bbox, config=cfg, cutoff=split, registry=registry)
    create_training_view(conn, cfg, bbox, registry, name="_all", before=end)
    stations = stations_in_store(conn, station_coords)
    signals = sorted({t.signal for terms in specs.values() for t in terms})
    lookup = SignalLookup(conn, stations, signals, normals_before=naive_utc(split).date())
    reports = []
    now = naive_utc(utcnow())
    for taxon_id, terms in specs.items():
        taxon_groups = groups.get(taxon_id) if groups else None
        if not taxon_groups:
            taxon_groups = [
                g
                for (g,) in conn.execute(
                    "SELECT group_id FROM prior_taxa WHERE region_id = ? AND taxon_id = ? "
                    "ORDER BY n_visits DESC",
                    [bt, taxon_id],
                ).fetchall()
            ]
        for group_id in taxon_groups:
            report = evaluate_taxon(
                conn,
                bt=bt,
                taxon_id=taxon_id,
                group_id=group_id,
                terms=terms,
                lookup=lookup,
                split=split,
                cfg=cfg,
                **kwargs,
            )
            reports.append(report)
            _persist(conn, region_id, split, now, report)
    return reports


def _persist(
    conn: duckdb.DuckDBPyConnection,
    region_id: str,
    split: datetime,
    now: datetime,
    report: ConditionsReport,
) -> None:
    key = [region_id, report.taxon_id, report.group_id]
    for table in ("conditions_gates", "conditions_models", "hypothesis_scorecard"):
        conn.execute(
            f"DELETE FROM {table} WHERE region_id = ? AND taxon_id = ? AND group_id = ?", key
        )
    split_n = naive_utc(split)
    for lv in report.levels:
        conn.execute(
            "INSERT INTO conditions_gates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                *key,
                lv.level,
                report.n_train,
                lv.n_test,
                lv.n_pos,
                lv.brier_ref,
                lv.brier,
                lv.skill,
                lv.ci[0],
                lv.ci[1],
                lv.passes,
                split_n,
                now,
            ],
        )
    for level_no, model in report.models.items():
        conn.execute(
            "INSERT INTO conditions_models VALUES (?, ?, ?, ?, ?, ?)",
            [*key, level_no, json.dumps(model.to_dict()), now],
        )
    for s in report.scorecard:
        conn.execute(
            "INSERT INTO hypothesis_scorecard VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                *key,
                s.term,
                s.signal,
                s.hypothesis,
                report.n_test,
                s.delta_log_loss,
                s.ci[0],
                s.ci[1],
                s.direction_expected,
                s.direction_fitted,
                s.verdict,
                now,
                s.review,
            ],
        )
