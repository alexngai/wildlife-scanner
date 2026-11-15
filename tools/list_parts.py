"""List the parts of a GBIF monthly snapshot on AWS (S3 ListObjectsV2 over HTTPS).

    uv run python tools/list_parts.py 2026-11-01 data/parts.json

Writes ``[[key, size], ...]`` for ``tools/extract_region.py``. The ``snapshot`` job does all
three steps itself with ``wildlife-scanner run ... --ingest-snapshots``.
"""

from __future__ import annotations

import json
import sys

from wildlife_scanner.connectors.gbif_snapshot_remote import list_parts


def main(date: str, out: str) -> None:
    parts = list_parts(date)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(parts, fh)
    print(f"{len(parts)} parts, {sum(s for _, s in parts) / 1e9:.1f} GB")


if __name__ == "__main__":
    main(*sys.argv[1:3])
