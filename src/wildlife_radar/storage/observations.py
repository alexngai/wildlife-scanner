"""DuckDB-backed observation store.

Observations are flattened into one row each, with precomputed H3 cells at several resolutions
(only where the record's positional uncertainty is finer than the cell), a local calendar date,
ISO week, and a *visit key* (one observer, one day, one place), which the baseline uses to
measure sampling effort.

Records duplicated across sources (e.g., iNaturalist observations that also arrive via GBIF)
share a ``dedupe_key``; the most recently ingested copy wins.

Never point the store at a path inside the repository: data stays out of git.
"""

from __future__ import annotations

import csv
import os
import re
import tempfile
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

from wildlife_radar.core import spatial
from wildlife_radar.core.geometry import (
    CellsFootprint,
    PointFootprint,
    PolygonFootprint,
    StationFootprint,
    footprint_centroid,
)
from wildlife_radar.core.observations import Observation
from wildlife_radar.core.taxa import species_id_from_name
from wildlife_radar.core.time import Precision, utcnow

CELL_RESOLUTIONS = (3, 4, 5, 6, 7, 8)
#: Finest resolution used in visit keys; baselines must not be finer than this.
VISIT_RES = 7

_WEEK_PRECISIONS = {
    Precision.INSTANT,
    Precision.MINUTE,
    Precision.HOUR,
    Precision.DAY,
    Precision.WEEK,
}
_INAT_URL = re.compile(r"inaturalist\.org/observations/(\d+)")

_CELL_COLS = ", ".join(f"cell_r{r} VARCHAR" for r in CELL_RESOLUTIONS)
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS observations (
    dedupe_key VARCHAR PRIMARY KEY,
    obs_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    source_record_id VARCHAR,
    taxon_scheme VARCHAR,
    taxon_source_id VARCHAR,
    taxon_name VARCHAR,
    taxon_rank VARCHAR,
    taxon_id VARCHAR,
    group_id VARCHAR,
    lat DOUBLE,
    lon DOUBLE,
    uncertainty_m DOUBLE,
    {_CELL_COLS},
    time_start TIMESTAMP,
    time_end TIMESTAMP,
    time_precision VARCHAR,
    local_date DATE,
    week SMALLINT,
    visit_key VARCHAR,
    outcome VARCHAR,
    count DOUBLE,
    evidence_grade VARCHAR,
    modality VARCHAR,
    method VARCHAR,
    effort_duration_min DOUBLE,
    license_id VARCHAR,
    obscured BOOLEAN,
    geoprivacy VARCHAR,
    taxon_geoprivacy VARCHAR,
    observer_hash VARCHAR,
    dataset_key VARCHAR,
    ingested_at TIMESTAMP,
    basis_of_record VARCHAR
)
"""
#: Columns added after the first schema version (appended, so column order stays stable).
MIGRATIONS = ("ALTER TABLE observations ADD COLUMN IF NOT EXISTS basis_of_record VARCHAR",)
COLUMNS = [
    "dedupe_key",
    "obs_id",
    "source_id",
    "source_record_id",
    "taxon_scheme",
    "taxon_source_id",
    "taxon_name",
    "taxon_rank",
    "taxon_id",
    "group_id",
    "lat",
    "lon",
    "uncertainty_m",
    *(f"cell_r{r}" for r in CELL_RESOLUTIONS),
    "time_start",
    "time_end",
    "time_precision",
    "local_date",
    "week",
    "visit_key",
    "outcome",
    "count",
    "evidence_grade",
    "modality",
    "method",
    "effort_duration_min",
    "license_id",
    "obscured",
    "geoprivacy",
    "taxon_geoprivacy",
    "observer_hash",
    "dataset_key",
    "ingested_at",
    "basis_of_record",
]


def _csv_value(v: object) -> object:
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


def week_of(d: date) -> int:
    """ISO week, with week 53 folded into 52 so every year has 52 bins."""
    return min(d.isocalendar().week, 52)


def local_date(obs: Observation, lon: float) -> date | None:
    """Approximate local calendar date (UTC offset from longitude), if the time is precise."""
    if obs.time.precision not in _WEEK_PRECISIONS:
        return None
    return (obs.time.midpoint + timedelta(hours=round(lon / 15))).date()


def footprint_cells_by_res(
    obs: Observation,
) -> tuple[float, float, float | None, dict[int, str | None]]:
    """``(lat, lon, uncertainty_m, {res: cell})``; a cell is ``None`` where the record is too
    imprecise for that resolution.

    Coarser cells are always the H3 *parents* of the finest valid cell (not independent
    point lookups, which can disagree because H3 cells don't nest exactly), so the store, the
    baseline hierarchy and the policy layer's coarsening all agree.
    """
    fp = obs.footprint
    cells: dict[int, str | None] = dict.fromkeys(CELL_RESOLUTIONS)
    if isinstance(fp, PointFootprint | StationFootprint):
        unc = fp.uncertainty_m if isinstance(fp, PointFootprint) else None
        allowed = [r for r in CELL_RESOLUTIONS if unc is None or unc <= spatial.edge_km(r) * 1000]
        if allowed:
            finest = spatial.cell_for_point(fp.lat, fp.lon, max(allowed))
            for r in allowed:
                cells[r] = spatial.coarsen_cell(finest, r)
        return fp.lat, fp.lon, unc, cells
    lat, lon = footprint_centroid(fp)
    if isinstance(fp, CellsFootprint) and len(fp.cells) == 1:
        (cell,) = fp.cells
        r0 = spatial.cell_resolution(cell)
        for r in CELL_RESOLUTIONS:
            if r <= r0:
                cells[r] = spatial.coarsen_cell(cell, r)
        return lat, lon, spatial.edge_km(r0) * 1000, cells
    if isinstance(fp, PolygonFootprint | CellsFootprint):
        cells[CELL_RESOLUTIONS[0]] = spatial.cell_for_point(lat, lon, CELL_RESOLUTIONS[0])
    return lat, lon, None, cells


def dedupe_key(obs: Observation) -> str:
    if obs.source_id == "inaturalist" and obs.source_record_id:
        return f"inat:{obs.source_record_id}"
    occurrence_id = obs.extras.get("occurrence_id")
    if occurrence_id and (m := _INAT_URL.search(str(occurrence_id))):
        return f"inat:{m.group(1)}"
    return obs.obs_id


def observation_row(obs: Observation) -> tuple:
    lat, lon, unc, cells = footprint_cells_by_res(obs)
    d = local_date(obs, lon)
    observer = obs.extras.get("observer_hash")
    dataset = obs.extras.get("dataset_key")
    visit_cell = next((cells[r] for r in (VISIT_RES, 6, 5) if cells.get(r)), None)
    visit_key = None
    if d is not None and visit_cell is not None:
        visit_key = f"{observer or dataset or obs.source_id}|{d.isoformat()}|{visit_cell}"
    taxon_id = obs.taxon_id or species_id_from_name(obs.taxon.name, obs.taxon.rank)
    return (
        dedupe_key(obs),
        obs.obs_id,
        obs.source_id,
        obs.source_record_id,
        obs.taxon.scheme.value,
        obs.taxon.id,
        obs.taxon.name,
        obs.taxon.rank,
        taxon_id,
        obs.extras.get("group"),
        lat,
        lon,
        unc,
        *(cells[r] for r in CELL_RESOLUTIONS),
        naive_utc(obs.time.start),
        naive_utc(obs.time.end),
        obs.time.precision.value,
        d,
        week_of(d) if d else None,
        visit_key,
        obs.outcome.value,
        obs.count,
        obs.evidence_grade.value,
        obs.modality.value,
        obs.method,
        obs.effort.duration_min if obs.effort else None,
        obs.license.id,
        obs.sensitivity.obscured,
        obs.sensitivity.geoprivacy,
        obs.sensitivity.taxon_geoprivacy,
        observer,
        dataset,
        naive_utc(obs.ingested_at),
        obs.extras.get("basis_of_record"),
    )


class ObservationStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(self.path)
        self.conn.execute(SCHEMA)
        for migration in MIGRATIONS:
            self.conn.execute(migration)

    def add(self, observations: Iterable[Observation], batch_size: int = 20_000) -> int:
        n = 0
        batch: list[tuple] = []
        for obs in observations:
            batch.append(observation_row(obs))
            if len(batch) >= batch_size:
                n += self._flush(batch)
        if batch:
            n += self._flush(batch)
        return n

    def _flush(self, batch: list[tuple]) -> int:
        # Collapse duplicates within the batch (last wins), bulk-load through a temporary CSV
        # (orders of magnitude faster than parameter binding), then upsert in one statement.
        unique = list({row[0]: row for row in batch}.values())
        batch.clear()
        with tempfile.NamedTemporaryFile(
            "w", suffix=".csv", newline="", encoding="utf-8", delete=False
        ) as fh:
            writer = csv.writer(fh)
            for row in unique:
                writer.writerow("" if v is None else _csv_value(v) for v in row)
            tmp_path = fh.name
        try:
            self.conn.execute(
                "CREATE OR REPLACE TEMP TABLE _staging AS SELECT * FROM observations LIMIT 0"
            )
            self.conn.execute(
                f"COPY _staging FROM '{tmp_path}' (FORMAT csv, HEADER false, NULLSTR '')"
            )
            self.conn.execute("INSERT OR REPLACE INTO observations SELECT * FROM _staging")
            self.conn.execute("DROP TABLE _staging")
        finally:
            os.unlink(tmp_path)
        return len(unique)

    def count(self) -> int:
        return self.conn.execute("SELECT count(*) FROM observations").fetchone()[0]

    def summary(self) -> dict:
        rows = self.conn.execute(
            """
            SELECT source_id, group_id, count(*) AS n, count(DISTINCT taxon_id) AS taxa,
                   count(DISTINCT visit_key) AS visits
            FROM observations GROUP BY ALL ORDER BY n DESC
            """
        ).fetchall()
        return {
            "n": self.count(),
            "by_source_group": [
                {"source": s, "group": g, "records": n, "taxa": t, "visits": v}
                for s, g, n, t, v in rows
            ],
            "as_of": utcnow().isoformat(),
        }

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> ObservationStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
