"""GBIF dataset metadata (title, type, license), cached in the ``dataset_meta`` table.

Dataset type is the most reliable signal of how a dataset observes: ``SAMPLING_EVENT`` datasets
come from structured monitoring with explicit absences (survey effort models), ``OCCURRENCE``
datasets are opportunistic records.
"""

from __future__ import annotations

from collections.abc import Iterable

import duckdb
import httpx

from wildlife_scanner.baseline.effort import DATASET_META_SCHEMA
from wildlife_scanner.connectors.base import ConnectorError, RateLimiter, get_json, make_client
from wildlife_scanner.core.time import utcnow
from wildlife_scanner.storage.observations import naive_utc

BASE_URL = "https://api.gbif.org/v1/dataset"


def fetch_dataset_meta(
    conn: duckdb.DuckDBPyConnection,
    dataset_keys: Iterable[str] | None = None,
    *,
    client: httpx.Client | None = None,
    limiter: RateLimiter | None = None,
    min_records: int = 1,
) -> int:
    """Fetch metadata for datasets present in ``observations`` (or the given keys) not cached."""
    conn.execute(DATASET_META_SCHEMA)
    if dataset_keys is None:
        dataset_keys = [
            k
            for (k,) in conn.execute(
                """
                SELECT dataset_key FROM observations
                WHERE dataset_key IS NOT NULL
                  AND dataset_key NOT IN (SELECT dataset_key FROM dataset_meta)
                GROUP BY 1 HAVING count(*) >= ? ORDER BY count(*) DESC
                """,
                [min_records],
            ).fetchall()
        ]
    client = client or make_client()
    limiter = limiter if limiter is not None else RateLimiter(0.2)
    n = 0
    for key in dataset_keys:
        try:
            meta = get_json(client, f"{BASE_URL}/{key}", {}, limiter)
        except ConnectorError:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO dataset_meta VALUES (?, ?, ?, ?, ?)",
            [key, meta.get("title"), meta.get("type"), meta.get("license"), naive_utc(utcnow())],
        )
        n += 1
    return n
