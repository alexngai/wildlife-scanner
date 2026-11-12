"""Pre-publication tier audit: look for signals that a taxon's tier is too low.

The tier pipeline fails closed on *missing* information, but it can still under-protect when
information is present yet never reaches it: a curated status keyed by an old name, a status
iNaturalist reports without an IUCN equivalent, a threatened category only Wikidata knows.
Each of these happened, or nearly happened, on real data (docs/research/09). The audit
cross-checks the tier table against every status signal in the store and reports findings by
severity; ``audit-tiers`` exits non-zero on any ``high`` finding so it can gate deployment.

Checks:

- ``high`` — an OPEN taxon with: a threatened IUCN category (VU/EN/CR/EW) on Wikidata; an
  in-scope iNaturalist status that has no IUCN equivalent; observed obscured geoprivacy.
- ``high`` — a curated status entry that matches no taxon in the region while a taxon with the
  same epithet in another genus exists (a probable rename the aliases missed).
- ``medium`` — an OPEN taxon threatened (VU or worse, by iNaturalist's IUCN equivalent) in a
  place outside the region's scopes (range-edge species worth a look).
- ``info`` — taxa held at COARSE only because lookups failed; curated entries for taxa absent
  from the region.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass

import duckdb

from wildlife_radar.policy.statuses import StatusLookup, identity_crosswalk
from wildlife_radar.policy.tiers import PolicyTier

THREATENED = {"VU", "EN", "CR", "EW"}
_INAT_THREATENED = re.compile(r"\b(endangered|threatened|vulnerable|critically)\b", re.I)
_NS_SENSITIVE = re.compile(r"^[GTSN][12HX]", re.I)


@dataclass(frozen=True)
class Finding:
    severity: str
    check: str
    taxon_id: str
    detail: str


def _table_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
        ).fetchone()[0]
    )


def audit_tiers(
    conn: duckdb.DuckDBPyConnection,
    region_id: str,
    curated_taxon_ids: Iterable[str] = (),
) -> list[Finding]:
    if not _table_exists(conn, "tiers"):
        return [Finding("high", "no_tier_table", "-", "build-tiers has not run")]
    tiers = {
        t: (PolicyTier(tier), json.loads(reasons))
        for t, tier, reasons in conn.execute(
            "SELECT taxon_id, tier, reasons FROM tiers WHERE region_id = ?", [region_id]
        ).fetchall()
    }
    names = dict(
        conn.execute(
            "SELECT taxon_id, any_value(scientific_name) FROM prior_taxa WHERE region_id = ? "
            "GROUP BY 1",
            [region_id],
        ).fetchall()
    )
    findings: list[Finding] = []
    open_taxa = {t for t, (tier, _) in tiers.items() if tier == PolicyTier.OPEN}

    # Wikidata IUCN categories from the identity crosswalk.
    if _table_exists(conn, "taxon_identity"):
        categories = dict(
            conn.execute(
                "SELECT query_name, record->>'$.iucn_category' FROM taxon_identity "
                "WHERE record->>'$.iucn_category' IS NOT NULL"
            ).fetchall()
        )
        for t in sorted(open_taxa):
            cat = categories.get(names.get(t) or "")
            if cat in THREATENED:
                findings.append(
                    Finding("high", "open_but_threatened_on_wikidata", t, f"IUCN {cat} (Wikidata)")
                )

    # iNaturalist lookups: unmapped in-scope statuses and threatened out-of-scope statuses.
    if _table_exists(conn, "status_cache"):
        for t, payload in conn.execute(
            "SELECT taxon_id, payload FROM status_cache WHERE provider = 'inaturalist'"
        ).fetchall():
            if t not in open_taxa:
                continue
            lookup = StatusLookup.model_validate_json(payload)
            for status in lookup.unmapped:
                # Threat words make it high; other unknown statuses still deserve a look.
                severity = "high" if _INAT_THREATENED.search(status) else "medium"
                findings.append(Finding(severity, "open_with_unmapped_status", t, status))
            for status in lookup.statuses:
                if status.authority == "NatureServe" and _NS_SENSITIVE.match(status.code):
                    findings.append(
                        Finding(
                            "high",
                            "open_with_sensitive_natureserve_rank",
                            t,
                            f"NatureServe {status.code} ({status.scope})",
                        )
                    )
            elsewhere = [s for s in lookup.ignored if _INAT_THREATENED.search(s)]
            if elsewhere:
                findings.append(
                    Finding("medium", "threatened_elsewhere", t, "; ".join(elsewhere[:3]))
                )

    # Observed obscured geoprivacy should always have raised the tier.
    for (t,) in conn.execute(
        "SELECT DISTINCT taxon_id FROM observations WHERE taxon_geoprivacy IN "
        "('obscured', 'private') AND taxon_id IS NOT NULL"
    ).fetchall():
        if t in open_taxa:
            findings.append(Finding("high", "open_but_obscured", t, "observed taxon geoprivacy"))

    # Curated entries that reach no taxon in the region.
    crosswalk = identity_crosswalk(conn)
    reachable = set(tiers)
    for name in names.values():
        reachable.update(crosswalk.get(name or "", (None, ()))[1])
    epithets: dict[str, list[str]] = {}
    for t in tiers:
        if "-" in t:
            epithets.setdefault(t.rsplit("-", 1)[1], []).append(t)
    for curated in sorted(set(curated_taxon_ids)):
        if curated in reachable:
            continue
        lookalikes = [t for t in epithets.get(curated.rsplit("-", 1)[-1], []) if t != curated]
        if lookalikes:
            findings.append(
                Finding(
                    "high",
                    "curated_status_unmatched",
                    curated,
                    f"no taxon with this id or alias; same epithet: {', '.join(lookalikes)}",
                )
            )
        else:
            findings.append(
                Finding("info", "curated_status_absent", curated, "taxon not in this region")
            )

    failed = [
        t
        for t, (tier, reasons) in tiers.items()
        if tier == PolicyTier.COARSE and any("lookups failed" in r for r in reasons)
    ]
    if failed:
        findings.append(
            Finding(
                "info",
                "fail_closed_lookups",
                "-",
                f"{len(failed)} taxa held at COARSE because status lookups failed",
            )
        )
    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(findings, key=lambda f: (order[f.severity], f.check, f.taxon_id))


def summarize(findings: list[Finding]) -> dict:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return {"counts": counts, "findings": [asdict(f) for f in findings]}
