"""Find, extract and ingest a region from GBIF's monthly snapshots on AWS, over plain HTTPS.

The snapshot bucket is public: ``occurrence/<YYYY-MM-01>/occurrence.parquet/<part>`` (about
10,000 parts of ~25 MB). For each part the extractor fetches the Parquet footer, then only the
latitude/longitude column chunks, and tests the region's bounding box. Only when rows match
does it fetch the other needed columns and write the matching rows to a small local staging
file. No DuckDB extensions are needed. Reference: the Southern California box fetched 135 of
272 GB in 22 minutes with 10 workers (docs/research/08).

Extraction is resumable (``.done`` markers per part). ``ingest_staged`` parses the staged rows
with the package's own parser across processes and bulk-loads them; the most recently ingested
copy of a record wins (``dedupe_key``).

Cite each snapshot per GBIF guidelines (its ``citation.txt``).
"""

from __future__ import annotations

import csv
import glob
import os
import re
import struct
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from multiprocessing import get_context
from pathlib import Path

import duckdb
import httpx

from wildlife_radar.connectors.base import make_client

BUCKET = "https://gbif-open-data-us-east-1.s3.us-east-1.amazonaws.com/"
KEEP = (
    "gbifid",
    "datasetkey",
    "kingdom",
    "phylum",
    "class",
    "species",
    "taxonrank",
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
    # occurrenceid carries iNaturalist's observation URL: without it a snapshot row can't be
    # matched with its live API copy (same dedupe key), and both are kept.
    "occurrenceid",
    "scientificname",
    "lastinterpreted",
)
GAP = 512 * 1024
"""Coalesce byte ranges separated by less than this."""

Bbox = tuple[float, float, float, float]
Log = Callable[[str], None]


# -- Listing -----------------------------------------------------------------------------------


def _list(client: httpx.Client, prefix: str, delimiter: str | None = None) -> tuple[list, list]:
    """``(keys with sizes, common prefixes)`` under ``prefix`` (S3 ListObjectsV2, all pages)."""
    keys: list[tuple[str, int]] = []
    prefixes: list[str] = []
    token = None
    while True:
        params = {"list-type": "2", "prefix": prefix}
        if delimiter:
            params["delimiter"] = delimiter
        if token:
            params["continuation-token"] = token
        resp = client.get(BUCKET, params=params)
        resp.raise_for_status()
        xml = resp.text
        found = re.findall(r"<Key>([^<]+)</Key>", xml)
        sizes = re.findall(r"<Size>(\d+)</Size>", xml)
        keys += [(k, int(s)) for k, s in zip(found, sizes, strict=True)]
        prefixes += re.findall(r"<CommonPrefixes><Prefix>([^<]+)</Prefix>", xml)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", xml)
        if not m:
            return keys, prefixes
        token = m.group(1)


def latest_snapshot(client: httpx.Client | None = None, *, look_back: int = 3) -> str | None:
    """Date (``YYYY-MM-DD``) of the newest complete snapshot, or ``None``.

    A snapshot counts as complete once its ``citation.txt`` and at least one part exist; a
    snapshot still being uploaded is skipped in favor of the previous one.
    """
    client = client or make_client(timeout=60)
    _, prefixes = _list(client, "occurrence/", "/")
    dates = sorted(
        p.split("/")[1] for p in prefixes if re.fullmatch(r"occurrence/\d{4}-\d{2}-\d{2}/", p)
    )
    for d in reversed(dates[-look_back:]):
        keys, subdirs = _list(client, f"occurrence/{d}/", "/")
        if f"occurrence/{d}/citation.txt" in {k for k, _ in keys} and any(
            s.endswith("occurrence.parquet/") for s in subdirs
        ):
            return d
    return None


def list_parts(snapshot_date: str, client: httpx.Client | None = None) -> list[tuple[str, int]]:
    """``[(key, size), ...]`` for a snapshot's Parquet parts."""
    client = client or make_client(timeout=60)
    keys, _ = _list(client, f"occurrence/{snapshot_date}/occurrence.parquet/")
    return [(k, s) for k, s in keys if s > 0]


# -- Extraction ---------------------------------------------------------------------------------


def write_sparse(path: str, size: int, tail: bytes) -> None:
    """A local file of the part's size holding only its footer (the last ``len(tail)`` bytes),
    so DuckDB's ``parquet_metadata()`` can read column-chunk offsets."""
    footer_len = struct.unpack("<I", tail[-8:-4])[0]
    if tail[-4:] != b"PAR1":
        raise ValueError("not a Parquet file")
    if footer_len + 8 > len(tail):
        raise ValueError(f"need {footer_len + 8} tail bytes")
    with open(path, "wb") as fh:
        fh.write(b"PAR1")
        fh.truncate(size)
        fh.seek(size - len(tail))
        fh.write(tail)


def needed_tail(tail: bytes) -> int:
    return struct.unpack("<I", tail[-8:-4])[0] + 8


def _chunks(db: duckdb.DuckDBPyConnection, path: str) -> list[tuple[str, int, int]]:
    """``(top-level column, start, size)`` of every column chunk, from the footer."""
    rows = db.execute(
        "SELECT path_in_schema, coalesce(dictionary_page_offset, data_page_offset), "
        "total_compressed_size FROM parquet_metadata(?)",
        [path],
    ).fetchall()
    return [(name.split(",")[0].strip().lower(), start, size) for name, start, size in rows]


def _chunk_ranges(
    chunks: list[tuple[str, int, int]], columns: set[str] | tuple[str, ...]
) -> list[list[int]]:
    spans = sorted((start, start + size) for name, start, size in chunks if name in columns)
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s - merged[-1][1] < GAP:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


class _Extractor:
    def __init__(self, staging: Path, work: Path, bbox: Bbox) -> None:
        self.staging, self.work, self.bbox = staging, work, bbox
        self.local = threading.local()
        self.lock = threading.Lock()
        self.stats = {"bytes": 0, "parts": 0, "matched": 0, "rows": 0, "skipped_done": 0}

    def _client(self) -> httpx.Client:
        if not hasattr(self.local, "client"):
            self.local.client = make_client(timeout=120)
        return self.local.client

    def _db(self) -> duckdb.DuckDBPyConnection:
        if not hasattr(self.local, "db"):
            self.local.db = duckdb.connect()
        return self.local.db

    def get(self, url: str, rng: str) -> bytes:
        for attempt in range(7):
            try:
                r = self._client().get(url, headers={"Range": rng})
                r.raise_for_status()
                with self.lock:
                    self.stats["bytes"] += len(r.content)
                return r.content
            except httpx.HTTPError:
                self.local.__dict__.pop("client", None)
                time.sleep(min(2**attempt, 30))
        raise RuntimeError(f"giving up on {url} {rng}")

    def _fill(self, path: str, url: str, ranges: list[list[int]]) -> None:
        with open(path, "r+b") as fh:
            for s, e in ranges:
                fh.seek(s)
                fh.write(self.get(url, f"bytes={s}-{e - 1}"))

    def process(self, key: str, size: int) -> None:
        name = key.rsplit("/", 1)[1]
        done = self.staging / f"{name}.done"
        if done.exists():
            with self.lock:
                self.stats["skipped_done"] += 1
            return
        url = BUCKET + key
        db = self._db()
        tail = self.get(url, "bytes=-65536")
        if needed_tail(tail) > len(tail):
            tail = self.get(url, f"bytes=-{needed_tail(tail)}")
        path = str(self.work / f"{name}.parquet")
        write_sparse(path, size, tail)
        lon_min, lat_min, lon_max, lat_max = (float(v) for v in self.bbox)
        where = (
            f"decimallatitude BETWEEN {lat_min} AND {lat_max} "
            f"AND decimallongitude BETWEEN {lon_min} AND {lon_max}"
        )
        try:
            chunks = _chunks(db, path)
            self._fill(path, url, _chunk_ranges(chunks, {"decimallatitude", "decimallongitude"}))
            n = db.execute(f"SELECT count(*) FROM read_parquet('{path}') WHERE {where}").fetchone()[
                0
            ]
            if n:
                self._fill(path, url, _chunk_ranges(chunks, KEEP))
                present = {c for c, _, _ in chunks}
                # Older snapshots may lack newer columns (e.g. eventid): NULL keeps the schema.
                cols = ", ".join(c if c in present else f"NULL::VARCHAR AS {c}" for c in KEEP)
                out = self.staging / f"{name}.parquet"
                db.execute(
                    f"COPY (SELECT {cols} FROM read_parquet('{path}') WHERE {where}) "
                    f"TO '{out}' (FORMAT parquet, COMPRESSION zstd)"
                )
            done.write_text(str(n), encoding="utf-8")
            with self.lock:
                self.stats["parts"] += 1
                self.stats["matched"] += bool(n)
                self.stats["rows"] += n
        finally:
            os.remove(path)


def extract_region(
    parts: Sequence[tuple[str, int]],
    staging: str | Path,
    work: str | Path,
    bbox: Bbox,
    workers: int = 8,
    log: Log = print,
) -> dict:
    """Stage the bbox's rows of every part into ``staging`` (resumable); returns statistics."""
    staging, work = Path(staging), Path(work)
    staging.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    ex = _Extractor(staging, work, bbox)
    t0 = time.time()
    with ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(ex.process, k, s) for k, s in parts]
        for i, f in enumerate(as_completed(futures), 1):
            f.result()
            if i % 250 == 0 or i == len(futures):
                el = max(time.time() - t0, 1e-6)
                s = ex.stats
                log(
                    f"{i}/{len(futures)} parts | matched {s['matched']} | rows {s['rows']:,} | "
                    f"{s['bytes'] / 1e9:.1f} GB | {s['bytes'] / 1e6 / el:.0f} MB/s | "
                    f"{el / 60:.1f} min"
                )
    return dict(ex.stats)


# -- Ingestion ----------------------------------------------------------------------------------


def _parse_chunk(args: tuple[str, list[str], Bbox]) -> tuple[str, int]:
    from wildlife_radar.connectors.gbif_snapshot import snapshot_observations
    from wildlife_radar.storage.observations import _csv_value, observation_row

    out, files, bbox = args
    n = 0
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for obs in snapshot_observations(files, bbox):
            w.writerow("" if v is None else _csv_value(v) for v in observation_row(obs))
            n += 1
    return out, n


def ingest_staged(
    db: str | Path,
    staging: str | Path | list[str],
    bbox: Bbox,
    workers: int = 4,
    log: Log = print,
    reconcile_taken: datetime | None = None,
    live_keys: list[str] | None = None,
) -> dict:
    """Parse staged rows (a folder of Parquet files, or a list of files) in ``workers``
    processes and bulk-load them into the store at ``db``.

    With ``reconcile_taken`` (when the snapshot was taken), these rows are a complete
    snapshot of ``bbox``: GBIF rows from earlier ingests that it lacks are deleted (deleted or
    withdrawn at the source). Rows of ``live_keys`` datasets pulled from the API after the
    snapshot was taken are kept: they may simply be newer than it."""
    from wildlife_radar.storage import ObservationStore

    started = datetime.now(UTC).replace(tzinfo=None)

    if isinstance(staging, list):
        files = sorted(staging)
    else:
        files = sorted(glob.glob(os.path.join(str(staging), "*.parquet")))
    if not files:
        raise RuntimeError(f"no staged rows in {staging}")
    tmpdir = tempfile.mkdtemp(prefix="ingest-", dir=os.path.dirname(os.path.abspath(db)))
    n_chunks = workers * 4
    chunks = [
        (os.path.join(tmpdir, f"rows-{i}.csv"), files[i::n_chunks], bbox) for i in range(n_chunks)
    ]
    chunks = [c for c in chunks if c[1]]
    t0 = time.time()
    with get_context("spawn").Pool(workers) as pool:
        results = pool.map(_parse_chunk, chunks)
    parsed = sum(n for _, n in results)
    log(f"parsed {parsed:,} rows in {time.time() - t0:.0f}s")
    t1 = time.time()
    with ObservationStore(db) as store:
        conn = store.conn
        conn.execute("CREATE OR REPLACE TEMP TABLE _staging AS SELECT * FROM observations LIMIT 0")
        for path, _ in results:
            conn.execute(f"COPY _staging FROM '{path}' (FORMAT csv, HEADER false, NULLSTR '')")
            os.remove(path)
        conn.execute(
            "INSERT OR REPLACE INTO observations SELECT * FROM _staging QUALIFY "
            "row_number() OVER (PARTITION BY dedupe_key ORDER BY ingested_at DESC) = 1"
        )
        removed = 0
        if reconcile_taken is not None:
            lon_min, lat_min, lon_max, lat_max = bbox
            before = conn.execute("SELECT count(*) FROM observations").fetchone()[0]
            conn.execute(
                """
                DELETE FROM observations
                WHERE source_id = 'gbif' AND ingested_at < ?
                  AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                  AND dedupe_key NOT IN (SELECT dedupe_key FROM _staging)
                  AND (coalesce(dataset_key, '') NOT IN (SELECT unnest(?)) OR ingested_at < ?)
                """,
                [
                    started,
                    lat_min,
                    lat_max,
                    lon_min,
                    lon_max,
                    list(live_keys or []),
                    reconcile_taken.replace(tzinfo=None),
                ],
            )
            removed = before - conn.execute("SELECT count(*) FROM observations").fetchone()[0]
            log(f"reconciled: {removed:,} GBIF rows no longer in the snapshot removed")
        conn.execute("DROP TABLE _staging")
        total = store.count()
    os.rmdir(tmpdir)
    log(f"loaded in {time.time() - t1:.0f}s; store has {total:,} rows")
    return {"parsed": parsed, "total": total, "removed": removed}
