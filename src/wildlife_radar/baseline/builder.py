"""Level-0 baseline: a seasonal × spatial prior for every species with enough records.

Estimand (Level 0): the probability that a *typical recorded visit* — one observer, one day,
one place — by someone who reports this taxon group records the species, per cell and week.

Presence-only records mostly measure where observers go. We correct for that with a
**target-group background**: the denominator is visits by observers of the same taxon group
(birds, fishes, mammals…), so heavily visited places don't look species-rich just because
they're busy. Then:

1. Counts are smoothed over weeks with a circular Gaussian kernel (seasons are smooth).
2. Rates are shrunk hierarchically — cell → parent cell → context cell → region → the species'
   annual regional rate — with Beta-Binomial pseudo-counts, so sparse cells borrow strength
   from their surroundings instead of reporting 0 % or 100 % (see ``estimate.py``).
3. Each estimate keeps ``lift`` (vs. the ~100 km context: "special to here") and
   ``seasonal_index`` (vs. the place's annual mean: "peaking now").

Storage is *sparse sufficient statistics*, not a dense species × cell × week tensor:
smoothed effort per group/level/cell/week, smoothed detections per taxon/level/cell/week (only
where non-zero), the cells with effort, and each taxon's plausible-range mask. Probabilities are
computed on demand for just the cells a query needs, so storage scales with the data rather than
with taxa × cells.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime

import duckdb
import h3

from wildlife_radar.core.time import utcnow
from wildlife_radar.storage.observations import CELL_RESOLUTIONS, VISIT_RES, naive_utc

#: Level codes used in prior_effort / prior_hits.
LEVEL_CELL, LEVEL_PARENT, LEVEL_CONTEXT, LEVEL_REGION = 0, 1, 2, 9

PRIOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS prior_effort (
    region_id VARCHAR, group_id VARCHAR, level SMALLINT, cell VARCHAR, week SMALLINT, n DOUBLE
);
CREATE TABLE IF NOT EXISTS prior_hits (
    region_id VARCHAR, taxon_id VARCHAR, level SMALLINT, cell VARCHAR, week SMALLINT, k DOUBLE
);
CREATE TABLE IF NOT EXISTS prior_cells (
    region_id VARCHAR, group_id VARCHAR, cell VARCHAR, parent_cell VARCHAR, context_cell VARCHAR
);
CREATE TABLE IF NOT EXISTS prior_taxa (
    region_id VARCHAR, taxon_id VARCHAR, group_id VARCHAR, scientific_name VARCHAR,
    n_visits BIGINT, annual_rate DOUBLE, inat_taxon_id VARCHAR, gbif_taxon_key VARCHAR
);
CREATE TABLE IF NOT EXISTS prior_mask (region_id VARCHAR, taxon_id VARCHAR, context_cell VARCHAR);
CREATE TABLE IF NOT EXISTS prior_licenses (
    region_id VARCHAR, group_id VARCHAR, source_id VARCHAR, license_id VARCHAR, n BIGINT
);
CREATE TABLE IF NOT EXISTS prior_builds (
    region_id VARCHAR PRIMARY KEY, model_version VARCHAR, built_at TIMESTAMP, cutoff TIMESTAMP,
    res SMALLINT, parent_res SMALLINT, context_res SMALLINT, shrinkage DOUBLE, config VARCHAR
);
"""
PRIOR_TABLES = (
    "prior_effort",
    "prior_hits",
    "prior_cells",
    "prior_taxa",
    "prior_mask",
    "prior_licenses",
    "prior_builds",
)


@dataclass(frozen=True)
class BaselineConfig:
    res: int = 6
    parent_res: int = 5
    context_res: int = 3
    shrinkage: float = 5.0
    """Pseudo-visits pulling each level toward the next coarser one."""
    kernel_sigma_weeks: float = 1.5
    kernel_half_width: int = 3
    min_visits: int = 5
    """Minimum detection visits region-wide for a taxon to get a baseline."""
    model_version: str = "baseline-v0"

    def __post_init__(self) -> None:
        if not (self.context_res < self.parent_res < self.res <= VISIT_RES):
            raise ValueError("need context_res < parent_res < res <= VISIT_RES")
        for r in (self.res, self.parent_res, self.context_res):
            if r not in CELL_RESOLUTIONS:
                raise ValueError(f"resolution {r} is not stored (have {CELL_RESOLUTIONS})")

    def kernel(self) -> list[tuple[int, float]]:
        k = self.kernel_half_width
        raw = [(d, math.exp(-0.5 * (d / self.kernel_sigma_weeks) ** 2)) for d in range(-k, k + 1)]
        total = sum(w for _, w in raw)
        return [(d, w / total) for d, w in raw]


@dataclass
class BaselineReport:
    region_id: str
    taxa: int = 0
    visits: int = 0
    cells: int = 0
    effort_rows: int = 0
    hit_rows: int = 0
    groups: dict[str, int] = field(default_factory=dict)
    built_at: datetime | None = None


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(PRIOR_SCHEMA)


def clear_region(conn: duckdb.DuckDBPyConnection, region_id: str) -> None:
    for table in PRIOR_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE region_id = ?", [region_id])


def build_baseline(
    conn: duckdb.DuckDBPyConnection,
    *,
    region_id: str,
    bbox: tuple[float, float, float, float],
    config: BaselineConfig | None = None,
    cutoff: datetime | None = None,
) -> BaselineReport:
    """(Re)build the Level-0 statistics for a region from the ``observations`` table.

    ``cutoff`` restricts training to observations that started before it (for backtests).
    """
    cfg = config or BaselineConfig()
    ensure_schema(conn)
    lon_min, lat_min, lon_max, lat_max = bbox
    R, P1, P2 = cfg.res, cfg.parent_res, cfg.context_res
    cutoff_naive = naive_utc(cutoff) if cutoff else None

    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _obs AS
        SELECT * FROM observations
        WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
          AND week IS NOT NULL AND group_id IS NOT NULL AND visit_key IS NOT NULL
          AND cell_r{R} IS NOT NULL
          AND (?::TIMESTAMP IS NULL OR time_start < ?::TIMESTAMP)
        """,
        [lat_min, lat_max, lon_min, lon_max, cutoff_naive, cutoff_naive],
    )
    cols = f"cell_r{R} AS c, cell_r{P1} AS c1, cell_r{P2} AS c2, week"
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _d AS
        SELECT DISTINCT taxon_id, group_id, visit_key, {cols} FROM _obs
        WHERE taxon_id IS NOT NULL
          AND (outcome IN ('detected', 'presence_only') OR (outcome = 'count' AND count > 0))
        """
    )
    # A taxon's group is its most common group (sources may disagree, e.g. iNat vs GBIF).
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _taxa AS
        SELECT taxon_id, arg_max(group_id, n) AS group_id, sum(n) AS n_visits
        FROM (SELECT taxon_id, group_id, count(*) AS n FROM _d GROUP BY ALL)
        GROUP BY taxon_id HAVING sum(n) >= ?
        """,
        [cfg.min_visits],
    )
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _d2 AS
        SELECT DISTINCT d.taxon_id, t.group_id, d.visit_key, d.c, d.c1, d.c2, d.week
        FROM _d d JOIN _taxa t USING (taxon_id)
        """
    )
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _v AS
        SELECT DISTINCT group_id, visit_key, c, c1, c2, week FROM (
            SELECT group_id, visit_key, {cols} FROM _obs
            UNION ALL SELECT group_id, visit_key, c, c1, c2, week FROM _d2
        )
        """
    )
    conn.execute("CREATE OR REPLACE TEMP TABLE _k (d INTEGER, w DOUBLE)")
    conn.executemany("INSERT INTO _k VALUES (?, ?)", cfg.kernel())

    built_at = naive_utc(utcnow())
    clear_region(conn, region_id)

    week_expr = "((week - 1 + d + 52) % 52) + 1"
    for level, col in (
        (LEVEL_CELL, "c"),
        (LEVEL_PARENT, "c1"),
        (LEVEL_CONTEXT, "c2"),
        (LEVEL_REGION, "NULL"),
    ):
        conn.execute(
            f"""
            INSERT INTO prior_effort
            SELECT ?, group_id, ?, {col}, {week_expr}, SUM(w)
            FROM _v CROSS JOIN _k GROUP BY ALL
            """,
            [region_id, level],
        )
        conn.execute(
            f"""
            INSERT INTO prior_hits
            SELECT ?, taxon_id, ?, {col}, {week_expr}, SUM(w)
            FROM _d2 CROSS JOIN _k GROUP BY ALL
            """,
            [region_id, level],
        )
    conn.execute(
        "INSERT INTO prior_cells SELECT DISTINCT ?, group_id, c, c1, c2 FROM _v", [region_id]
    )
    conn.execute(
        """
        INSERT INTO prior_taxa
        SELECT ?, t.taxon_id, t.group_id, n.name, t.n_visits, t.n_visits / gv.n,
               n.inat_id, n.gbif_key
        FROM _taxa t
        JOIN (SELECT group_id, count(*) AS n FROM _v GROUP BY ALL) gv USING (group_id)
        LEFT JOIN (
            SELECT taxon_id,
                   mode(taxon_name) AS name,
                   mode(taxon_source_id) FILTER (WHERE taxon_scheme = 'inaturalist') AS inat_id,
                   mode(taxon_source_id) FILTER (WHERE taxon_scheme = 'gbif') AS gbif_key
            FROM _obs WHERE taxon_id IS NOT NULL GROUP BY taxon_id
        ) n USING (taxon_id)
        """,
        [region_id],
    )

    # Plausible range: context cells with records, plus one ring of neighbors.
    detected = conn.execute("SELECT DISTINCT taxon_id, c2 FROM _d2").fetchall()
    mask = sorted({(region_id, t, n) for t, c2 in detected for n in h3.grid_disk(c2, 1)})
    if mask:
        conn.executemany("INSERT INTO prior_mask VALUES (?, ?, ?)", mask)
    conn.execute(
        "INSERT INTO prior_licenses "
        "SELECT ?, group_id, source_id, license_id, count(*) FROM _obs GROUP BY ALL",
        [region_id],
    )
    conn.execute(
        "INSERT INTO prior_builds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            region_id,
            cfg.model_version,
            built_at,
            cutoff_naive,
            R,
            P1,
            P2,
            cfg.shrinkage,
            repr(asdict(cfg)),
        ],
    )

    def scalar(sql: str) -> int:
        return conn.execute(sql, [region_id]).fetchone()[0]

    report = BaselineReport(
        region_id=region_id,
        built_at=built_at,
        taxa=scalar("SELECT count(*) FROM prior_taxa WHERE region_id = ?"),
        cells=scalar("SELECT count(DISTINCT cell) FROM prior_cells WHERE region_id = ?"),
        effort_rows=scalar("SELECT count(*) FROM prior_effort WHERE region_id = ?"),
        hit_rows=scalar("SELECT count(*) FROM prior_hits WHERE region_id = ?"),
    )
    report.visits = conn.execute("SELECT count(*) FROM _v").fetchone()[0]
    report.groups = dict(conn.execute("SELECT group_id, count(*) FROM _taxa GROUP BY 1").fetchall())
    for tmp in ("_obs", "_d", "_taxa", "_d2", "_v", "_k"):
        conn.execute(f"DROP TABLE IF EXISTS {tmp}")
    return report
