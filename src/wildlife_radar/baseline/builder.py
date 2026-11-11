"""Level-0 baseline: a seasonal × spatial prior for every species with enough records.

Estimates are made per **effort group** — taxon group × effort class (see ``effort.py``):

- *Outing-based* classes (checklists, casual sightings, sensors): the probability that a typical
  recorded outing — one observer, one day, one place — by someone who records this group
  records the species. Presence-only records mostly measure where observers go, so the
  denominator is the group's outings (a **target-group background**).
- *Survey* classes (dive, intertidal and other structured surveys that record absences): the
  probability that one survey unit detects the species — detections over the species' own
  present/absent trials.

Then, for both:

1. Counts are smoothed over weeks with a circular Gaussian kernel (seasons are smooth).
2. Rates are shrunk hierarchically — cell → parent cell → context cell → region → the species'
   annual regional rate — with Beta-Binomial pseudo-counts (see ``estimate.py``).
3. Estimates keep ``lift`` (vs. the ~100 km context: "special to here") and ``seasonal_index``
   (vs. the place's annual mean: "peaking now").

Storage is *sparse sufficient statistics*: smoothed effort per effort group (and per taxon for
survey groups), smoothed detections per taxon and effort group (only where non-zero), cells
with effort, and each taxon's plausible-range mask. Probabilities are computed on demand.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime

import duckdb
import h3

from wildlife_radar.baseline.effort import SURVEY_CLASSES, DatasetRegistry, create_dataset_classes
from wildlife_radar.core.time import utcnow
from wildlife_radar.storage.observations import CELL_RESOLUTIONS, VISIT_RES, naive_utc

#: Level codes used in prior_effort / prior_hits.
LEVEL_CELL, LEVEL_PARENT, LEVEL_CONTEXT, LEVEL_REGION = 0, 1, 2, 9

PRIOR_COLUMNS = {
    "prior_effort": (
        "region_id VARCHAR, group_id VARCHAR, taxon_id VARCHAR, level SMALLINT, cell VARCHAR, "
        "week SMALLINT, n DOUBLE"
    ),
    "prior_hits": (
        "region_id VARCHAR, taxon_id VARCHAR, group_id VARCHAR, level SMALLINT, cell VARCHAR, "
        "week SMALLINT, k DOUBLE"
    ),
    "prior_cells": (
        "region_id VARCHAR, group_id VARCHAR, cell VARCHAR, parent_cell VARCHAR, "
        "context_cell VARCHAR"
    ),
    "prior_taxa": (
        "region_id VARCHAR, taxon_id VARCHAR, group_id VARCHAR, taxon_group VARCHAR, "
        "effort_class VARCHAR, scientific_name VARCHAR, n_visits BIGINT, annual_rate DOUBLE, "
        "inat_taxon_id VARCHAR, gbif_taxon_key VARCHAR"
    ),
    "prior_mask": "region_id VARCHAR, taxon_id VARCHAR, context_cell VARCHAR",
    "prior_licenses": (
        "region_id VARCHAR, group_id VARCHAR, source_id VARCHAR, license_id VARCHAR, n BIGINT"
    ),
    "prior_builds": (
        "region_id VARCHAR PRIMARY KEY, model_version VARCHAR, built_at TIMESTAMP, "
        "cutoff TIMESTAMP, res SMALLINT, parent_res SMALLINT, context_res SMALLINT, "
        "shrinkage DOUBLE, config VARCHAR"
    ),
}
PRIOR_TABLES = tuple(PRIOR_COLUMNS)


@dataclass(frozen=True)
class BaselineConfig:
    res: int = 6
    parent_res: int = 5
    context_res: int = 3
    shrinkage: float = 5.0
    """Pseudo-trials pulling each level toward the next coarser one."""
    kernel_sigma_weeks: float = 1.5
    kernel_half_width: int = 3
    min_visits: int = 5
    """Minimum detections region-wide for a taxon to get a baseline in an effort group."""
    since_year: int | None = None
    """Ignore records before this year (land use, ranges and observer behavior change)."""
    exclude_basis: tuple[str, ...] = (
        "LIVING_SPECIMEN",
        "FOSSIL_SPECIMEN",
        "PRESERVED_SPECIMEN",
        "MATERIAL_CITATION",
        "MATERIAL_SAMPLE",
    )
    """Records that aren't evidence of encounterable wild presence (zoos and gardens, fossils,
    museum specimens, bulk barcoding samples) — and whose collecting isn't comparable effort."""
    exclude_licenses: tuple[str, ...] = ("ALL-RIGHTS-RESERVED", "UNKNOWN")
    """Records whose license doesn't allow publishing derived products (licensing.md §3)."""
    survey_flat_season: bool = True
    """Survey programs sample in a fixed season (and record campaign dates), so they can't
    inform seasonality: their counts are spread evenly over the year (a per-site annual rate)."""
    model_version: str = "baseline-v1"

    def __post_init__(self) -> None:
        if not (self.context_res < self.parent_res < self.res <= VISIT_RES):
            raise ValueError("need context_res < parent_res < res <= VISIT_RES")
        for r in (self.res, self.parent_res, self.context_res):
            if r not in CELL_RESOLUTIONS:
                raise ValueError(f"resolution {r} is not stored (have {CELL_RESOLUTIONS})")

    def record_filter(self) -> str:
        clauses = []
        if self.exclude_basis:
            quoted = ", ".join("'" + b.replace("'", "''") + "'" for b in self.exclude_basis)
            clauses.append(f"(basis_of_record IS NULL OR basis_of_record NOT IN ({quoted}))")
        if self.exclude_licenses:
            quoted = ", ".join("'" + b.replace("'", "''") + "'" for b in self.exclude_licenses)
            clauses.append(f"license_id NOT IN ({quoted})")
        return " AND ".join(clauses) or "TRUE"

    def flat_kernel(self) -> list[tuple[int, float]]:
        return [(d, 1 / 52) for d in range(-25, 27)]

    def kernel(self) -> list[tuple[int, float]]:
        k = self.kernel_half_width
        raw = [(d, math.exp(-0.5 * (d / self.kernel_sigma_weeks) ** 2)) for d in range(-k, k + 1)]
        total = sum(w for _, w in raw)
        return [(d, w / total) for d, w in raw]


@dataclass
class BaselineReport:
    region_id: str
    taxa: int = 0
    taxon_groups: int = 0
    visits: int = 0
    survey_trials: int = 0
    cells: int = 0
    effort_rows: int = 0
    hit_rows: int = 0
    groups: dict[str, int] = field(default_factory=dict)
    built_at: datetime | None = None


def table_columns(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Column names of a main-schema table, in order ([] if it doesn't exist)."""
    return [
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND table_schema = 'main' ORDER BY ordinal_position",
            [table],
        ).fetchall()
    ]


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the statistics tables, dropping derived tables with an outdated schema."""
    for table, columns in PRIOR_COLUMNS.items():
        expected = [c.strip().split()[0] for c in columns.split(",")]
        existing = table_columns(conn, table)
        if existing and existing != expected:
            conn.execute(f"DROP TABLE {table}")
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({columns})")


def clear_region(conn: duckdb.DuckDBPyConnection, region_id: str) -> None:
    for table in PRIOR_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE region_id = ?", [region_id])


def create_training_view(
    conn: duckdb.DuckDBPyConnection,
    cfg: BaselineConfig,
    bbox: tuple[float, float, float, float],
    registry: DatasetRegistry | None,
    *,
    name: str = "_obs",
    after: datetime | None = None,
    before: datetime | None = None,
) -> None:
    """Filtered records with effort class, effort group and cells, as temp table ``name``."""
    create_dataset_classes(conn, registry)
    lon_min, lat_min, lon_max, lat_max = bbox
    R, P1, P2 = cfg.res, cfg.parent_res, cfg.context_res
    surveys = ", ".join(f"'{c}'" for c in SURVEY_CLASSES)
    after_n = naive_utc(after) if after else None
    before_n = naive_utc(before) if before else None
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {name} AS
        WITH base AS (
            SELECT o.*, d.ds_id,
                -- Survey estimators need recorded absences for the taxon itself (programs may
                -- record absences for fishes but only presences for invertebrates).
                CASE WHEN d.effort_class IN ({surveys}) AND NOT bool_or(o.outcome = 'not_detected')
                        OVER (PARTITION BY d.ds_id, o.taxon_id)
                     THEN 'casual' ELSE d.effort_class END AS effort_class
            FROM observations o
            JOIN _dsclass d ON d.ds_id = coalesce(o.dataset_key, o.source_id)
            WHERE NOT d.excluded
              AND NOT EXISTS (SELECT 1 FROM _baddates x
                              WHERE x.ds_id = d.ds_id AND x.d = o.local_date)
              AND o.lat BETWEEN ? AND ? AND o.lon BETWEEN ? AND ?
              AND o.week IS NOT NULL AND o.group_id IS NOT NULL AND o.visit_key IS NOT NULL
              AND o.cell_r{R} IS NOT NULL
              AND (?::TIMESTAMP IS NULL OR o.time_start >= ?::TIMESTAMP)
              AND (?::TIMESTAMP IS NULL OR o.time_start < ?::TIMESTAMP)
              AND (?::INTEGER IS NULL OR year(o.local_date) >= ?::INTEGER)
              AND {cfg.record_filter()}
        ),
        tg AS (SELECT taxon_id, mode(group_id) AS taxon_group FROM base
               WHERE taxon_id IS NOT NULL GROUP BY 1)
        SELECT b.dedupe_key, b.taxon_id, b.taxon_name, b.taxon_scheme, b.taxon_source_id,
            b.source_id, b.license_id, b.outcome, b.count, b.visit_key, b.effort_class,
            coalesce(tg.taxon_group, b.group_id) AS taxon_group,
            coalesce(tg.taxon_group, b.group_id) || ':' || b.effort_class AS egroup,
            b.cell_r{R} AS c, b.cell_r{P1} AS c1, b.cell_r{P2} AS c2, b.week,
            (b.outcome IN ('detected', 'presence_only') OR (b.outcome = 'count' AND b.count > 0))
                AS detected
        FROM base b LEFT JOIN tg USING (taxon_id)
        """,
        [
            lat_min,
            lat_max,
            lon_min,
            lon_max,
            after_n,
            after_n,
            before_n,
            before_n,
            cfg.since_year,
            cfg.since_year,
        ],
    )


def build_baseline(
    conn: duckdb.DuckDBPyConnection,
    *,
    region_id: str,
    bbox: tuple[float, float, float, float],
    config: BaselineConfig | None = None,
    cutoff: datetime | None = None,
    registry: DatasetRegistry | None = None,
) -> BaselineReport:
    """(Re)build the Level-0 statistics for a region from the ``observations`` table.

    ``cutoff`` restricts training to observations that started before it (for backtests).
    """
    cfg = config or BaselineConfig()
    ensure_schema(conn)
    create_training_view(conn, cfg, bbox, registry, before=cutoff)
    surveys = ", ".join(f"'{c}'" for c in SURVEY_CLASSES)

    # Outing-based classes: detections and the group's outings.
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _d AS
        SELECT DISTINCT taxon_id, egroup, visit_key, c, c1, c2, week FROM _obs
        WHERE taxon_id IS NOT NULL AND detected AND effort_class NOT IN ({surveys})
        """
    )
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _v AS
        SELECT DISTINCT egroup, visit_key, c, c1, c2, week FROM _obs
        WHERE effort_class NOT IN ({surveys})
        """
    )
    # Survey classes: every present/absent record is a trial for its species.
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _t AS
        SELECT taxon_id, egroup, dedupe_key AS trial, c, c1, c2, week, detected FROM _obs
        WHERE taxon_id IS NOT NULL AND effort_class IN ({surveys})
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _taxa AS
        SELECT taxon_id, egroup, count(*) AS n_det FROM (
            SELECT taxon_id, egroup, visit_key AS unit FROM _d
            UNION ALL SELECT taxon_id, egroup, trial FROM _t WHERE detected
        ) GROUP BY ALL HAVING count(*) >= ?
        """,
        [cfg.min_visits],
    )
    conn.execute("CREATE OR REPLACE TEMP TABLE _k (d INTEGER, w DOUBLE)")
    conn.executemany("INSERT INTO _k VALUES (?, ?)", cfg.kernel())
    conn.execute("CREATE OR REPLACE TEMP TABLE _ks (d INTEGER, w DOUBLE)")
    conn.executemany(
        "INSERT INTO _ks VALUES (?, ?)",
        cfg.flat_kernel() if cfg.survey_flat_season else cfg.kernel(),
    )

    built_at = naive_utc(utcnow())
    clear_region(conn, region_id)
    week_expr = "((week - 1 + d + 52) % 52) + 1"
    for level, col in (
        (LEVEL_CELL, "c"),
        (LEVEL_PARENT, "c1"),
        (LEVEL_CONTEXT, "c2"),
        (LEVEL_REGION, "NULL"),
    ):
        # Shared effort: the group's outings (taxon_id NULL).
        conn.execute(
            f"""
            INSERT INTO prior_effort
            SELECT ?, egroup, NULL, ?, {col} AS cell, {week_expr} AS week, SUM(w)
            FROM _v CROSS JOIN _k
            WHERE egroup IN (SELECT egroup FROM _taxa)
            GROUP BY ALL ORDER BY egroup, cell, week
            """,
            [region_id, level],
        )
        # Survey effort: the species' own trials.
        conn.execute(
            f"""
            INSERT INTO prior_effort
            SELECT ?, t.egroup, t.taxon_id, ?, {col} AS cell, {week_expr} AS week, SUM(w)
            FROM _t t JOIN _taxa USING (taxon_id, egroup) CROSS JOIN _ks
            GROUP BY ALL ORDER BY t.egroup, cell, week
            """,
            [region_id, level],
        )
        for source, kernel in (
            ("SELECT taxon_id, egroup, c, c1, c2, week FROM _d", "_k"),
            ("SELECT taxon_id, egroup, c, c1, c2, week FROM _t WHERE detected", "_ks"),
        ):
            conn.execute(
                f"""
                INSERT INTO prior_hits
                SELECT ?, taxon_id, egroup, ?, {col} AS cell, {week_expr} AS week, SUM(w)
                FROM ({source}) h JOIN _taxa USING (taxon_id, egroup) CROSS JOIN {kernel}
                GROUP BY ALL ORDER BY taxon_id, cell, week
                """,
                [region_id, level],
            )
    conn.execute(
        """
        INSERT INTO prior_cells
        SELECT DISTINCT ?, egroup, c, c1, c2 FROM (
            SELECT egroup, c, c1, c2 FROM _v
            UNION ALL SELECT egroup, c, c1, c2 FROM _t
        ) WHERE egroup IN (SELECT egroup FROM _taxa)
        """,
        [region_id],
    )
    # Annual regional rate: detections / effort (group outings, or the species' trials).
    conn.execute(
        """
        INSERT INTO prior_taxa
        SELECT ?, t.taxon_id, t.egroup, split_part(t.egroup, ':', 1),
            split_part(t.egroup, ':', 2), n.name, t.n_det,
            t.n_det / coalesce(tr.n, gv.n), n.inat_id, n.gbif_key
        FROM _taxa t
        LEFT JOIN (SELECT egroup, count(*) AS n FROM _v GROUP BY ALL) gv USING (egroup)
        LEFT JOIN (SELECT taxon_id, egroup, count(*) AS n FROM _t GROUP BY ALL) tr
            USING (taxon_id, egroup)
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

    # Plausible range: context cells with detections (any effort group), plus one ring.
    detected = conn.execute(
        """
        SELECT DISTINCT taxon_id, c2 FROM (
            SELECT taxon_id, egroup, c2 FROM _d UNION ALL
            SELECT taxon_id, egroup, c2 FROM _t WHERE detected
        ) JOIN _taxa USING (taxon_id, egroup)
        """
    ).fetchall()
    mask = sorted({(region_id, t, n) for t, c2 in detected for n in h3.grid_disk(c2, 1)})
    if mask:
        conn.executemany("INSERT INTO prior_mask VALUES (?, ?, ?)", mask)
    conn.execute(
        "INSERT INTO prior_licenses "
        "SELECT ?, egroup, source_id, license_id, count(*) FROM _obs GROUP BY ALL",
        [region_id],
    )
    conn.execute(
        "INSERT INTO prior_builds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            region_id,
            cfg.model_version,
            built_at,
            naive_utc(cutoff) if cutoff else None,
            cfg.res,
            cfg.parent_res,
            cfg.context_res,
            cfg.shrinkage,
            repr(asdict(cfg)),
        ],
    )

    def scalar(sql: str, params: list | None = None) -> int:
        return conn.execute(sql, params if params is not None else [region_id]).fetchone()[0]

    report = BaselineReport(
        region_id=region_id,
        built_at=built_at,
        taxa=scalar("SELECT count(DISTINCT taxon_id) FROM prior_taxa WHERE region_id = ?"),
        taxon_groups=scalar("SELECT count(*) FROM prior_taxa WHERE region_id = ?"),
        cells=scalar("SELECT count(DISTINCT cell) FROM prior_cells WHERE region_id = ?"),
        effort_rows=scalar("SELECT count(*) FROM prior_effort WHERE region_id = ?"),
        hit_rows=scalar("SELECT count(*) FROM prior_hits WHERE region_id = ?"),
        visits=scalar("SELECT count(*) FROM _v", []),
        survey_trials=scalar("SELECT count(*) FROM _t", []),
    )
    report.groups = dict(
        conn.execute("SELECT egroup, count(*) FROM _taxa GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    for tmp in ("_obs", "_d", "_v", "_t", "_taxa", "_k", "_ks"):
        conn.execute(f"DROP TABLE IF EXISTS {tmp}")
    return report
