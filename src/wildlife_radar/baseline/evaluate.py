"""Backtest the Level-0 baseline: train before a split date, score visits after it.

For each taxon, every held-out visit by an observer of its group is a trial: did that visit
record the taxon? The baseline's estimate for the visit's cell and week (falling back to the
parent, then context cell where training data had no effort) is compared with a **range-only**
reference — the taxon's annual regional rate inside its range mask, ~0 outside — i.e. the map a
Level-0 baseline must beat to be worth showing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import duckdb

from wildlife_radar.baseline.builder import BaselineConfig, build_baseline, clear_region
from wildlife_radar.baseline.estimate import estimate_query
from wildlife_radar.core.time import utcnow
from wildlife_radar.storage.observations import naive_utc

GATES_SCHEMA = """
CREATE TABLE IF NOT EXISTS baseline_gates (
    region_id VARCHAR, taxon_id VARCHAR, n_test BIGINT, n_pos BIGINT,
    brier DOUBLE, brier_ref DOUBLE, bss DOUBLE, passes BOOLEAN,
    split TIMESTAMP, evaluated_at TIMESTAMP
)
"""


@dataclass(frozen=True)
class TaxonScore:
    taxon_id: str
    n_test: int
    n_pos: int
    brier: float
    brier_ref: float
    bss: float
    passes: bool


def backtest_baseline(
    conn: duckdb.DuckDBPyConnection,
    *,
    region_id: str,
    bbox: tuple[float, float, float, float],
    split: datetime,
    end: datetime | None = None,
    config: BaselineConfig | None = None,
    min_positives: int = 5,
    floor: float = 1e-4,
    max_test_visits: int = 50_000,
) -> list[TaxonScore]:
    cfg = config or BaselineConfig()
    bt = f"{region_id}__backtest"
    build_baseline(conn, region_id=bt, bbox=bbox, config=cfg, cutoff=split)
    lon_min, lat_min, lon_max, lat_max = bbox
    split_n = naive_utc(split)
    end_n = naive_utc(end) if end else None
    R, P1, P2 = cfg.res, cfg.parent_res, cfg.context_res

    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _test AS
        SELECT * FROM observations
        WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
          AND week IS NOT NULL AND group_id IS NOT NULL AND visit_key IS NOT NULL
          AND cell_r{R} IS NOT NULL AND time_start >= ?
          AND (?::TIMESTAMP IS NULL OR time_start < ?::TIMESTAMP)
          AND {cfg.basis_filter()}
        """,
        [lat_min, lat_max, lon_min, lon_max, split_n, end_n, end_n],
    )
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _tv AS
        SELECT DISTINCT group_id, visit_key, cell_r{R} AS c, cell_r{P1} AS c1,
            cell_r{P2} AS c2, week
        FROM _test
        """
    )
    n_visits = conn.execute("SELECT count(*) FROM _tv").fetchone()[0]
    if n_visits > max_test_visits:
        conn.execute(
            f"CREATE OR REPLACE TEMP TABLE _tv AS SELECT * FROM _tv "
            f"USING SAMPLE reservoir({int(max_test_visits)} ROWS) REPEATABLE (42)"
        )
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _th AS
        SELECT DISTINCT taxon_id, visit_key FROM _test
        WHERE taxon_id IS NOT NULL
          AND (outcome IN ('detected', 'presence_only') OR (outcome = 'count' AND count > 0))
        """
    )
    for name, level, col in (
        ("_e0", "cell", "c"),
        ("_e1", "parent", "c1"),
        ("_e2", "context", "c2"),
    ):
        sql, params = estimate_query(
            bt, level, cfg.shrinkage, cells_subquery=f"SELECT DISTINCT {col} FROM _tv"
        )
        conn.execute(f"CREATE OR REPLACE TEMP TABLE {name} AS {sql}", params)

    rows = conn.execute(
        """
        WITH trials AS (
            SELECT t.taxon_id,
                (h.visit_key IS NOT NULL)::INTEGER AS y,
                coalesce(e0.p, e1.p, e2.p,
                    CASE WHEN m.context_cell IS NOT NULL THEN t.annual_rate ELSE ? END) AS p,
                CASE WHEN m.context_cell IS NOT NULL THEN t.annual_rate ELSE ? END AS p_ref
            FROM prior_taxa t
            JOIN _tv v ON v.group_id = t.group_id
            LEFT JOIN _th h ON h.taxon_id = t.taxon_id AND h.visit_key = v.visit_key
            LEFT JOIN prior_mask m
                ON m.region_id = t.region_id AND m.taxon_id = t.taxon_id AND m.context_cell = v.c2
            LEFT JOIN _e0 e0 ON e0.taxon_id = t.taxon_id AND e0.cell = v.c AND e0.week = v.week
            LEFT JOIN _e1 e1 ON e1.taxon_id = t.taxon_id AND e1.cell = v.c1 AND e1.week = v.week
            LEFT JOIN _e2 e2 ON e2.taxon_id = t.taxon_id AND e2.cell = v.c2 AND e2.week = v.week
            WHERE t.region_id = ?
        )
        SELECT taxon_id, count(*) AS n, sum(y) AS pos,
               avg((p - y) ^ 2) AS brier, avg((p_ref - y) ^ 2) AS brier_ref
        FROM trials GROUP BY taxon_id ORDER BY pos DESC
        """,
        [floor, floor, bt],
    ).fetchall()

    scores = []
    for taxon_id, n, pos, brier, brier_ref in rows:
        bss = 1 - brier / brier_ref if brier_ref > 0 else 0.0
        scores.append(
            TaxonScore(
                taxon_id=taxon_id,
                n_test=int(n),
                n_pos=int(pos),
                brier=float(brier),
                brier_ref=float(brier_ref),
                bss=float(bss),
                passes=bool(pos >= min_positives and bss > 0),
            )
        )

    conn.execute(GATES_SCHEMA)
    conn.execute("DELETE FROM baseline_gates WHERE region_id = ?", [region_id])
    evaluated_at = naive_utc(utcnow())
    if scores:
        conn.executemany(
            "INSERT INTO baseline_gates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    region_id,
                    s.taxon_id,
                    s.n_test,
                    s.n_pos,
                    s.brier,
                    s.brier_ref,
                    s.bss,
                    s.passes,
                    split_n,
                    evaluated_at,
                )
                for s in scores
            ],
        )
    clear_region(conn, bt)
    for tmp in ("_test", "_tv", "_th", "_e0", "_e1", "_e2"):
        conn.execute(f"DROP TABLE IF EXISTS {tmp}")
    return scores
