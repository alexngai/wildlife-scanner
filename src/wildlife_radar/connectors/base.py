"""Shared connector plumbing: HTTP client, rate limiting, query model, errors.

Connectors fetch third-party data at runtime under the operator's own credentials and terms.
No third-party data or keys are ever committed to this repository (see DATA_SOURCES.md).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from wildlife_radar import __version__
from wildlife_radar.core.observations import Observation
from wildlife_radar.core.sources import Source

USER_AGENT_ENV = "WILDLIFE_RADAR_USER_AGENT"


def user_agent() -> str:
    """User-Agent for outbound requests.

    Operators should set ``WILDLIFE_RADAR_USER_AGENT`` to include a contact (many APIs ask for
    one). The default identifies only the software.
    """
    return os.environ.get(USER_AGENT_ENV) or f"wildlife-radar/{__version__}"


def make_client(
    timeout: float = 30.0, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": user_agent(), "Accept": "application/json"},
        timeout=timeout,
        follow_redirects=True,
        transport=transport,
    )


class ConnectorError(RuntimeError):
    pass


class RateLimiter:
    """Enforces a minimum interval between calls (per connector instance)."""

    def __init__(
        self,
        min_interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval_s = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self.min_interval_s - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last = now


def get_json(
    client: httpx.Client,
    url: str,
    params: dict,
    limiter: RateLimiter | None,
    retries: int = 0,
) -> dict:
    """GET JSON. ``retries`` retries connection errors, rate limits (429) and server errors
    (5xx) with exponential backoff; client errors (4xx) are not retried."""
    for attempt in range(retries + 1):
        if limiter is not None:
            limiter.wait()
        try:
            resp = client.get(url, params=params)
        except httpx.HTTPError as exc:
            error = ConnectorError(f"request to {url} failed: {exc}")
        else:
            if resp.status_code == 429:
                error = ConnectorError(f"rate limited by {url} (HTTP 429); slow down")
            elif resp.status_code >= 500:
                error = ConnectorError(f"{url} returned HTTP {resp.status_code}")
            elif resp.status_code >= 400:
                raise ConnectorError(f"{url} returned HTTP {resp.status_code}: {resp.text[:200]}")
            else:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise ConnectorError(f"{url} returned invalid JSON") from exc
        if attempt == retries:
            raise error
        time.sleep(min(60, 2 ** (attempt + 1)))
    raise AssertionError("unreachable")


class ObservationQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    taxon_name: str | None = None
    source_taxon_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    """``(lon_min, lat_min, lon_max, lat_max)``."""
    start: date | None = None
    end: date | None = None
    updated_since: datetime | None = None
    limit: int | None = Field(default=None, gt=0)
    dataset_keys: tuple[str, ...] = ()
    """Only these datasets (sources that support it, e.g. GBIF)."""

    @model_validator(mode="after")
    def _checks(self) -> ObservationQuery:
        if self.taxon_name is None and self.source_taxon_id is None and self.bbox is None:
            raise ValueError("query needs a taxon (taxon_name/source_taxon_id) or a bbox")
        if self.start and self.end and self.end < self.start:
            raise ValueError("end before start")
        if self.bbox is not None:
            lon_min, lat_min, lon_max, lat_max = self.bbox
            if not (lon_min < lon_max and lat_min < lat_max):
                raise ValueError("bbox must be (lon_min, lat_min, lon_max, lat_max)")
        return self


class ObservationConnector(Protocol):
    source: Source

    def fetch(self, query: ObservationQuery) -> Iterator[Observation]: ...
