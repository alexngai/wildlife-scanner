"""iNaturalist taxon conservation statuses (an automatic status lookup).

iNaturalist aggregates statuses from many authorities (IUCN, NatureServe, national and state
lists), each with an IUCN-equivalent category, a place scope and a geoprivacy setting that it
applies to observations. Field names follow the public API v1 taxon JSON
(``conservation_statuses[].{iucn, status, authority, geoprivacy, place}``); verify against live
responses before production use.

Statuses scoped to places the region doesn't map (``Region.inat_place_scopes``) are ignored and
reported, because iNaturalist carries lists from many other jurisdictions. iNaturalist's own
obscuring of observations still reaches the policy layer through the observed
``taxon_geoprivacy`` of ingested records.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx

from wildlife_radar.connectors.base import ConnectorError, RateLimiter, get_json, make_client
from wildlife_radar.policy.assign import ConservationStatus
from wildlife_radar.policy.statuses import StatusLookup, TaxonInfo, most_severe_geoprivacy

BASE_URL = "https://api.inaturalist.org/v1"
BATCH = 30

#: iNaturalist's IUCN-equivalent integer codes.
IUCN_EQUIVALENTS = {5: "DD", 10: "LC", 20: "NT", 30: "VU", 40: "EN", 50: "CR", 60: "EW", 70: "EX"}


def parse_taxon_statuses(taxon: dict[str, Any], place_scopes: dict[str, str]) -> StatusLookup:
    statuses: list[ConservationStatus] = []
    geoprivacies: list[str | None] = []
    ignored: list[str] = []
    for cs in taxon.get("conservation_statuses") or []:
        place = cs.get("place")
        if not place:
            scope = "global"
        else:
            ids = [str(place.get("id"))] + [str(x) for x in place.get("ancestor_place_ids") or []]
            scope = next((place_scopes[i] for i in ids if i in place_scopes), None)
            if scope is None:
                ignored.append(
                    f"{cs.get('authority')}: {cs.get('status')} @ place {place.get('id')}"
                )
                continue
        geoprivacies.append(cs.get("geoprivacy"))
        code = IUCN_EQUIVALENTS.get(cs.get("iucn"))
        if code is None:
            continue
        statuses.append(
            ConservationStatus(
                authority="IUCN-EQUIV",
                code=code,
                scope=scope,
                source=f"inaturalist: {cs.get('authority') or 'unknown'} {cs.get('status') or ''}",
            )
        )
    return StatusLookup(
        statuses=tuple(statuses),
        geoprivacy=most_severe_geoprivacy(geoprivacies),
        source="inaturalist",
        ignored=tuple(ignored),
    )


class InatTaxonStatusProvider:
    name = "inaturalist"
    authoritative = True

    def __init__(
        self,
        place_scopes: dict[str, str],
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.place_scopes = place_scopes
        self.client = client or make_client()
        self.limiter = limiter if limiter is not None else RateLimiter(1.0)

    def _resolve_id(self, taxon: TaxonInfo) -> str | None:
        if taxon.inat_taxon_id:
            return taxon.inat_taxon_id
        payload = get_json(
            self.client,
            f"{BASE_URL}/taxa",
            {"q": taxon.scientific_name, "rank": "species", "is_active": "true", "per_page": 10},
            self.limiter,
        )
        for result in payload.get("results") or []:
            if (result.get("name") or "").lower() == taxon.scientific_name.lower():
                return str(result["id"])
        return None

    def lookup_many(self, taxa: Iterable[TaxonInfo]) -> dict[str, StatusLookup | None]:
        out: dict[str, StatusLookup | None] = {}
        by_id: dict[str, TaxonInfo] = {}
        for taxon in taxa:
            try:
                inat_id = self._resolve_id(taxon)
            except ConnectorError:
                out[taxon.taxon_id] = None
                continue
            if inat_id is None:
                out[taxon.taxon_id] = None
            else:
                by_id[inat_id] = taxon
        ids = list(by_id)
        for i in range(0, len(ids), BATCH):
            chunk = ids[i : i + BATCH]
            try:
                payload = get_json(
                    self.client, f"{BASE_URL}/taxa/{','.join(chunk)}", {}, self.limiter
                )
            except ConnectorError:
                for inat_id in chunk:
                    out[by_id[inat_id].taxon_id] = None
                continue
            found = {str(r.get("id")): r for r in payload.get("results") or []}
            for inat_id in chunk:
                taxon = by_id[inat_id]
                record = found.get(inat_id)
                out[taxon.taxon_id] = (
                    parse_taxon_statuses(record, self.place_scopes) if record else None
                )
        return out
