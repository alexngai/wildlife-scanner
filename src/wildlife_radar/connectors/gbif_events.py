"""Fetch GBIF event ids for records whose stored date can't be trusted.

Some publishers stamp a placeholder ``eventDate`` (e.g. a release date) on records whose real
date survives only in ``eventID`` (``SAN_MATEO_KELP_20201008_OUTER_2_swath``). Snapshots taken
before ``eventid`` was kept in the store lack it, so this pages the occurrence search API for
the affected records and returns ``(gbifID, eventID)`` pairs.

Records are fetched event by event (events are listed with a facet query), which keeps page
offsets shallow: the search API is slow at deep offsets and stops at 100,000.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import httpx

from wildlife_radar.connectors.base import RateLimiter, get_json, make_client

SEARCH_URL = "https://api.gbif.org/v1/occurrence/search"
PAGE = 300

BBox = tuple[float, float, float, float]


def _params(dataset_key: str, event_date: str, bbox: BBox) -> dict:
    lon_min, lat_min, lon_max, lat_max = bbox
    return {
        "datasetKey": dataset_key,
        "eventDate": event_date,
        "decimalLatitude": f"{lat_min},{lat_max}",
        "decimalLongitude": f"{lon_min},{lon_max}",
    }


def _get(client: httpx.Client, params: dict, limiter: RateLimiter | None) -> dict:
    """Long paging runs meet transient resets and rate limits: retry with backoff."""
    return get_json(client, SEARCH_URL, params, limiter, retries=8)


def event_ids(
    client: httpx.Client,
    dataset_key: str,
    event_date: str,
    bbox: BBox,
    limiter: RateLimiter | None = None,
) -> list[tuple[str, int]]:
    """``(eventID, records)`` for the dataset's records on ``event_date`` inside ``bbox``."""
    out: list[tuple[str, int]] = []
    offset = 0
    while True:
        payload = _get(
            client,
            {
                **_params(dataset_key, event_date, bbox),
                "limit": 0,
                "facet": "eventId",
                "facetLimit": 1000,
                "facetOffset": offset,
            },
            limiter,
        )
        counts = (payload.get("facets") or [{}])[0].get("counts") or []
        out += [(c["name"], int(c["count"])) for c in counts]
        if len(counts) < 1000:
            return out
        offset += 1000


def fetch_events(
    dataset_key: str,
    events: list[tuple[str, int]],
    *,
    client: httpx.Client | None = None,
    limiter: RateLimiter | None = None,
    workers: int = 4,
) -> list[tuple[str, str]]:
    """``(gbifID, eventID)`` for every record of the given ``(eventID, records)`` events."""
    client = client or make_client(timeout=60)
    pages = [(name, offset) for name, n in events for offset in range(0, n, PAGE)]

    def page(job: tuple[str, int]) -> list[tuple[str, str]]:
        name, offset = job
        payload = _get(
            client,
            {"datasetKey": dataset_key, "eventId": name, "limit": PAGE, "offset": offset},
            limiter,
        )
        return [
            (str(r["key"]), r["eventID"])
            for r in payload.get("results") or []
            if r.get("key") and r.get("eventID")
        ]

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return [row for rows in pool.map(page, pages) for row in rows]


def fetch_event_ids(
    dataset_key: str,
    event_date: str,
    bbox: BBox,
    *,
    client: httpx.Client | None = None,
    limiter: RateLimiter | None = None,
    workers: int = 4,
) -> Iterator[tuple[str, str]]:
    """Yield ``(gbifID, eventID)`` for records of ``dataset_key`` dated ``event_date``.

    Deep offsets in the occurrence search are slow (tens of seconds per page), so records are
    fetched per event: list the events (a facet), then page each event's few hundred records.
    """
    client = client or make_client(timeout=60)
    events = event_ids(client, dataset_key, event_date, bbox, limiter)
    yield from fetch_events(dataset_key, events, client=client, limiter=limiter, workers=workers)
