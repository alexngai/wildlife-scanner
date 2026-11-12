"""Extract a region's rows from a remote GBIF snapshot using HTTP range requests only.

usage: extract_region.py parts.json staging_dir work_dir lon_min lat_min lon_max lat_max [workers]

See ``wildlife_radar.connectors.gbif_snapshot_remote``.
"""

import json
import sys

from wildlife_radar.connectors.gbif_snapshot_remote import extract_region

if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as fh:
        parts = [tuple(p) for p in json.load(fh)]
    bbox = tuple(map(float, sys.argv[4:8]))
    workers = int(sys.argv[8]) if len(sys.argv) > 8 else 8
    stats = extract_region(parts, sys.argv[2], sys.argv[3], bbox, workers)
    print("DONE", json.dumps(stats))
