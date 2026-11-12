"""Taxon aliases: one canonical id per concept for names the store keeps apart.

Records are keyed by a slug of their scientific name, so a renamed species is split across
ids (``charadrius-nivosus`` and ``anarhynchus-nivosus``). The identity crosswalk
(``profilegen crosswalk``) groups names into concepts by their verified iNaturalist id (or GBIF
key). ``taxon_alias`` maps every non-canonical id of a concept to the canonical one: the id
with the most records, so the dominant current usage wins.

The baseline, tier inputs (geoprivacy) and queries resolve ids through this table. Merging is
conservative for policy: a concept's tier considers every alias's signals.
"""

from __future__ import annotations

import json
from collections import defaultdict

import duckdb

from wildlife_radar.core.taxa import species_id_from_name

ALIAS_SCHEMA = """
CREATE TABLE IF NOT EXISTS taxon_alias (
    alias_id VARCHAR PRIMARY KEY, taxon_id VARCHAR, concept VARCHAR
)
"""


def ensure_alias_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(ALIAS_SCHEMA)


def _concept(record: dict) -> str | None:
    ids = record.get("ids") or {}
    if ids.get("inaturalist") and (record.get("verified") or {}).get("inaturalist"):
        return f"inaturalist:{ids['inaturalist']}"
    if ids.get("gbif"):
        return f"gbif:{ids['gbif']}"
    return None


def build_alias_table(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Rebuild ``taxon_alias`` from cached identities and the store's record counts."""
    ensure_alias_table(conn)
    conn.execute("DELETE FROM taxon_alias")
    has_identities = conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'taxon_identity'"
    ).fetchone()[0]
    if not has_identities:
        return {"concepts_merged": 0, "aliases": 0}
    counts = dict(
        conn.execute(
            "SELECT taxon_id, count(*) FROM observations WHERE taxon_id IS NOT NULL GROUP BY 1"
        ).fetchall()
    )
    members: dict[str, set[str]] = defaultdict(set)
    for query_name, raw in conn.execute("SELECT query_name, record FROM taxon_identity").fetchall():
        record = json.loads(raw)
        concept = _concept(record)
        if not concept:
            continue
        # The queried name plus every name the identity knows (accepted name, synonyms such
        # as an original combination): a renamed species may appear in the store under one
        # that was never queried itself.
        names = [query_name, record.get("accepted_name"), *record.get("synonyms", [])]
        for name in names:
            store_id = species_id_from_name(name, "species") if name else None
            if store_id in counts:
                members[concept].add(store_id)
    rows = []
    for concept, ids in members.items():
        if len(ids) < 2:
            continue
        canonical = max(sorted(ids), key=lambda i: counts[i])
        rows += [(alias, canonical, concept) for alias in sorted(ids) if alias != canonical]
    # An id must not be both an alias and a canonical id of different concepts.
    canonicals = {r[1] for r in rows}
    rows = [r for r in rows if r[0] not in canonicals]
    if rows:
        conn.executemany("INSERT OR REPLACE INTO taxon_alias VALUES (?, ?, ?)", rows)
    return {"concepts_merged": len({r[2] for r in rows}), "aliases": len(rows)}


def alias_map(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """``alias id → canonical id`` (empty if no alias table)."""
    if not conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'taxon_alias'"
    ).fetchone()[0]:
        return {}
    return dict(conn.execute("SELECT alias_id, taxon_id FROM taxon_alias").fetchall())
