"""iNaturalist taxon conservation statuses (an automatic status lookup).

iNaturalist aggregates statuses from many authorities (IUCN, NatureServe, national and state
lists), each with an IUCN-equivalent category, a place scope and a geoprivacy setting that it
applies to observations. Field names follow the public API v1 taxon JSON
(``conservation_statuses[].{iucn, status, authority, geoprivacy, place}``); verify against live
responses before production use.

Statuses for places that neither contain the region nor lie inside it are ignored and
reported, because iNaturalist carries lists from many other jurisdictions. iNaturalist's own
obscuring of observations still reaches the policy layer through the observed
``taxon_geoprivacy`` of ingested records.

Raw taxon records are the same for every region, so they can be shared (``RecordCache``, kept
in the global reference store); which statuses apply depends on the region's places, so
parsing always happens per region and parsed lookups are cached only per region.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

import duckdb
import httpx

from wildlife_radar.connectors.base import ConnectorError, RateLimiter, get_json, make_client
from wildlife_radar.core.time import utcnow
from wildlife_radar.policy.assign import ConservationStatus
from wildlife_radar.policy.statuses import StatusLookup, TaxonInfo, most_severe_geoprivacy

BASE_URL = "https://api.inaturalist.org/v1"
BATCH = 30

#: iNaturalist's IUCN-equivalent integer codes.
IUCN_EQUIVALENTS = {5: "DD", 10: "LC", 20: "NT", 30: "VU", 40: "EN", 50: "CR", 60: "EW", 70: "EX"}


def status_scope(
    place: dict[str, Any] | None, place_scopes: dict[str, str], innermost_place: str | None
) -> str | None:
    """Scope a place-scoped status applies to, or ``None`` if it doesn't apply to the region.

    A status applies if its place *contains* the region (its id is one of the region's mapped
    places, e.g. the US or California), or — conservatively — if it lies *inside* the region's
    innermost mapped place (e.g. a county within California). Note ``ancestor_place_ids`` lists
    the places containing the status's place: Michigan's include the US, which must not make a
    Michigan-only status apply in California.
    """
    if not place:
        return "global"
    place_id = str(place.get("id"))
    if place_id in place_scopes:
        return place_scopes[place_id]
    ancestors = {str(x) for x in place.get("ancestor_place_ids") or []}
    if innermost_place is not None and innermost_place in ancestors:
        return place_scopes.get(innermost_place)
    return None


def parse_taxon_statuses(
    taxon: dict[str, Any],
    place_scopes: dict[str, str],
    innermost_place: str | None = None,
) -> StatusLookup:
    statuses: list[ConservationStatus] = []
    geoprivacies: list[str | None] = []
    ignored: list[str] = []
    unmapped: list[str] = []
    for cs in taxon.get("conservation_statuses") or []:
        place = cs.get("place")
        scope = status_scope(place, place_scopes, innermost_place)
        if scope is None:
            ignored.append(f"{cs.get('authority')}: {cs.get('status')} @ place {place.get('id')}")
            continue
        geoprivacies.append(cs.get("geoprivacy"))
        code = IUCN_EQUIVALENTS.get(cs.get("iucn"))
        if code is None:
            authority = cs.get("authority") or ""
            if "natureserve" in authority.lower() and cs.get("status"):
                # NatureServe ranks (S1–S5, G…, N…) have their own tier rules.
                statuses.append(
                    ConservationStatus(
                        authority="NatureServe",
                        code=str(cs["status"]),
                        scope=scope,
                        source=f"inaturalist: {authority}",
                    )
                )
                continue
            # Applies here but has no IUCN equivalent: kept visible for the tier audit.
            unmapped.append(f"{authority}: {cs.get('status')} ({scope})")
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
        unmapped=tuple(unmapped),
    )


OPEN_PHOTO_LICENSES = ("cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa")
"""Licences a representative photo may carry: open, attribution kept. All rights reserved
(``license_code`` null) and the no-derivatives licences are skipped."""
OPEN_DATA_HOST = "inaturalist-open-data.s3.amazonaws.com"


def open_photo(record: dict) -> dict | None:
    """The first openly licensed photo of an iNaturalist taxon record, as published in
    ``taxa.json`` (hotlinked from iNaturalist's open-data bucket; docs/design/static-products.md).

    Walks ``taxon_photos`` in iNaturalist's order: the default photo is often all rights
    reserved. Only photos on the open-data bucket qualify."""
    for tp in record.get("taxon_photos") or []:
        photo = tp.get("photo") or {}
        url = photo.get("url") or ""
        if photo.get("license_code") not in OPEN_PHOTO_LICENSES:
            continue
        if not url.startswith(f"https://{OPEN_DATA_HOST}/photos/") or "/square." not in url:
            continue
        if not photo.get("attribution") or not photo.get("id"):
            continue
        return {
            "url": url,
            "url_medium": url.replace("/square.", "/small."),
            "license": photo["license_code"],
            "attribution": photo["attribution"],
            "source": "iNaturalist",
            "source_url": f"https://www.inaturalist.org/photos/{int(photo['id'])}",
        }
    return None


RECORDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS inat_taxon_records (
    taxon_id VARCHAR PRIMARY KEY, inat_id VARCHAR, record JSON, fetched_at TIMESTAMP
)
"""


class RecordCache:
    """Raw iNaturalist taxon records by our taxon id (region-independent, shareable)."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        max_age: timedelta = timedelta(days=90),
        now: datetime | None = None,
    ) -> None:
        self.conn = conn
        self.max_age = max_age
        self.now = now or utcnow()
        conn.execute(RECORDS_SCHEMA)

    def get_many(self, taxon_ids: list[str]) -> dict[str, dict]:
        if not taxon_ids:
            return {}
        fresh_after = (self.now - self.max_age).replace(tzinfo=None)
        return {
            t: json.loads(record)
            for t, record in self.conn.execute(
                "SELECT taxon_id, record FROM inat_taxon_records "
                "WHERE taxon_id IN (SELECT unnest(?)) AND fetched_at >= ?",
                [taxon_ids, fresh_after],
            ).fetchall()
        }

    def put_many(self, records: dict[str, dict]) -> None:
        if not records:
            return
        now = self.now.replace(tzinfo=None)
        self.conn.executemany(
            "INSERT OR REPLACE INTO inat_taxon_records VALUES (?, ?, ?, ?)",
            [(t, str(r.get("id")), json.dumps(r), now) for t, r in records.items()],
        )


class InatTaxonStatusProvider:
    name = "inaturalist"
    authoritative = True

    def __init__(
        self,
        place_scopes: dict[str, str],
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        innermost_place: str | None = None,
        records: RecordCache | None = None,
    ) -> None:
        self.place_scopes = place_scopes
        self.innermost_place = innermost_place
        self.records = records
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
            retries=4,
        )
        name = taxon.scientific_name.lower()
        # Exact name, or a synonym iNaturalist files under its current name (matched_term).
        hits = {
            str(r["id"])
            for r in payload.get("results") or []
            if r.get("rank", "species") == "species"  # the query already asks for species
            and name in ((r.get("name") or "").lower(), (r.get("matched_term") or "").lower())
        }
        return hits.pop() if len(hits) == 1 else None

    def lookup_many(self, taxa: Iterable[TaxonInfo]) -> dict[str, StatusLookup | None]:
        """Parsed for this provider's region, from cached raw records where fresh."""
        taxa = list(taxa)
        records = self.records.get_many([t.taxon_id for t in taxa]) if self.records else {}
        missing = [t for t in taxa if t.taxon_id not in records]
        fetched = self.fetch_records(missing) if missing else {}
        if self.records:
            self.records.put_many({t: r for t, r in fetched.items() if r is not None})
        records.update(fetched)
        return {
            t.taxon_id: (
                parse_taxon_statuses(records[t.taxon_id], self.place_scopes, self.innermost_place)
                if records.get(t.taxon_id)
                else None
            )
            for t in taxa
        }

    def fetch_records(self, taxa: Iterable[TaxonInfo]) -> dict[str, dict | None]:
        """Raw taxon records from the API; ``None`` where unresolved or the request failed."""
        out: dict[str, dict | None] = {}
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
                    self.client, f"{BASE_URL}/taxa/{','.join(chunk)}", {}, self.limiter, retries=4
                )
            except ConnectorError:
                for inat_id in chunk:
                    out[by_id[inat_id].taxon_id] = None
                continue
            found = {str(r.get("id")): r for r in payload.get("results") or []}
            for inat_id in chunk:
                out[by_id[inat_id].taxon_id] = found.get(inat_id)
        return out
