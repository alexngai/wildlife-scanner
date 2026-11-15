"""The global reference store: taxon data shared by every region (data-platform.md §2, ``ref``).

Each shared table lives under ``lake/ref/<table>/`` as immutable Parquet parts. A job imports
the parts into its region's work store before it runs (rows it lacks, or older copies of them)
and exports the rows it fetched afterwards as a new part named after its writer (the region).
Writers never touch the same file, so regions can run in parallel on one machine or on
several (``sync_ref`` copies parts through object storage). On read, the newest
``fetched_at`` wins.

Only region-independent data is shared:

- ``taxon_identity``: name → identity crosswalk records (Catalogue of Life, Wikidata, ...);
- ``inat_taxon_records``: raw iNaturalist taxon records;
- ``gbif_event_ids``: GBIF record id → eventID for re-dated survey records (slow to fetch:
  GBIF rate-limits the paging, so a rebuild must not start over).

Status *lookups* are not shared: which statuses apply depends on each region's places, so they
are parsed and cached per region (connectors/inaturalist_taxa.py).
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import duckdb

from wildlife_scanner.connectors.inaturalist_taxa import RECORDS_SCHEMA
from wildlife_scanner.core.time import utcnow
from wildlife_scanner.profilegen.identity import IDENTITY_SCHEMA
from wildlife_scanner.storage.repair import EVENT_IDS_SCHEMA

REF_TABLES: dict[str, tuple[str, str]] = {
    "taxon_identity": ("query_name", IDENTITY_SCHEMA),
    "inat_taxon_records": ("taxon_id", RECORDS_SCHEMA),
    "gbif_event_ids": ("gbif_id", EVENT_IDS_SCHEMA),
}


class RefStore:
    def __init__(self, root: str | Path, writer: str) -> None:
        self.root = Path(root)
        self.writer = writer

    def parts(self, table: str) -> list[Path]:
        folder = self.root / table
        return sorted(folder.glob("part-*.parquet")) if folder.exists() else []

    def import_into(self, conn: duckdb.DuckDBPyConnection, table: str) -> int:
        """Copy shared rows the store lacks, or holds older copies of. Returns rows imported."""
        key, schema = REF_TABLES[table]
        conn.execute(schema)
        parts = self.parts(table)
        if not parts:
            return 0
        files = "[" + ", ".join(f"'{p.as_posix()}'" for p in parts) + "]"
        conn.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE _ref_import AS
            SELECT r.* FROM (
                SELECT * FROM read_parquet({files}, union_by_name = true)
                QUALIFY row_number() OVER (PARTITION BY {key} ORDER BY fetched_at DESC) = 1
            ) r
            LEFT JOIN {table} l ON l.{key} = r.{key}
            WHERE l.{key} IS NULL OR l.fetched_at < r.fetched_at
            """
        )
        n = conn.execute("SELECT count(*) FROM _ref_import").fetchone()[0]
        if n:
            conn.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM _ref_import")
        conn.execute("DROP TABLE _ref_import")
        return n

    def export_from(
        self, conn: duckdb.DuckDBPyConnection, table: str, since: datetime
    ) -> Path | None:
        """Write rows fetched at or after ``since`` as a new part; ``None`` if there are none."""
        key, schema = REF_TABLES[table]
        conn.execute(schema)
        since_naive = since.replace(tzinfo=None)
        n = conn.execute(
            f"SELECT count(*) FROM {table} WHERE fetched_at >= ?", [since_naive]
        ).fetchone()[0]
        if not n:
            return None
        folder = self.root / table
        folder.mkdir(parents=True, exist_ok=True)
        stamp = utcnow().strftime("%Y%m%dT%H%M%S%f")
        path = folder / f"part-{self.writer}-{stamp}.parquet"
        tmp = folder / f".{path.name}.tmp"
        conn.execute(
            f"COPY (SELECT * FROM {table} WHERE fetched_at >= ? ORDER BY {key}) "
            f"TO '{tmp.as_posix()}' (FORMAT parquet, COMPRESSION zstd)",
            [since_naive],
        )
        os.replace(tmp, path)
        return path
