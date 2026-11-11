"""On-demand Level-0 estimates from the sparse statistics written by ``build_baseline``.

Hierarchical Beta-Binomial shrinkage with ``A`` pseudo-visits per level::

    p_region  = (k_region  + A · annual_rate) / (n_region  + A)
    p_context = (k_context + A · p_region)    / (n_context + A)
    p_parent  = (k_parent  + A · p_context)   / (n_parent  + A)
    p_cell    = (k_cell    + A · p_parent)    / (n_cell    + A)

An estimate at a level stops the cascade there, so a coarse policy tier is answered with a
genuinely coarse estimate (not an average of fine ones).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import duckdb

from wildlife_radar.baseline.builder import (
    LEVEL_CELL,
    LEVEL_CONTEXT,
    LEVEL_PARENT,
    LEVEL_REGION,
)

Level = Literal["cell", "parent", "context"]
LEVEL_COLUMN = {"cell": "cell", "parent": "parent_cell", "context": "context_cell"}


@dataclass(frozen=True)
class Estimate:
    taxon_id: str
    cell: str
    week: int
    p: float
    p_context: float
    p_region: float
    lift: float | None
    seasonal_index: float | None
    n_eff: float
    n_region: float


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join('?' * len(values))})"


def estimate_query(
    region_id: str,
    level: Level,
    shrinkage: float,
    *,
    taxon_ids: Sequence[str] | None = None,
    cells: Sequence[str] | None = None,
    cells_subquery: str | None = None,
    weeks: Sequence[int] | None = None,
) -> tuple[str, list]:
    """SQL (and parameters) yielding Estimate-shaped rows for one level."""
    col = LEVEL_COLUMN[level]
    A = float(shrinkage)
    params: list = [region_id]
    where = ["t.region_id = ?"]
    if taxon_ids is not None:
        where.append(_in("t.taxon_id", taxon_ids))
        params.extend(taxon_ids)
    if cells is not None:
        where.append(_in(f"cl.{col}", cells))
        params.extend(cells)
    if cells_subquery is not None:
        where.append(f"cl.{col} IN ({cells_subquery})")

    parent_select = "cl.parent_cell AS c1," if level == "cell" else ""
    frame = f"""
        SELECT DISTINCT t.taxon_id, t.group_id, t.annual_rate AS g,
            cl.{col} AS x, {parent_select} cl.context_cell AS c2
        FROM prior_taxa t
        JOIN prior_mask m ON m.region_id = t.region_id AND m.taxon_id = t.taxon_id
        JOIN prior_cells cl ON cl.region_id = t.region_id AND cl.group_id = t.group_id
            AND cl.context_cell = m.context_cell
        WHERE {" AND ".join(where)}
    """

    def join(alias: str, lvl: int, cell_expr: str | None) -> str:
        cell_cond_e = f"AND e{alias}.cell = {cell_expr}" if cell_expr else ""
        cell_cond_h = f"AND h{alias}.cell = {cell_expr}" if cell_expr else ""
        return f"""
            LEFT JOIN prior_effort e{alias} ON e{alias}.region_id = ? AND e{alias}.level = {lvl}
                AND e{alias}.group_id = f.group_id AND e{alias}.week = f.week {cell_cond_e}
            LEFT JOIN prior_hits h{alias} ON h{alias}.region_id = ? AND h{alias}.level = {lvl}
                AND h{alias}.taxon_id = f.taxon_id AND h{alias}.week = f.week {cell_cond_h}
        """

    joins = [join("r", LEVEL_REGION, None), join("2", LEVEL_CONTEXT, "f.c2")]
    sel = [
        "coalesce(hr.k, 0) AS kr, coalesce(er.n, 0) AS nr",
        "coalesce(h2.k, 0) AS k2, coalesce(e2.n, 0) AS n2",
    ]
    if level in ("cell", "parent"):
        joins.append(join("1", LEVEL_PARENT, "f.c1" if level == "cell" else "f.x"))
        sel.append("coalesce(h1.k, 0) AS k1, coalesce(e1.n, 0) AS n1")
    if level == "cell":
        joins.append(join("0", LEVEL_CELL, "f.x"))
        sel.append("coalesce(h0.k, 0) AS k0, coalesce(e0.n, 0) AS n0")
    params.extend([region_id, region_id] * len(joins))

    stages = [
        f"a AS (SELECT *, (kr + {A} * g) / (nr + {A}) AS p_reg FROM j)",
        f"b AS (SELECT *, (k2 + {A} * p_reg) / (n2 + {A}) AS p2 FROM a)",
    ]
    if level == "context":
        final, n_eff, ref = "b", "n2", "p_reg"
        p_expr = "p2"
    elif level == "parent":
        stages.append(f"c AS (SELECT *, (k1 + {A} * p2) / (n1 + {A}) AS p1 FROM b)")
        final, n_eff, ref, p_expr = "c", "n1", "p2", "p1"
    else:
        stages.append(f"c AS (SELECT *, (k1 + {A} * p2) / (n1 + {A}) AS p1 FROM b)")
        stages.append(f"e AS (SELECT *, (k0 + {A} * p1) / (n0 + {A}) AS p0 FROM c)")
        final, n_eff, ref, p_expr = "e", "n0", "p2", "p0"

    week_filter = ""
    if weeks is not None:
        week_filter = f"WHERE {_in('week', weeks)}"
        week_params = list(weeks)
    else:
        week_params = []

    sql = f"""
        WITH frame AS (
            SELECT fr.*, w.range::SMALLINT AS week FROM ({frame}) fr CROSS JOIN range(1, 53) w
        ),
        j AS (
            SELECT f.*, {", ".join(sel)}
            FROM frame f {" ".join(joins)}
        ),
        {", ".join(stages)},
        out AS (
            SELECT taxon_id, x AS cell, week, {p_expr} AS p,
                p2 AS p_context, p_reg AS p_region,
                {p_expr} / nullif({ref}, 0) AS lift,
                {p_expr} / nullif(avg({p_expr}) OVER (PARTITION BY taxon_id, x), 0)
                    AS seasonal_index,
                {n_eff} AS n_eff, nr AS n_region
            FROM {final}
        )
        SELECT * FROM out {week_filter}
    """
    return sql, params + week_params


def estimate(
    conn: duckdb.DuckDBPyConnection,
    region_id: str,
    level: Level,
    shrinkage: float,
    **filters,
) -> list[Estimate]:
    sql, params = estimate_query(region_id, level, shrinkage, **filters)
    return [Estimate(*row) for row in conn.execute(sql, params).fetchall()]
