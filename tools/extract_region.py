"""Extract a region's rows from a remote GBIF snapshot using HTTP range requests only.

For each part: fetch the footer; fetch the lat/lon column chunks into a sparse local copy and
test the bbox; only if rows match, fetch the other needed column chunks and write the matching
rows (projected columns) to a small local staging Parquet. No DuckDB extensions needed.

usage: extract_region.py parts.json staging_dir work_dir lon_min lat_min lon_max lat_max [workers]
"""

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb
import httpx

sys.path.insert(0, os.path.dirname(__file__))
from footer import needed_tail, write_sparse

BUCKET = "https://gbif-open-data-us-east-1.s3.us-east-1.amazonaws.com/"
KEEP = [
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
]
GAP = 512 * 1024  # coalesce ranges separated by less than this

with open(sys.argv[1]) as fh:
    parts = json.load(fh)
staging, work = sys.argv[2], sys.argv[3]
lon_min, lat_min, lon_max, lat_max = map(float, sys.argv[4:8])
workers = int(sys.argv[8]) if len(sys.argv) > 8 else 8
os.makedirs(staging, exist_ok=True)
os.makedirs(work, exist_ok=True)
local = threading.local()
stats = {"bytes": 0, "parts": 0, "matched": 0, "rows": 0, "skipped_done": 0}
lock = threading.Lock()


def client():
    if not hasattr(local, "c"):
        local.c = httpx.Client(verify=os.environ["SSL_CERT_FILE"], timeout=120)
    if not hasattr(local, "db"):
        local.db = duckdb.connect()
    return local.c, local.db


def get(url, rng):
    for attempt in range(7):
        try:
            c, _ = client()
            r = c.get(url, headers={"Range": rng})
            r.raise_for_status()
            with lock:
                stats["bytes"] += len(r.content)
            return r.content
        except httpx.HTTPError:
            local.__dict__.pop("c", None)
            time.sleep(min(2**attempt, 30))
    raise RuntimeError(f"giving up on {url} {rng}")


def chunk_ranges(db, path, columns):
    rows = db.execute(
        "select path_in_schema, coalesce(dictionary_page_offset, data_page_offset), "
        "total_compressed_size from parquet_metadata(?)",
        [path],
    ).fetchall()
    out = []
    for name, start, size in rows:
        if name.split(",")[0].strip() in columns:
            out.append((start, start + size))
    out.sort()
    merged = []
    for s, e in out:
        if merged and s - merged[-1][1] < GAP:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def fill(path, url, ranges):
    with open(path, "r+b") as fh:
        for s, e in ranges:
            fh.seek(s)
            fh.write(get(url, f"bytes={s}-{e - 1}"))


def process(item):
    key, size = item
    name = key.rsplit("/", 1)[1]
    done_marker = os.path.join(staging, name + ".done")
    if os.path.exists(done_marker):
        with lock:
            stats["skipped_done"] += 1
        return
    url = BUCKET + key
    _, db = client()
    tail = get(url, "bytes=-65536")
    if needed_tail(tail) > len(tail):
        tail = get(url, f"bytes=-{needed_tail(tail)}")
    path = os.path.join(work, name + ".parquet")
    write_sparse(path, size, tail)
    try:
        fill(path, url, chunk_ranges(db, path, {"decimallatitude", "decimallongitude"}))
        where = (
            f"decimallatitude BETWEEN {lat_min} AND {lat_max} "
            f"AND decimallongitude BETWEEN {lon_min} AND {lon_max}"
        )
        n = db.execute(f"select count(*) from read_parquet('{path}') where {where}").fetchone()[0]
        if n:
            fill(path, url, chunk_ranges(db, path, set(KEEP)))
            out = os.path.join(staging, name + ".parquet")
            cols = ", ".join(KEEP)
            db.execute(
                f"COPY (SELECT {cols}, NULL::VARCHAR AS occurrenceid, "
                f"NULL::VARCHAR AS scientificname FROM read_parquet('{path}') WHERE {where}) "
                f"TO '{out}' (FORMAT parquet, COMPRESSION zstd)"
            )
        with open(done_marker, "w") as fh:
            fh.write(str(n))
        with lock:
            stats["parts"] += 1
            stats["matched"] += bool(n)
            stats["rows"] += n
    finally:
        os.remove(path)


t0 = time.time()
with ThreadPoolExecutor(workers) as ex:
    futures = [ex.submit(process, p) for p in parts]
    for i, f in enumerate(as_completed(futures), 1):
        f.result()
        if i % 250 == 0 or i == len(futures):
            el = time.time() - t0
            print(
                f"{i}/{len(futures)} parts | matched {stats['matched']} | "
                f"rows {stats['rows']:,} | {stats['bytes'] / 1e9:.1f} GB | "
                f"{stats['bytes'] / 1e6 / el:.0f} MB/s | {el / 60:.1f} min",
                flush=True,
            )
print("DONE", json.dumps(stats))
