"""Bulk ingestion from GBIF's monthly occurrence snapshots (Parquet).

Snapshots are published as open data, e.g. on AWS at
``s3://gbif-open-data-us-east-1/occurrence/<YYYY-MM-01>/occurrence.parquet/*`` (several
thousand ~40 MB parts). DuckDB reads only the needed columns and row groups, filtering by bounding
box before rows reach Python.

Remote paths (``s3://``, ``https://``) need DuckDB's ``httpfs`` extension, which DuckDB downloads
on first use; local paths need nothing. The column schema was verified against the 2026-11-01
snapshot (lower-case Darwin Core names; ``eventdate`` is a naive timestamp whose precision is
given by ``year``/``month``/``day``; ``recordedby``, ``mediatype`` and ``issue`` are lists).

Cite the snapshot per GBIF guidelines and register a derived-dataset DOI for published products.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

import duckdb

from wildlife_radar.connectors.gbif import parse_dwc_record
from wildlife_radar.core.observations import Observation
from wildlife_radar.core.time import utcnow

SNAPSHOT_URL = "s3://gbif-open-data-us-east-1/occurrence/{date}/occurrence.parquet/*"

SNAPSHOT_COLUMNS = (
    "gbifid",
    "datasetkey",
    "occurrenceid",
    "kingdom",
    "phylum",
    "class",
    "species",
    "taxonrank",
    "scientificname",
    "occurrencestatus",
    "individualcount",
    "decimallatitude",
    "decimallongitude",
    "coordinateuncertaintyinmeters",
    "eventdate",
    "day",
    "month",
    "year",
    "taxonkey",
    "specieskey",
    "basisofrecord",
    "license",
    "recordedby",
    "mediatype",
    "issue",
    "eventid",
)


def snapshot_url(snapshot_date: str) -> str:
    return SNAPSHOT_URL.format(date=snapshot_date)


def _quote(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


@dataclass
class SnapshotReport:
    rows_read: int = 0
    parsed: int = 0
    skipped: int = 0
    issues: dict[str, int] = field(default_factory=dict)


def snapshot_rows(
    paths: str | Sequence[str],
    bbox: tuple[float, float, float, float],
    *,
    batch_size: int = 10_000,
    con: duckdb.DuckDBPyConnection | None = None,
    row_range: tuple[int, int] | None = None,
) -> Iterator[dict]:
    """Rows of the snapshot inside ``bbox`` (``lon_min, lat_min, lon_max, lat_max``); with
    ``row_range`` (start, end), only those row numbers of each file (row groups outside the
    range are skipped)."""
    path_list = [paths] if isinstance(paths, str) else list(paths)
    con = con or duckdb.connect()
    if any(p.startswith(("s3://", "http://", "https://")) for p in path_list):
        con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-east-1'")
    lon_min, lat_min, lon_max, lat_max = bbox
    sources = "[" + ", ".join(_quote(p) for p in path_list) + "]"
    # Older extracts may lack newer columns (e.g. eventid): select NULL for those.
    present = {
        r[0].lower()
        for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({sources}) LIMIT 0").fetchall()
    }
    cols = ", ".join(c if c in present else f"NULL AS {c}" for c in SNAPSHOT_COLUMNS)
    params: list = [lat_min, lat_max, lon_min, lon_max]
    rows = ""
    if row_range is not None:
        rows = "AND file_row_number >= ? AND file_row_number < ?"
        params += list(row_range)
    cursor = con.execute(
        f"""
        SELECT {cols} FROM read_parquet({sources}, file_row_number = {row_range is not None})
        WHERE decimallatitude BETWEEN ? AND ? AND decimallongitude BETWEEN ? AND ? {rows}
        """,
        params,
    )
    while True:
        batch = cursor.fetchmany(batch_size)
        if not batch:
            return
        for row in batch:
            yield dict(zip(SNAPSHOT_COLUMNS, row, strict=True))


def snapshot_observations(
    paths: str | Sequence[str],
    bbox: tuple[float, float, float, float],
    report: SnapshotReport | None = None,
    limit: int | None = None,
    row_range: tuple[int, int] | None = None,
) -> Iterator[Observation]:
    report = report if report is not None else SnapshotReport()
    ingested_at = utcnow()
    for row in snapshot_rows(paths, bbox, row_range=row_range):
        report.rows_read += 1
        try:
            obs = parse_dwc_record(row, ingested_at)
        except (ValueError, TypeError) as exc:
            key = type(exc).__name__
            report.issues[key] = report.issues.get(key, 0) + 1
            obs = None
        if obs is None:
            report.skipped += 1
            continue
        report.parsed += 1
        yield obs
        if limit is not None and report.parsed >= limit:
            return
