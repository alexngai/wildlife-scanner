"""Hourly observation counts from iNaturalist's histogram endpoint (no records downloaded).

``GET /v1/observations/histogram?interval=hour&date_field=observed`` returns, for every UTC
hour in the date range, how many verifiable observations of the taxon were made in the
bounding box (records with a time only; ~90% have one). One request covers a year, so a
taxon's whole history takes ~15 requests. These counts drive the time-of-day and tide-stage
indices (conditions/timed.py); the GBIF snapshot carries dates only.

Taxa are given as iNaturalist taxon ids: a name query matches only records identified at
exactly that name (e.g. "Actinopterygii" alone), not the clade.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime

import httpx

from wildlife_scanner.connectors.base import RateLimiter, get_json, make_client

BASE_URL = "https://api.inaturalist.org/v1"

#: iNaturalist clades whose records stand in for observing effort per taxon group (the
#: groups of core/taxa.py; ids checked against the live API, 2026-11-12).
GROUP_TAXA: dict[str, tuple[str, ...]] = {
    "birds": ("3",),  # Aves
    "fishes": ("47178", "47273"),  # Actinopterygii, Elasmobranchii
    "mammals": ("40151",),  # Mammalia
    "herps": ("26036", "20978"),  # Reptilia, Amphibia
    "insects": ("47158",),  # Insecta
    "mollusks": ("47115",),  # Mollusca
    "plants": ("47126",),  # Plantae
}


class InatHistogram:
    def __init__(self, client: httpx.Client | None = None, limiter: RateLimiter | None = None):
        self.client = client or make_client(timeout=60)
        self.limiter = limiter if limiter is not None else RateLimiter(1.0)

    def hourly(
        self,
        taxon_ids: Iterable[str],
        bbox: tuple[float, float, float, float],
        start: date,
        end: date,
    ) -> dict[datetime, int]:
        """Non-zero counts per UTC hour (``start``..``end`` inclusive)."""
        lon_min, lat_min, lon_max, lat_max = bbox
        out: dict[datetime, int] = {}
        for year in range(start.year, end.year + 1):
            d1, d2 = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            payload = get_json(
                self.client,
                f"{BASE_URL}/observations/histogram",
                {
                    "taxon_id": ",".join(taxon_ids),
                    "swlat": lat_min,
                    "swlng": lon_min,
                    "nelat": lat_max,
                    "nelng": lon_max,
                    "verifiable": "true",
                    "date_field": "observed",
                    "interval": "hour",
                    "d1": d1.isoformat(),
                    "d2": d2.isoformat(),
                },
                self.limiter,
                retries=4,
            )
            for stamp, n in ((payload.get("results") or {}).get("hour") or {}).items():
                if n:
                    t = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)
                    out[t] = out.get(t, 0) + int(n)
        return out
