"""Taxon identity: resolve a name to a concept and cross-database identifiers.

Pipeline (framework.md §4.3 step 1):

1. **GBIF name match** → accepted name, rank, classification and synonym status.
2. **Wikidata crosswalk** (SPARQL, CC0) by accepted name, then by GBIF key → Wikidata item,
   iNaturalist / eBird / NCBI / ITIS / WoRMS / IUCN / Catalogue of Life ids, the English
   Wikipedia article and the referenced IUCN category.
3. **Per-id verification** of the iNaturalist id against iNaturalist itself: the name it
   returns must equal the accepted name or a known synonym. A name that differs is recorded as
   a synonym (taxonomy moves: e.g. *Charadrius nivosus* → *Anarhynchus nivosus*), so status and
   occurrence lookups go by id instead of failing on a name.

Identifiers are only ever written by this resolver, never typed by hand or produced by an LLM.
Results are cached in the ``taxon_identity`` table so bulk runs (every species in a region) stay
polite to the services.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Literal

import duckdb
import httpx
from pydantic import BaseModel, ConfigDict, Field

from wildlife_radar.connectors.base import ConnectorError, RateLimiter, get_json, make_client
from wildlife_radar.core.taxa import species_id_from_name, target_group
from wildlife_radar.core.time import utcnow
from wildlife_radar.storage.observations import naive_utc

GBIF_MATCH_URL = "https://api.gbif.org/v1/species/match"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
INAT_TAXA_URL = "https://api.inaturalist.org/v1/taxa"

#: Wikidata properties pulled by the crosswalk (all CC0).
WIKIDATA_PROPERTIES = {
    "gbif": "P846",
    "inaturalist": "P3151",
    "ebird": "P3444",
    "ncbi": "P685",
    "itis": "P815",
    "worms": "P850",
    "iucn": "P627",
    "col": "P10585",
}

#: Wikidata items for IUCN Red List categories (property P141).
IUCN_CATEGORY_ITEMS = {
    "Q211005": "LC",
    "Q719675": "NT",
    "Q278113": "VU",
    "Q11394": "EN",
    "Q219127": "CR",
    "Q239509": "EW",
    "Q237350": "EX",
    "Q3245245": "DD",
}

IDENTITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS taxon_identity (
    query_name VARCHAR PRIMARY KEY, taxon_id VARCHAR, record JSON, fetched_at TIMESTAMP
)
"""

SPARQL_BATCH = 100


_ENDINGS = re.compile(r"(erum|era|er|us|um|is|a|e|i)$")


def same_epithet(a: str, b: str) -> bool:
    """Epithets equal up to Latin gender agreement (``paxillifer``/``paxillifera``,
    ``cinereus``/``cinerea``), which changes when a species moves genus."""
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    if min(len(a), len(b)) < 5:
        return False
    return _ENDINGS.sub("", a) == _ENDINGS.sub("", b)


def _name_matches(record: dict, trusted: list[str]) -> bool:
    """An iNaturalist record matches if its name is a trusted name, or (at species rank) shares
    a trusted name's epithet up to gender agreement (genus moves, spelling variants)."""
    name = record.get("name") or ""
    if name in trusted:
        return True
    if record.get("rank", "species") != "species" or " " not in name:
        return False
    epithets = [n.split()[-1] for n in trusted if " " in n]
    return any(same_epithet(name.split()[-1], e) for e in epithets)


class TaxonIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    query_name: str
    taxon_id: str | None = None
    """Internal species id (slug of the accepted name)."""
    accepted_name: str | None = None
    rank: str | None = None
    kingdom: str | None = None
    phylum: str | None = None
    class_: str | None = Field(default=None, alias="class")
    order: str | None = None
    family: str | None = None
    genus: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    iconic_taxon: str | None = None
    """iNaturalist iconic taxon (fills gaps in GBIF classifications, e.g. fish classes)."""
    gbif_match: str | None = None
    """GBIF match type (EXACT, FUZZY, HIGHERRANK, NONE) and confidence, e.g. ``EXACT/99``."""
    wikidata: str | None = None
    ids: dict[str, str] = Field(default_factory=dict)
    """Crosswalk ids by scheme (``gbif``, ``inaturalist``, ``ebird``, ...)."""
    verified: dict[str, bool] = Field(default_factory=dict)
    common_name: str | None = None
    wikipedia_title: str | None = None
    iucn_category: str | None = None
    """Referenced Wikidata IUCN category: a status *hint* for raising tiers, never lowering."""
    synonym_sources: dict[str, str] = Field(default_factory=dict)
    """Where each synonym came from: ``gbif``, ``inaturalist`` or ``wikidata``."""
    notes: list[str] = Field(default_factory=list)

    def add_synonym(self, name: str | None, source: str) -> None:
        if name and name not in self.synonyms and name not in (self.accepted_name, self.query_name):
            self.synonyms.append(name)
            self.synonym_sources[name] = source

    @property
    def trusted_names(self) -> list[str]:
        """Names that may verify ids and merge taxa: accepted, queried, and synonyms from GBIF
        or a verified iNaturalist chain. Wikidata synonym links are sometimes wrong (e.g. a
        different species listed as a synonym), so they only ever *raise* protection."""
        return list(
            dict.fromkeys(
                n
                for n in [
                    self.accepted_name,
                    self.query_name,
                    *(
                        s
                        for s in self.synonyms
                        if self.synonym_sources.get(s, "gbif") != "wikidata"
                    ),
                ]
                if n
            )
        )

    @property
    def names(self) -> list[str]:
        """Accepted name, the queried name and known synonyms (for evidence checks)."""
        return list(
            dict.fromkeys(n for n in [self.accepted_name, self.query_name, *self.synonyms] if n)
        )

    @property
    def alias_ids(self) -> list[str]:
        """Internal ids of every known name (stores keyed by name split a renamed concept)."""
        ids = [species_id_from_name(n, "species") for n in self.names]
        return list(dict.fromkeys(i for i in [self.taxon_id, *ids] if i))

    @property
    def resolved(self) -> bool:
        return self.taxon_id is not None

    @property
    def taxon_group(self) -> str:
        return target_group(self.kingdom, self.phylum, self.class_, self.iconic_taxon)


class IdentityResolver:
    def __init__(
        self,
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        *,
        verify_inat: bool = True,
    ) -> None:
        self.client = client or make_client(timeout=60)
        self.limiter = limiter if limiter is not None else RateLimiter(1.0)
        self.verify_inat = verify_inat

    # -- GBIF -----------------------------------------------------------------------------
    def gbif_match(self, name: str) -> TaxonIdentity:
        ident = TaxonIdentity(query_name=name)
        try:
            m = get_json(self.client, GBIF_MATCH_URL, {"name": name, "strict": "true"}, None)
        except ConnectorError as exc:
            ident.notes.append(f"GBIF match failed: {exc}")
            return ident
        match_type = m.get("matchType", "NONE")
        ident.gbif_match = f"{match_type}/{m.get('confidence', 0)}"
        if match_type in ("NONE", "HIGHERRANK") or not m.get("rank"):
            ident.notes.append(f"no species-level GBIF match ({match_type})")
            return ident
        status = (m.get("status") or "").upper()
        synonym = bool(m.get("synonym")) or "SYNONYM" in status or status == "MISAPPLIED"
        if status == "DOUBTFUL":
            ident.notes.append("GBIF marks this name as doubtful")
        accepted = m.get("species") if synonym else m.get("canonicalName")
        if synonym and m.get("canonicalName"):
            ident.synonyms.append(m["canonicalName"])
            ident.synonym_sources[m["canonicalName"]] = "gbif"
        ident.accepted_name = accepted or m.get("canonicalName")
        ident.rank = (m.get("rank") or "").lower() or None
        for field in ("kingdom", "phylum", "order", "family", "genus"):
            setattr(ident, field, m.get(field))
        ident.class_ = m.get("class")
        key = m.get("acceptedUsageKey") if synonym else m.get("usageKey")
        key = m.get("speciesKey") or key
        if key:
            ident.ids["gbif"] = str(key)
        ident.taxon_id = species_id_from_name(ident.accepted_name, ident.rank)
        if ident.taxon_id is None:
            ident.notes.append(f"rank {ident.rank!r} is above species")
        return ident

    # -- Wikidata -------------------------------------------------------------------------
    def _sparql(self, query: str) -> list[dict[str, str]]:
        self.limiter.wait()
        try:
            resp = self.client.post(
                WIKIDATA_SPARQL_URL,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"},
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Wikidata SPARQL failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ConnectorError(f"Wikidata SPARQL returned HTTP {resp.status_code}")
        return [{k: v["value"] for k, v in b.items()} for b in resp.json()["results"]["bindings"]]

    @staticmethod
    def crosswalk_query(values: Sequence[str], by: str) -> str:
        """SPARQL for items whose taxon name (``by="name"``) or GBIF key (``by="gbif"``) is in
        ``values``. Multi-valued properties come back as ``|``-joined lists."""
        literals = " ".join(json.dumps(v) for v in values)
        key_prop = "wdt:P225" if by == "name" else "wdt:P846"
        selects = " ".join(
            f'(GROUP_CONCAT(DISTINCT ?{k}; separator="|") AS ?{k}s)' for k in WIKIDATA_PROPERTIES
        )
        optionals = " ".join(
            f"OPTIONAL {{ ?item wdt:{p} ?{k} }}" for k, p in WIKIDATA_PROPERTIES.items()
        )
        return f"""
SELECT ?key ?item ?name {selects}
  (GROUP_CONCAT(DISTINCT ?status; separator="|") AS ?statuses)
  (GROUP_CONCAT(DISTINCT ?synName; separator="|") AS ?synonymNames)
  (SAMPLE(?article) AS ?wiki) (SAMPLE(?common) AS ?commonName)
WHERE {{
  VALUES ?key {{ {literals} }}
  ?item {key_prop} ?key .
  OPTIONAL {{ ?item wdt:P225 ?name }}
  {optionals}
  OPTIONAL {{ ?item wdt:P141 ?status }}
  OPTIONAL {{ {{ ?item wdt:P1403|wdt:P1420 ?syn }} UNION {{ ?syn wdt:P1420|wdt:P12765 ?item }}
             ?syn wdt:P225 ?synName }}
  OPTIONAL {{ ?item wdt:P1843 ?common FILTER(lang(?common) = "en") }}
  OPTIONAL {{ ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }}
}}
GROUP BY ?key ?item ?name
"""

    def wikidata_rows(self, values: Sequence[str], by: str) -> dict[str, list[dict[str, str]]]:
        out: dict[str, list[dict[str, str]]] = {}
        for i in range(0, len(values), SPARQL_BATCH):
            chunk = list(values[i : i + SPARQL_BATCH])
            for row in self._sparql(self.crosswalk_query(chunk, by)):
                out.setdefault(row["key"], []).append(row)
        return out

    @staticmethod
    def apply_wikidata(ident: TaxonIdentity, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        if len({r["item"] for r in rows}) > 1:
            ident.notes.append(
                "several Wikidata items share this key: "
                + ", ".join(sorted({r["item"].rsplit("/", 1)[-1] for r in rows}))
            )
            # Prefer the item whose taxon name is the accepted name.
            rows = [r for r in rows if r.get("name") == ident.accepted_name] or rows[:1]
        row = rows[0]
        ident.wikidata = row["item"].rsplit("/", 1)[-1]
        for scheme in WIKIDATA_PROPERTIES:
            values = [v for v in (row.get(f"{scheme}s") or "").split("|") if v]
            if not values:
                continue
            if scheme == "gbif" and "gbif" in ident.ids and ident.ids["gbif"] not in values:
                ident.notes.append(f"Wikidata GBIF ids {values} differ from match {ident.ids}")
                continue
            if len(values) > 1:
                ident.notes.append(f"several {scheme} ids on Wikidata: {values}")
            ident.ids.setdefault(scheme, sorted(values)[0])
        categories = [
            IUCN_CATEGORY_ITEMS.get(s.rsplit("/", 1)[-1])
            for s in (row.get("statuses") or "").split("|")
            if s
        ]
        categories = [c for c in categories if c]
        if len(set(categories)) == 1:
            ident.iucn_category = categories[0]
        elif categories:
            ident.notes.append(f"conflicting IUCN categories on Wikidata: {categories}")
        if row.get("wiki"):
            path = httpx.URL(row["wiki"]).path  # percent-decoded
            ident.wikipedia_title = path.rsplit("/wiki/", 1)[-1].replace("_", " ")
        if row.get("commonName"):
            ident.common_name = row["commonName"]
        # Original combination (P1403) and taxon synonyms (P1420, and their reverse links).
        for synonym in (row.get("synonymNames") or "").split("|"):
            ident.add_synonym(synonym, "wikidata")

    # -- iNaturalist ----------------------------------------------------------------------
    def _inat_records(self, ids: list[str]) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for start in range(0, len(ids), 30):
            chunk = ids[start : start + 30]
            payload = get_json(self.client, f"{INAT_TAXA_URL}/{','.join(chunk)}", {}, self.limiter)
            found.update({str(r.get("id")): r for r in payload.get("results") or []})
        return found

    def verify_inat_ids(self, idents: Iterable[TaxonIdentity]) -> None:
        """Check iNaturalist ids against the identity's trusted names; follow an inactive
        concept to its replacement only if the inactive concept itself matches."""
        by_id = {i.ids["inaturalist"]: i for i in idents if "inaturalist" in i.ids}
        try:
            found = self._inat_records(list(by_id))
            moved: dict[str, str] = {}
            for inat_id, record in found.items():
                ident = by_id[inat_id]
                replacements = record.get("current_synonymous_taxon_ids") or []
                if (
                    record.get("is_active") is False
                    and len(replacements) == 1
                    and _name_matches(record, ident.trusted_names)
                ):
                    moved[inat_id] = str(replacements[0])
            current = self._inat_records(sorted(set(moved.values()))) if moved else {}
        except ConnectorError as exc:
            for ident in by_id.values():
                ident.notes.append(f"iNaturalist verification failed: {exc}")
            return
        for inat_id, ident in by_id.items():
            record = found.get(inat_id)
            if record is None:
                ident.verified["inaturalist"] = False
                ident.notes.append(f"iNaturalist id {inat_id} not found")
                continue
            if inat_id in moved and moved[inat_id] in current:
                new_id = moved[inat_id]
                ident.notes.append(f"iNaturalist id {inat_id} is inactive; using {new_id}")
                ident.add_synonym(record.get("name"), "inaturalist")
                ident.ids["inaturalist"] = new_id
                record = current[new_id]
            name = record.get("name") or ""
            if record.get("is_active") is False:
                ident.verified["inaturalist"] = False
                ident.notes.append(f"iNaturalist id {inat_id} ({name!r}) is inactive")
            elif _name_matches(record, ident.trusted_names):
                ident.verified["inaturalist"] = True
                if name not in ident.names:
                    # Same epithet (up to gender agreement), possibly in another genus: a
                    # genus move or a spelling variant.
                    ident.add_synonym(name, "inaturalist")
                    ident.notes.append(f"iNaturalist uses the name {name!r}")
            else:
                ident.verified["inaturalist"] = False
                ident.notes.append(
                    f"iNaturalist id {ident.ids['inaturalist']} is {name!r} ({record.get('rank')})"
                )
            ident.iconic_taxon = record.get("iconic_taxon_name") or ident.iconic_taxon
            if record.get("preferred_common_name"):
                # iNaturalist's preferred name beats Wikidata's arbitrary P1843 sample.
                ident.common_name = record["preferred_common_name"]

    def search_inat(self, idents: Iterable[TaxonIdentity]) -> None:
        """Find iNaturalist ids by name for identities without one.

        Accepts an active species whose name, or the synonym it matched (``matched_term``),
        equals one of the identity's names; verification then runs as for crosswalk ids.
        """
        for ident in idents:
            if "inaturalist" in ident.ids:
                continue
            for name in ident.trusted_names[:3]:
                try:
                    payload = get_json(
                        self.client,
                        INAT_TAXA_URL,
                        {"q": name, "rank": "species", "is_active": "true", "per_page": 10},
                        self.limiter,
                    )
                except ConnectorError:
                    break
                hits = [
                    r
                    for r in payload.get("results") or []
                    if r.get("rank") == "species"
                    and name.lower()
                    in ((r.get("name") or "").lower(), (r.get("matched_term") or "").lower())
                ]
                if len({r["id"] for r in hits}) == 1:
                    ident.ids["inaturalist"] = str(hits[0]["id"])
                    if hits[0].get("name") != name:
                        ident.notes.append(
                            f"iNaturalist lists {name!r} under {hits[0].get('name')!r}"
                        )
                        ident.add_synonym(hits[0]["name"], "inaturalist")
                    break

    # -- Orchestration --------------------------------------------------------------------
    def resolve_many(
        self, names: Sequence[str], *, gbif: Literal["always", "fallback"] = "always"
    ) -> list[TaxonIdentity]:
        """Resolve names. ``gbif="fallback"`` (bulk crosswalks) asks Wikidata first and calls
        the per-name GBIF matcher only for names Wikidata doesn't know."""
        if gbif == "fallback":
            try:
                by_query = self.wikidata_rows(sorted(set(names)), "name")
            except ConnectorError:
                by_query = {}
            idents = []
            for name in names:
                if by_query.get(name):
                    ident = TaxonIdentity(
                        query_name=name,
                        accepted_name=name,
                        rank="species",
                        taxon_id=species_id_from_name(name, "species"),
                    )
                    self.apply_wikidata(ident, by_query[name])
                else:
                    ident = self.gbif_match(name)
                idents.append(ident)
        else:
            idents = [self.gbif_match(n) for n in names]
        resolved = [i for i in idents if i.resolved]
        try:
            todo = [i for i in resolved if i.wikidata is None]
            by_name = self.wikidata_rows(sorted({i.accepted_name for i in todo}), "name")
            for ident in todo:
                self.apply_wikidata(ident, by_name.get(ident.accepted_name, []))
            missing = [i for i in resolved if i.wikidata is None and "gbif" in i.ids]
            if missing:
                by_key = self.wikidata_rows([i.ids["gbif"] for i in missing], "gbif")
                for ident in missing:
                    self.apply_wikidata(ident, by_key.get(ident.ids["gbif"], []))
        except ConnectorError as exc:
            for ident in resolved:
                ident.notes.append(f"Wikidata crosswalk failed: {exc}")
        for ident in resolved:
            if "gbif" in ident.ids:
                ident.verified.setdefault("gbif", True)
        if self.verify_inat:
            self.search_inat(resolved)
            self.verify_inat_ids(resolved)
        return idents

    def resolve(self, name: str) -> TaxonIdentity:
        return self.resolve_many([name])[0]


def save_identities(conn: duckdb.DuckDBPyConnection, idents: Iterable[TaxonIdentity]) -> int:
    """Cache identities keyed by query name (several names may resolve to one concept)."""
    conn.execute(IDENTITY_SCHEMA)
    rows = [
        (i.query_name, i.taxon_id, i.model_dump_json(by_alias=True), naive_utc(utcnow()))
        for i in idents
    ]
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO taxon_identity (query_name, taxon_id, record, fetched_at) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def load_identities(
    conn: duckdb.DuckDBPyConnection, taxon_ids: Iterable[str] | None = None
) -> dict[str, TaxonIdentity]:
    conn.execute(IDENTITY_SCHEMA)
    sql = "SELECT taxon_id, record FROM taxon_identity"
    params: list = []
    if taxon_ids is not None:
        ids = list(taxon_ids)
        if not ids:
            return {}
        sql += " WHERE taxon_id IN (SELECT unnest(?))"
        params = [ids]
    return {
        tid: TaxonIdentity.model_validate_json(rec)
        for tid, rec in conn.execute(sql, params).fetchall()
    }


def verified_inat_ids(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """``query name → verified iNaturalist id`` from cached identities."""
    conn.execute(IDENTITY_SCHEMA)
    rows = conn.execute(
        """
        SELECT query_name, record->>'$.ids.inaturalist' FROM taxon_identity
        WHERE (record->>'$.verified.inaturalist')::BOOLEAN
        """
    ).fetchall()
    return {name: inat for name, inat in rows if inat}


def identity_age(conn: duckdb.DuckDBPyConnection, taxon_id: str) -> datetime | None:
    conn.execute(IDENTITY_SCHEMA)
    row = conn.execute(
        "SELECT max(fetched_at) FROM taxon_identity WHERE taxon_id = ?", [taxon_id]
    ).fetchone()
    return row[0] if row else None
