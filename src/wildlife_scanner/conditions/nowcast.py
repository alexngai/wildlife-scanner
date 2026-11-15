"""Recent-sightings forecasts (Level 2) for every OPEN taxon with enough data.

Level 2 here is the Level-0 baseline (recalibrated by an intercept) plus two nowcast terms:
recorded detections of the taxon, and outings recording its taxon group, in the same parent
cell (~10 km) during the previous ``days`` days, strictly before the day. Both come only from
sources with a live feed (iNaturalist), in training as in serving, so a model trained on eBird
checklists still has its inputs when only iNaturalist is live. It needs no profile and no
stations, so it can run for hundreds of taxa. Taxa with a species profile get their Level 1–2
from ``levels.run_conditions`` instead.

To keep the per-taxon cost small, everything that depends only on the effort group is computed
once per group: its outings, a shared random sample of outings used as negatives (up-weighted
to the group's totals), and the recent effort around each outing. Per taxon, only its
detections, Level-0 offsets and the fit are computed. Gates are the same as in ``levels``:
beat the recalibrated Level 0 with a 90% block-bootstrap interval above zero and at least
``min_skill`` improvement, and beat persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import duckdb
import numpy as np

from wildlife_scanner.baseline.builder import BaselineConfig, build_baseline, create_training_view
from wildlife_scanner.baseline.effort import SURVEY_CLASSES, DatasetRegistry, split_egroup
from wildlife_scanner.baseline.estimate import estimate_query
from wildlife_scanner.conditions.levels import (
    NOWCAST_TERMS,
    ConditionsReport,
    LevelResult,
    _persist,
    ensure_schema,
)
from wildlife_scanner.conditions.model import OffsetLogit, block_bootstrap, brier, logit
from wildlife_scanner.core.time import utcnow
from wildlife_scanner.storage.observations import naive_utc


@dataclass
class NowcastSummary:
    fitted: int = 0
    passing: int = 0
    skipped: int = 0
    best: list[tuple[str, str, float]] | None = None


def _group_tables(
    conn: duckdb.DuckDBPyConnection, group_id: str, split_d, days: int, pool: int, seed: int
) -> tuple[int, int]:
    """Per-group outings with their recent group effort (``_ng_v``) and a negative pool sampled
    from them (``_ng_pool``). Returns (train, test) outing counts."""
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _ng_base AS
        SELECT visit_key, any_value(c) AS c, any_value(c1) AS c1, any_value(c2) AS c2,
               any_value(week) AS week, any_value(local_date) AS d,
               any_value(local_date) >= ? AS is_test
        FROM _all WHERE egroup = ? AND local_date IS NOT NULL GROUP BY visit_key
        """,
        [split_d, group_id],
    )
    # Recent effort: outings with live-source records of the same taxon group (whatever the
    # effort class), since only live sources are available when forecasting.
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _ng_eff AS
        SELECT c1, local_date AS d, count(DISTINCT visit_key) AS n FROM _all
        WHERE live AND taxon_group = ? AND local_date IS NOT NULL GROUP BY ALL
        """,
        [split_egroup(group_id)[0]],
    )
    # Recent effort depends only on the group: computed once for all its outings.
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _ng_v AS
        SELECT v.visit_key, v.c, v.c1, v.c2, v.week, v.d, v.is_test,
               coalesce(sum(e.n), 0) AS n_recent
        FROM _ng_base v LEFT JOIN _ng_eff e
            ON e.c1 = v.c1 AND e.d BETWEEN v.d - {int(days)} AND v.d - 1
        GROUP BY ALL
        """
    )
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _ng_pool AS
        SELECT * FROM (
            SELECT * FROM _ng_v WHERE NOT is_test
            USING SAMPLE reservoir({int(pool)} ROWS) REPEATABLE ({seed})
        )
        UNION ALL
        SELECT * FROM (
            SELECT * FROM _ng_v WHERE is_test
            USING SAMPLE reservoir({int(pool)} ROWS) REPEATABLE ({seed})
        )
        """
    )
    totals = dict(conn.execute("SELECT is_test, count(*) FROM _ng_v GROUP BY 1").fetchall())
    return int(totals.get(False, 0)), int(totals.get(True, 0))


def evaluate_nowcast(
    conn: duckdb.DuckDBPyConnection,
    *,
    bt: str,
    taxon_id: str,
    group_id: str,
    totals: tuple[int, int],
    cfg: BaselineConfig,
    days: int,
    min_pos: int,
    min_skill: float,
    reps: int,
    floor: float = 1e-4,
    seed: int = 7,
) -> ConditionsReport:
    report = ConditionsReport(taxon_id, group_id, [t.name for t in NOWCAST_TERMS])
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _nt_pos AS
        SELECT DISTINCT visit_key FROM _all WHERE taxon_id = ? AND egroup = ? AND detected
        """,
        [taxon_id, group_id],
    )
    # Trials: every outing with a detection, plus the group's negative pool minus detections.
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _nt AS
        SELECT v.*, 1 AS y FROM _ng_v v JOIN _nt_pos USING (visit_key)
        UNION ALL
        SELECT p.*, 0 AS y FROM _ng_pool p ANTI JOIN _nt_pos USING (visit_key)
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _nt_det AS
        SELECT c1, local_date AS d, count(DISTINCT visit_key) AS k FROM _all
        WHERE taxon_id = ? AND detected AND live GROUP BY ALL
        """,
        [taxon_id],
    )
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _nt AS
        SELECT g.*, row_number() OVER (ORDER BY g.visit_key) - 1 AS i FROM (
            SELECT t.*, coalesce(sum(x.k), 0) AS k_recent
            FROM _nt t LEFT JOIN _nt_det x
                ON x.c1 = t.c1 AND x.d BETWEEN t.d - {int(days)} AND t.d - 1
            GROUP BY ALL
        ) g
        """
    )
    for name, level, col in (
        ("_ne0", "cell", "c"),
        ("_ne1", "parent", "c1"),
        ("_ne2", "context", "c2"),
    ):
        sql, params = estimate_query(
            bt,
            level,
            cfg.shrinkage,
            taxon_ids=[taxon_id],
            groups=[group_id],
            cells_subquery=f"SELECT DISTINCT {col} FROM _nt",
        )
        conn.execute(f"CREATE OR REPLACE TEMP TABLE {name} AS {sql}", params)
    rows = conn.execute(
        """
        SELECT t.y, t.is_test, t.d, t.k_recent, t.n_recent,
            coalesce(e0.p, e1.p, e2.p,
                CASE WHEN m.context_cell IS NOT NULL THEN pt.annual_rate ELSE ? END)
        FROM _nt t
        LEFT JOIN prior_taxa pt ON pt.region_id = ? AND pt.taxon_id = ? AND pt.group_id = ?
        LEFT JOIN prior_mask m ON m.region_id = ? AND m.taxon_id = ? AND m.context_cell = t.c2
        LEFT JOIN _ne0 e0 ON e0.cell = t.c AND e0.week = t.week
        LEFT JOIN _ne1 e1 ON e1.cell = t.c1 AND e1.week = t.week
        LEFT JOIN _ne2 e2 ON e2.cell = t.c2 AND e2.week = t.week
        ORDER BY t.i
        """,
        [floor, bt, taxon_id, group_id, bt, taxon_id],
    ).fetchall()
    if not rows:
        report.notes.append("no trials")
        return report
    y = np.array([r[0] for r in rows], dtype=float)
    test = np.array([r[1] for r in rows], dtype=bool)
    days_ = [r[2] for r in rows]
    k = np.array([r[3] for r in rows], dtype=float)
    n = np.array([r[4] for r in rows], dtype=float)
    p0 = np.array([r[5] if r[5] is not None else floor for r in rows], dtype=float)
    # Negatives are a sample of the group's outings: weight them up to the true totals.
    w = np.ones(len(y))
    for is_test, total in ((False, totals[0]), (True, totals[1])):
        neg = (~y.astype(bool)) & (test == is_test)
        pos = int(((y == 1) & (test == is_test)).sum())
        if neg.sum():
            w[neg] = max(total - pos, 1) / neg.sum()
    train, held = ~test, test
    report.n_train, report.n_test = int(train.sum()), int(held.sum())
    report.n_pos_test = int(y[held].sum())
    if y[train].sum() < min_pos or report.n_pos_test < min_pos:
        report.notes.append(f"too few detections (need {min_pos} in training and test)")
        return report
    sig = {"nowcast.log_detections": np.log1p(k), "nowcast.log_effort": np.log1p(n)}

    def sub(mask):
        return {s: v[mask] for s, v in sig.items()}

    off = logit(p0)
    m0 = OffsetLogit([]).fit(sub(train), y[train], off[train], w[train])
    m2 = OffsetLogit(list(NOWCAST_TERMS)).fit(sub(train), y[train], off[train], w[train])
    yt, wt = y[held], w[held]
    p0r = m0.predict(sub(held), off[held])
    p2 = m2.predict(sub(held), off[held])
    persistence = (k[held] + 5 * p0r) / (n[held] + 5)
    blocks = np.array([d.toordinal() for d, h in zip(days_, held, strict=True) if h])
    b_ref, b2 = brier(yt, p0r, wt), brier(yt, p2, wt)

    def skill(idx):
        ref = brier(yt[idx], p0r[idx], wt[idx])
        return 1 - brier(yt[idx], p2[idx], wt[idx]) / ref if ref > 0 else 0.0

    ci = block_bootstrap(blocks, skill, reps=reps, seed=seed)
    skill_all = 1 - b2 / b_ref if b_ref > 0 else 0.0
    report.brier_persistence = brier(yt, persistence, wt)
    report.brier_level0 = brier(yt, p0[held], wt)
    passes = bool(ci[0] > 0 and skill_all >= min_skill and b2 < report.brier_persistence)
    report.levels = [LevelResult(2, len(yt), int(yt.sum()), b_ref, b2, skill_all, ci, passes)]
    report.models = {2: m2}
    return report


def run_nowcasts(
    conn: duckdb.DuckDBPyConnection,
    *,
    region_id: str,
    bbox: tuple[float, float, float, float],
    split: datetime,
    config: BaselineConfig | None = None,
    registry: DatasetRegistry | None = None,
    exclude: set[str] = frozenset(),  # type: ignore[assignment]
    days: int = 14,
    min_detections: int = 200,
    max_taxa: int = 300,
    pool: int = 40_000,
    min_pos: int = 20,
    min_skill: float = 0.005,
    reps: int = 100,
    log=lambda _m: None,
) -> NowcastSummary:
    """Fit and gate nowcast-only Level 2 for OPEN taxa in shared-effort groups."""
    cfg = config or BaselineConfig()
    ensure_schema(conn)
    bt = f"{region_id}__conditions"
    cutoff = conn.execute("SELECT cutoff FROM prior_builds WHERE region_id = ?", [bt]).fetchone()
    if cutoff is None or cutoff[0] != naive_utc(split):
        build_baseline(conn, region_id=bt, bbox=bbox, config=cfg, cutoff=split, registry=registry)
    create_training_view(conn, cfg, bbox, registry, name="_all")
    surveys = ", ".join(f"'{c}'" for c in SURVEY_CLASSES)
    candidates = conn.execute(
        f"""
        SELECT p.taxon_id, p.group_id FROM prior_taxa p
        JOIN tiers t ON t.region_id = ? AND t.taxon_id = p.taxon_id AND t.tier = 0
        WHERE p.region_id = ? AND p.effort_class NOT IN ({surveys}) AND p.n_visits >= ?
        ORDER BY p.n_visits DESC
        """,
        [region_id, region_id, min_detections],
    ).fetchall()
    candidates = [(t, g) for t, g in candidates if t not in exclude][:max_taxa]
    summary = NowcastSummary(best=[])
    split_d = naive_utc(split).date()
    now = naive_utc(utcnow())
    by_group: dict[str, list[str]] = {}
    for t, g in candidates:
        by_group.setdefault(g, []).append(t)
    for group_id, taxa in by_group.items():
        if split_egroup(group_id)[1] in SURVEY_CLASSES:
            continue
        totals = _group_tables(conn, group_id, split_d, days, pool, seed=7)
        log(f"nowcast: {group_id}: {len(taxa)} taxa, outings {totals}")
        for taxon_id in taxa:
            report = evaluate_nowcast(
                conn,
                bt=bt,
                taxon_id=taxon_id,
                group_id=group_id,
                totals=totals,
                cfg=cfg,
                days=days,
                min_pos=min_pos,
                min_skill=min_skill,
                reps=reps,
            )
            if not report.levels:
                summary.skipped += 1
                continue
            summary.fitted += 1
            _persist(conn, region_id, split, now, report)
            level = report.levels[0]
            if level.passes:
                summary.passing += 1
                summary.best.append((taxon_id, group_id, round(level.skill, 4)))
    summary.best = sorted(summary.best, key=lambda x: -x[2])[:20]
    return summary
