"""List the parts of a GBIF monthly snapshot on AWS (S3 ListObjectsV2 over HTTPS).

    uv run python tools/list_parts.py 2026-11-01 data/parts.json

Writes ``[[key, size], ...]`` for ``tools/extract_region.py``.
"""

from __future__ import annotations

import json
import re
import sys

import httpx

BUCKET = "https://gbif-open-data-us-east-1.s3.us-east-1.amazonaws.com/"


def main(date: str, out: str) -> None:
    prefix = f"occurrence/{date}/occurrence.parquet/"
    token = None
    parts: list[tuple[str, int]] = []
    with httpx.Client(timeout=60) as client:
        while True:
            params = {"list-type": "2", "prefix": prefix}
            if token:
                params["continuation-token"] = token
            xml = client.get(BUCKET, params=params).text
            keys = re.findall(r"<Key>([^<]+)</Key>", xml)
            sizes = re.findall(r"<Size>(\d+)</Size>", xml)
            parts += [(k, int(s)) for k, s in zip(keys, sizes, strict=True)]
            m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", xml)
            if not m:
                break
            token = m.group(1)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(parts, fh)
    total = sum(s for _, s in parts)
    print(f"{len(parts)} parts, {total / 1e9:.1f} GB")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
