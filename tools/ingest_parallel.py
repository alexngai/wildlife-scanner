"""Parallel ingestion of staged snapshot rows into an ObservationStore (see tools/README.md).

Workers parse staging Parquet files with the package's own parser and write CSV rows;
the main process bulk-loads them (same path as ObservationStore.add).
usage: ingest_parallel.py db staging_dir lon_min lat_min lon_max lat_max [workers]
"""

import csv
import glob
import os
import sys
import tempfile
import time
from multiprocessing import Pool

from wildlife_radar.connectors.gbif_snapshot import snapshot_observations
from wildlife_radar.storage.observations import (
    ObservationStore,
    _csv_value,
    observation_row,
)

db, staging = sys.argv[1], sys.argv[2]
bbox = tuple(map(float, sys.argv[3:7]))
workers = int(sys.argv[7]) if len(sys.argv) > 7 else 4
tmpdir = tempfile.mkdtemp(prefix="ingest-", dir=os.path.dirname(db))


def work(args):
    idx, files = args
    out = os.path.join(tmpdir, f"rows-{idx}.csv")
    n = 0
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for obs in snapshot_observations(files, bbox):
            w.writerow("" if v is None else _csv_value(v) for v in observation_row(obs))
            n += 1
    return out, n


if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(staging, "*.parquet")))
    chunks = [(i, files[i :: workers * 4]) for i in range(workers * 4)]
    chunks = [c for c in chunks if c[1]]
    t0 = time.time()
    with Pool(workers) as pool:
        results = pool.map(work, chunks)
    print(f"parsed {sum(n for _, n in results):,} rows in {time.time() - t0:.0f}s", flush=True)
    store = ObservationStore(db)
    t1 = time.time()
    store.conn.execute(
        "CREATE OR REPLACE TEMP TABLE _staging AS SELECT * FROM observations LIMIT 0"
    )
    for path, _ in results:
        store.conn.execute(f"COPY _staging FROM '{path}' (FORMAT csv, HEADER false, NULLSTR '')")
        os.remove(path)
    store.conn.execute(
        "INSERT OR REPLACE INTO observations SELECT * FROM _staging QUALIFY "
        "row_number() OVER (PARTITION BY dedupe_key ORDER BY ingested_at DESC) = 1"
    )
    store.conn.execute("DROP TABLE _staging")
    os.rmdir(tmpdir)
    print(f"loaded in {time.time() - t1:.0f}s; store has {store.count():,} rows", flush=True)
    store.close()
