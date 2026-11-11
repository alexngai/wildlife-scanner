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
) -> Iterator[dict]:
    """Rows of the snapshot inside ``bbox`` (``lon_min, lat_min, lon_max, lat_max``)."""
    path_list = [paths] if isinstance(paths, str) else list(paths)
    con = con or duckdb.connect()
    if any(p.startswith(("s3://", "http://", "https://")) for p in path_list):
        con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-east-1'")
    lon_min, lat_min, lon_max, lat_max = bbox
    cols = ", ".join(SNAPSHOT_COLUMNS)
    sources = "[" + ", ".join(_quote(p) for p in path_list) + "]"
    cursor = con.execute(
        f"""
        SELECT {cols} FROM read_parquet({sources})
        WHERE decimallatitude BETWEEN ? AND ? AND decimallongitude BETWEEN ? AND ?
        """,
        [lat_min, lat_max, lon_min, lon_max],
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
) -> Iterator[Observation]:
    report = report if report is not None else SnapshotReport()
    ingested_at = utcnow()
    for row in snapshot_rows(paths, bbox):
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
