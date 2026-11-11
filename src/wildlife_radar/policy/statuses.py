"""Conservation-status providers and the persisted automatic tier table.

Fail-closed bookkeeping:
- Only *authoritative* providers (complete lookups, e.g. iNaturalist taxon statuses) count as
  "statuses looked up". A curated region file only adds statuses; on its own it never makes a
  taxon look checked.
- A provider error, or a cached lookup older than ``max_age``, yields ``lookups_failed`` /
  ``stale_sources`` → at least ``COARSE``.
- Geoprivacy observed on ingested records (iNaturalist's own obscuring) is always an input.

Seasonal windows and profile overrides depend on the date, so they are applied at query time
(``TierService``); this table stores the date-independent automatic decision.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict

from wildlife_radar.core.taxa import species_id_from_name
from wildlife_radar.core.time import utcnow
from wildlife_radar.policy.assign import (
    ConservationStatus,
    SensitivityInputs,
    TierDecision,
    assign_tier,
)
from wildlife_radar.policy.tiers import PolicyTier

TIERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tiers (
    region_id VARCHAR, taxon_id VARCHAR, tier SMALLINT, reasons VARCHAR, decided_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS status_cache (
    provider VARCHAR, taxon_id VARCHAR, payload VARCHAR, fetched_at TIMESTAMP,
    PRIMARY KEY (provider, taxon_id)
);
"""

_GEO_ORDER = {None: 0, "": 0, "open": 0, "obscured": 1, "private": 2}


def most_severe_geoprivacy(values: Iterable[str | None]) -> str | None:
    best: str | None = None
    for v in values:
        v = (v or "").lower() or None
        if _GEO_ORDER.get(v, 1) > _GEO_ORDER.get(best, 0):
            best = v
    return best


class TaxonInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    taxon_id: str
    scientific_name: str
    inat_taxon_id: str | None = None
    aliases: tuple[str, ...] = ()
    """Other internal ids of the same concept (renamed taxa), from the identity crosswalk."""


class StatusLookup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    statuses: tuple[ConservationStatus, ...] = ()
    geoprivacy: str | None = None
    source: str
    ignored: tuple[str, ...] = ()


class StatusProvider(Protocol):
    name: str
    authoritative: bool

    def lookup_many(self, taxa: Iterable[TaxonInfo]) -> dict[str, StatusLookup | None]:
        """``None`` for a taxon means the lookup could not be completed."""
        ...


class StaticStatusProvider:
    """Fixed answers (tests, demos, or an operator-supplied complete list)."""

    name = "static"

    def __init__(
        self, statuses: dict[str, StatusLookup] | None = None, *, authoritative: bool = True
    ) -> None:
        self._statuses = statuses or {}
        self.authoritative = authoritative

    def lookup_many(self, taxa: Iterable[TaxonInfo]) -> dict[str, StatusLookup | None]:
        return {
            t.taxon_id: self._statuses.get(t.taxon_id, StatusLookup(source=self.name)) for t in taxa
        }


class RegionStatusFile:
    """Curated supplementary statuses from ``regions/<id>/statuses.yaml`` (never authoritative)."""

    name = "region-file"
    authoritative = False

    def __init__(self, path: Path) -> None:
        self.path = path
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        self._by_taxon: dict[str, list[ConservationStatus]] = {}
        for entry in (doc or {}).get("statuses", []):
            taxon_id = entry["taxon_id"]
            status = ConservationStatus(
                authority=entry["authority"],
                code=str(entry["code"]),
                scope=entry.get("scope", "global"),
                threats=frozenset(entry.get("threats", [])),
                population=entry.get("population"),
                source=entry.get("source"),
            )
            self._by_taxon.setdefault(taxon_id, []).append(status)

    def lookup_many(self, taxa: Iterable[TaxonInfo]) -> dict[str, StatusLookup | None]:
        return {
            t.taxon_id: StatusLookup(
                statuses=tuple(
                    s
                    for key in dict.fromkeys((t.taxon_id, *t.aliases))
                    for s in self._by_taxon.get(key, ())
                ),
                source=self.name,
            )
            for t in taxa
        }


class CachedStatusProvider:
    """Caches another provider's lookups in DuckDB; entries older than ``max_age`` are stale."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        inner: StatusProvider,
        max_age: timedelta = timedelta(days=90),
        now: datetime | None = None,
    ) -> None:
        self.conn = conn
        self.inner = inner
        self.max_age = max_age
        self.now = now or utcnow()
        self.name = inner.name
        self.authoritative = inner.authoritative
        conn.execute(TIERS_SCHEMA)

    def lookup_many(self, taxa: Iterable[TaxonInfo]) -> dict[str, StatusLookup | None]:
        taxa = list(taxa)
        fresh_after = (self.now - self.max_age).replace(tzinfo=None)
        cached = {
            taxon_id: StatusLookup.model_validate_json(payload)
            for taxon_id, payload in self.conn.execute(
                "SELECT taxon_id, payload FROM status_cache WHERE provider = ? AND fetched_at >= ?",
                [self.name, fresh_after],
            ).fetchall()
        }
        missing = [t for t in taxa if t.taxon_id not in cached]
        fetched = self.inner.lookup_many(missing) if missing else {}
        now_naive = self.now.replace(tzinfo=None)
        rows = [
            (self.name, taxon_id, lookup.model_dump_json(), now_naive)
            for taxon_id, lookup in fetched.items()
            if lookup is not None
        ]
        if rows:
            self.conn.executemany("INSERT OR REPLACE INTO status_cache VALUES (?, ?, ?, ?)", rows)
        return {t.taxon_id: cached.get(t.taxon_id) or fetched.get(t.taxon_id) for t in taxa}


def observed_geoprivacy(conn: duckdb.DuckDBPyConnection) -> dict[str, str | None]:
    rows = conn.execute(
        """
        SELECT taxon_id, list(DISTINCT taxon_geoprivacy) FROM observations
        WHERE taxon_id IS NOT NULL AND taxon_geoprivacy IS NOT NULL GROUP BY taxon_id
        """
    ).fetchall()
    return {taxon_id: most_severe_geoprivacy(values) for taxon_id, values in rows}


def identity_crosswalk(
    conn: duckdb.DuckDBPyConnection,
) -> dict[str, tuple[str | None, tuple[str, ...]]]:
    """``query name → (verified iNaturalist id, alias ids)`` from cached identities."""
    if not conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'taxon_identity'"
    ).fetchone()[0]:
        return {}
    out: dict[str, tuple[str | None, tuple[str, ...]]] = {}
    for name, raw in conn.execute("SELECT query_name, record FROM taxon_identity").fetchall():
        rec = json.loads(raw)
        inat = rec.get("ids", {}).get("inaturalist")
        verified = rec.get("verified", {}).get("inaturalist")
        names = [rec.get("accepted_name"), rec.get("query_name"), *rec.get("synonyms", [])]
        aliases = [rec.get("taxon_id"), *(species_id_from_name(n, "species") for n in names if n)]
        out[name] = (inat if verified else None, tuple(dict.fromkeys(a for a in aliases if a)))
    return out


def build_tier_table(
    conn: duckdb.DuckDBPyConnection,
    *,
    region_id: str,
    scopes: Sequence[str],
    providers: Sequence[StatusProvider],
    now: datetime | None = None,
) -> dict[str, TierDecision]:
    """Automatic tier for every taxon with a baseline in ``region_id``; persisted to ``tiers``."""
    conn.execute(TIERS_SCHEMA)
    now = now or utcnow()
    # The identity crosswalk (profilegen) supplies verified iNaturalist ids, which beat name
    # searches, and aliases, so curated statuses keyed by another name of the concept apply.
    crosswalk = identity_crosswalk(conn)
    taxa = [
        TaxonInfo(
            taxon_id=t,
            scientific_name=name or t,
            inat_taxon_id=inat or crosswalk.get(name or "", (None, ()))[0],
            aliases=crosswalk.get(name or "", (None, ()))[1],
        )
        for t, name, inat in conn.execute(
            "SELECT DISTINCT taxon_id, scientific_name, inat_taxon_id FROM prior_taxa "
            "WHERE region_id = ?",
            [region_id],
        ).fetchall()
    ]
    results: dict[str, list[tuple[StatusProvider, StatusLookup | None]]] = {
        t.taxon_id: [] for t in taxa
    }
    failed_providers: dict[str, list[str]] = {t.taxon_id: [] for t in taxa}
    for provider in providers:
        try:
            answers = provider.lookup_many(taxa)
        except Exception:  # a provider outage must fail closed, not crash the build
            answers = dict.fromkeys(results)
        for taxon_id in results:
            lookup = answers.get(taxon_id)
            results[taxon_id].append((provider, lookup))
            if lookup is None and provider.authoritative:
                failed_providers[taxon_id].append(provider.name)

    observed = observed_geoprivacy(conn)
    decisions: dict[str, TierDecision] = {}
    for taxon_id, answers in results.items():
        looked_up = any(p.authoritative and lk is not None for p, lk in answers)
        statuses = tuple(s for _, lk in answers if lk is not None for s in lk.statuses)
        geoprivacy = most_severe_geoprivacy(
            [observed.get(taxon_id)] + [lk.geoprivacy for _, lk in answers if lk is not None]
        )
        inputs = SensitivityInputs(
            taxon_resolved=True,
            statuses=statuses if looked_up else None,
            inat_geoprivacy=geoprivacy,
            lookups_failed=tuple(failed_providers[taxon_id]) if not looked_up else (),
        )
        decisions[taxon_id] = assign_tier(inputs, scopes=scopes)

    conn.execute("DELETE FROM tiers WHERE region_id = ?", [region_id])
    decided_at = now.replace(tzinfo=None)
    if decisions:
        conn.executemany(
            "INSERT INTO tiers VALUES (?, ?, ?, ?, ?)",
            [
                (region_id, t, int(d.tier), json.dumps(list(d.reasons)), decided_at)
                for t, d in decisions.items()
            ],
        )
    return decisions


class TierService:
    """Effective tier per (taxon, date): automatic tier + profile defaults, windows, overrides."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        region_id: str,
        profiles=None,
        now: datetime | None = None,
    ) -> None:
        self.region_id = region_id
        self.profiles = profiles
        self.now = now
        self._auto = {
            t: PolicyTier(tier)
            for t, tier in conn.execute(
                "SELECT taxon_id, tier FROM tiers WHERE region_id = ?", [region_id]
            ).fetchall()
        }
        self._profile_ids = set(profiles.ids(kind="species")) if profiles else set()
        self._cache: dict[tuple[str, date], PolicyTier] = {}

    def auto(self, taxon_id: str | None) -> PolicyTier:
        if taxon_id is None:
            return PolicyTier.COARSE
        return self._auto.get(taxon_id, PolicyTier.COARSE)

    def get(self, taxon_id: str | None, on: date) -> PolicyTier:
        if taxon_id is None:
            return PolicyTier.COARSE
        key = (taxon_id, on)
        if key not in self._cache:
            tier = self.auto(taxon_id)
            if taxon_id in self._profile_ids:
                profile = self.profiles.resolve(taxon_id)
                tier = profile.effective_tier(
                    tier, region=self.region_id, on=on, now=self.now or utcnow()
                ).tier
            self._cache[key] = tier
        return self._cache[key]
