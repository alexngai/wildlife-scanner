"""Fetch GBIF event ids for records whose stored date can't be trusted.

Some publishers stamp a placeholder ``eventDate`` (e.g. a release date) on records whose real
date survives only in ``eventID`` (``SAN_MATEO_KELP_20201008_OUTER_2_swath``). Snapshots taken
before ``eventid`` was kept in the store lack it, so this pages the occurrence search API for
the affected records and returns ``(gbifID, eventID)`` pairs.

The search API stops paging at 100,000 records, so the bounding box is split recursively until
each piece is below that.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import httpx

from wildlife_radar.connectors.base import RateLimiter, get_json, make_client

SEARCH_URL = "https://api.gbif.org/v1/occurrence/search"
PAGE = 300
MAX_OFFSET = 100_000

BBox = tuple[float, float, float, float]


def _params(dataset_key: str, event_date: str, bbox: BBox) -> dict:
    lon_min, lat_min, lon_max, lat_max = bbox
    return {
        "datasetKey": dataset_key,
        "eventDate": event_date,
        "decimalLatitude": f"{lat_min},{lat_max}",
        "decimalLongitude": f"{lon_min},{lon_max}",
    }


def _count(client: httpx.Client, params: dict, limiter: RateLimiter | None) -> int:
    return int(get_json(client, SEARCH_URL, {**params, "limit": 0}, limiter).get("count", 0))


def partitions(
    client: httpx.Client,
    dataset_key: str,
    event_date: str,
    bbox: BBox,
    limiter: RateLimiter | None = None,
    depth: int = 0,
) -> list[tuple[dict, int]]:
    """``(params, count)`` pieces of ``bbox``, each small enough to page through."""
    params = _params(dataset_key, event_date, bbox)
    n = _count(client, params, limiter)
    if n == 0:
        return []
    if n < MAX_OFFSET - PAGE or depth >= 12:
        return [(params, n)]
    lon_min, lat_min, lon_max, lat_max = bbox
    lon_mid, lat_mid = (lon_min + lon_max) / 2, (lat_min + lat_max) / 2
    # Range filters are inclusive; nudge the upper edges so no record is counted twice.
    eps = 1e-7
    quads = [
        (lon_min, lat_min, lon_mid - eps, lat_mid - eps),
        (lon_mid, lat_min, lon_max, lat_mid - eps),
        (lon_min, lat_mid, lon_mid - eps, lat_max),
        (lon_mid, lat_mid, lon_max, lat_max),
    ]
    out: list[tuple[dict, int]] = []
    for quad in quads:
        out += partitions(client, dataset_key, event_date, quad, limiter, depth + 1)
    return out


def fetch_event_ids(
    dataset_key: str,
    event_date: str,
    bbox: BBox,
    *,
    client: httpx.Client | None = None,
    limiter: RateLimiter | None = None,
    workers: int = 4,
) -> Iterator[tuple[str, str]]:
    """Yield ``(gbifID, eventID)`` for records of ``dataset_key`` dated ``event_date``."""
    client = client or make_client(timeout=60)
    pieces = partitions(client, dataset_key, event_date, bbox, limiter)
    pages = [(params, offset) for params, n in pieces for offset in range(0, n, PAGE)]

    def page(job: tuple[dict, int]) -> list[tuple[str, str]]:
        params, offset = job
        payload = get_json(client, SEARCH_URL, {**params, "limit": PAGE, "offset": offset}, limiter)
        return [
            (str(r["key"]), r["eventID"])
            for r in payload.get("results") or []
            if r.get("key") and r.get("eventID")
        ]

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for rows in pool.map(page, pages):
            yield from rows
