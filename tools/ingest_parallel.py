"""Parallel ingestion of staged snapshot rows into an ObservationStore (see tools/README.md).

usage: ingest_parallel.py db staging_dir lon_min lat_min lon_max lat_max [workers]
"""

import sys

from wildlife_scanner.connectors.gbif_snapshot_remote import ingest_staged

if __name__ == "__main__":
    bbox = tuple(map(float, sys.argv[3:7]))
    workers = int(sys.argv[7]) if len(sys.argv) > 7 else 4
    ingest_staged(sys.argv[1], sys.argv[2], bbox, workers)
