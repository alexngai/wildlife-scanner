"""Backtest the Level-0 baseline: train before a split date, score held-out data after it.

Trials, per taxon and effort group:

- outing-based groups: every held-out outing of the group — did it record the taxon?
- survey groups: every held-out present/absent survey record of the taxon.

The baseline's estimate for the trial's cell and week (falling back to the parent, then context
cell where training had no effort) is compared with a **range-only** reference — the taxon's
annual regional rate inside its range mask, ~0 outside — i.e. the map a Level-0 baseline must
beat to be worth showing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import duckdb

from wildlife_scanner.baseline.builder import (
    BaselineConfig,
    build_baseline,
    clear_region,
    create_training_view,
    table_columns,
)
from wildlife_scanner.baseline.effort import SURVEY_CLASSES, DatasetRegistry
from wildlife_scanner.baseline.estimate import estimate_query
from wildlife_scanner.core.time import utcnow
from wildlife_scanner.storage.observations import naive_utc

GATES_COLUMNS = (
    "region_id VARCHAR, taxon_id VARCHAR, group_id VARCHAR, n_test BIGINT, n_pos BIGINT, "
    "brier DOUBLE, brier_ref DOUBLE, bss DOUBLE, passes BOOLEAN, split TIMESTAMP, "
    "evaluated_at TIMESTAMP"
)


@dataclass(frozen=True)
class TaxonScore:
    taxon_id: str
    group_id: str
    n_test: int
    n_pos: int
    brier: float
    brier_ref: float
    bss: float
    passes: bool


def ensure_gates_schema(conn: duckdb.DuckDBPyConnection) -> None:
    expected = [c.strip().split()[0] for c in GATES_COLUMNS.split(",")]
    existing = table_columns(conn, "baseline_gates")
    if existing and existing != expected:
        conn.execute("DROP TABLE baseline_gates")
    conn.execute(f"CREATE TABLE IF NOT EXISTS baseline_gates ({GATES_COLUMNS})")


def backtest_baseline(
    conn: duckdb.DuckDBPyConnection,
    *,
    region_id: str,
    bbox: tuple[float, float, float, float],
    split: datetime,
    end: datetime | None = None,
    config: BaselineConfig | None = None,
    registry: DatasetRegistry | None = None,
    min_positives: int = 5,
    floor: float = 1e-4,
    max_test_visits: int = 50_000,
    max_test_trials: int = 200_000,
    max_group_trials: int = 5_000_000,
    groups: list[str] | None = None,
) -> list[TaxonScore]:
    """``groups`` restricts scoring to these effort groups (e.g. survey programs whose data end
    earlier need their own split); gates of other groups are left untouched."""
    cfg = config or BaselineConfig()
    bt = f"{region_id}__backtest"
    build_baseline(conn, region_id=bt, bbox=bbox, config=cfg, cutoff=split, registry=registry)
    create_training_view(conn, cfg, bbox, registry, name="_test", after=split, before=end)
    surveys = ", ".join(f"'{c}'" for c in SURVEY_CLASSES)

    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _tv AS
        SELECT DISTINCT egroup, visit_key, c, c1, c2, week FROM _test
        WHERE effort_class NOT IN ({surveys})
        """
    )
    if conn.execute("SELECT count(*) FROM _tv").fetchone()[0] > max_test_visits:
        conn.execute(
            f"CREATE OR REPLACE TEMP TABLE _tv AS SELECT * FROM _tv "
            f"USING SAMPLE reservoir({int(max_test_visits)} ROWS) REPEATABLE (42)"
        )
    # Every taxon of a group is scored on every test visit of that group, so a group's
    # trials are taxa × visits: San Diego's 1,772 plant taxa on all their visits spilled more
    # than 17 GB. Cap each group at ``max_group_trials`` by sampling its visits (a stable
    # hash, so reruns score the same visits).
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _tv AS
        WITH n AS (SELECT group_id, count(*) AS taxa FROM prior_taxa WHERE region_id = ?
                   GROUP BY 1)
        SELECT v.* FROM _tv v LEFT JOIN n ON n.group_id = v.egroup
        QUALIFY row_number() OVER (PARTITION BY v.egroup ORDER BY hash(v.visit_key))
            <= greatest(1, ? // coalesce(n.taxa, 1))
        """,
        [bt, int(max_group_trials)],
    )
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _th AS
        SELECT DISTINCT taxon_id, egroup, visit_key FROM _test
        WHERE taxon_id IS NOT NULL AND detected AND effort_class NOT IN ({surveys})
        """
    )
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _ts AS
        SELECT taxon_id, egroup, c, c1, c2, week, detected::INTEGER AS y FROM _test
        WHERE taxon_id IS NOT NULL AND effort_class IN ({surveys})
        """
    )
    if conn.execute("SELECT count(*) FROM _ts").fetchone()[0] > max_test_trials:
        conn.execute(
            f"CREATE OR REPLACE TEMP TABLE _ts AS SELECT * FROM _ts "
            f"USING SAMPLE reservoir({int(max_test_trials)} ROWS) REPEATABLE (42)"
        )
    group_filter = f"AND t.group_id IN ({', '.join('?' * len(groups))})" if groups else ""
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _trials AS
        SELECT t.taxon_id, t.group_id, v.c, v.c1, v.c2, v.week,
            (h.visit_key IS NOT NULL)::INTEGER AS y
        FROM prior_taxa t
        JOIN _tv v ON v.egroup = t.group_id
        LEFT JOIN _th h
            ON h.taxon_id = t.taxon_id AND h.egroup = t.group_id AND h.visit_key = v.visit_key
        WHERE t.region_id = ? {group_filter}
        UNION ALL
        SELECT t.taxon_id, t.group_id, s.c, s.c1, s.c2, s.week, s.y
        FROM prior_taxa t JOIN _ts s ON s.taxon_id = t.taxon_id AND s.egroup = t.group_id
        WHERE t.region_id = ? {group_filter}
        """,
        [bt, *(groups or []), bt, *(groups or [])],
    )
    for name, level, col in (
        ("_e0", "cell", "c"),
        ("_e1", "parent", "c1"),
        ("_e2", "context", "c2"),
    ):
        sql, params = estimate_query(
            bt, level, cfg.shrinkage, cells_subquery=f"SELECT DISTINCT {col} FROM _trials"
        )
        conn.execute(f"CREATE OR REPLACE TEMP TABLE {name} AS {sql}", params)

    rows = conn.execute(
        """
        WITH scored AS (
            SELECT tr.taxon_id, tr.group_id, tr.y,
                coalesce(e0.p, e1.p, e2.p,
                    CASE WHEN m.context_cell IS NOT NULL THEN t.annual_rate ELSE ? END) AS p,
                CASE WHEN m.context_cell IS NOT NULL THEN t.annual_rate ELSE ? END AS p_ref
            FROM _trials tr
            JOIN prior_taxa t ON t.region_id = ? AND t.taxon_id = tr.taxon_id
                AND t.group_id = tr.group_id
            LEFT JOIN prior_mask m
                ON m.region_id = ? AND m.taxon_id = tr.taxon_id AND m.context_cell = tr.c2
            LEFT JOIN _e0 e0 ON e0.taxon_id = tr.taxon_id AND e0.group_id = tr.group_id
                AND e0.cell = tr.c AND e0.week = tr.week
            LEFT JOIN _e1 e1 ON e1.taxon_id = tr.taxon_id AND e1.group_id = tr.group_id
                AND e1.cell = tr.c1 AND e1.week = tr.week
            LEFT JOIN _e2 e2 ON e2.taxon_id = tr.taxon_id AND e2.group_id = tr.group_id
                AND e2.cell = tr.c2 AND e2.week = tr.week
        )
        SELECT taxon_id, group_id, count(*) AS n, sum(y) AS pos,
               avg((p - y) ^ 2) AS brier, avg((p_ref - y) ^ 2) AS brier_ref
        FROM scored GROUP BY ALL ORDER BY pos DESC
        """,
        [floor, floor, bt, bt],
    ).fetchall()

    scores = []
    for taxon_id, group_id, n, pos, brier, brier_ref in rows:
        bss = 1 - brier / brier_ref if brier_ref > 0 else 0.0
        scores.append(
            TaxonScore(
                taxon_id=taxon_id,
                group_id=group_id,
                n_test=int(n),
                n_pos=int(pos),
                brier=float(brier),
                brier_ref=float(brier_ref),
                bss=float(bss),
                passes=bool(pos >= min_positives and bss > 0),
            )
        )

    ensure_gates_schema(conn)
    if groups:
        conn.execute(
            f"DELETE FROM baseline_gates WHERE region_id = ? "
            f"AND group_id IN ({', '.join('?' * len(groups))})",
            [region_id, *groups],
        )
    else:
        conn.execute("DELETE FROM baseline_gates WHERE region_id = ?", [region_id])
    evaluated_at = naive_utc(utcnow())
    if scores:
        conn.executemany(
            "INSERT INTO baseline_gates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    region_id,
                    s.taxon_id,
                    s.group_id,
                    s.n_test,
                    s.n_pos,
                    s.brier,
                    s.brier_ref,
                    s.bss,
                    s.passes,
                    naive_utc(split),
                    evaluated_at,
                )
                for s in scores
            ],
        )
    clear_region(conn, bt)
    for tmp in ("_test", "_tv", "_th", "_ts", "_trials", "_e0", "_e1", "_e2"):
        conn.execute(f"DROP TABLE IF EXISTS {tmp}")
    return scores
