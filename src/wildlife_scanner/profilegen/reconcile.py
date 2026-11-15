"""Reconcile field candidates by precedence, with conflicts, license taint and a review queue.

Precedence (framework.md §4.3 step 7), highest first: human override → authoritative source →
measured curated value / occurrence-derived measurement → imputed curated value → referenced
Wikidata → LLM extraction with verified evidence → taxonomic imputation → unsourced hints.

- Categorical disagreements among sourced candidates are kept and flagged.
- Numeric values (or range midpoints) that differ by more than 2× are flagged.
- Agreement between independent sources raises confidence.
- Guarded paths (policy, status, crosswalk, ...) are refused from every non-human source.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from wildlife_scanner.profilegen.candidates import Candidate, Rank
from wildlife_scanner.profilegen.extract import GUARDED_PREFIXES
from wildlife_scanner.profiles.schema import Conflict, Provenance

OPEN_LICENSES = frozenset({"CC0-1.0", "CC-BY-4.0", "PDM", "public-domain", "CC-BY-3.0"})

#: How much a wrong value would hurt predictions (drives review order).
FIELD_IMPACT = {
    "traits.activity_pattern": 1.0,
    "traits.observed_seasonality": 0.9,
    "traits.migratory": 0.8,
    "traits.habitats": 0.8,
    "traits.depth_m": 0.8,
    "traits.breeding_months": 0.7,
    "traits.home_range_km2": 0.6,
    "traits.elevation_m": 0.5,
    "traits.social_behavior": 0.5,
    "traits.iucn_habitats": 0.5,
    "traits.observed_diel": 0.4,
    "traits.diet": 0.3,
    "traits.habitat_use": 0.3,
    "traits.ecosystems": 0.3,
    "traits.body_mass_g": 0.2,
    "traits.body_length_mm": 0.2,
}


class Reconciled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    conflicts: list[Conflict] = Field(default_factory=list)
    licenses: list[str] = Field(default_factory=list)
    open_variant: bool = True
    review_queue: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if (
        isinstance(value, list | tuple)
        and len(value) == 2
        and all(isinstance(v, int | float) for v in value)
    ):
        return (float(value[0]) + float(value[1])) / 2
    return None


def _norm(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(sorted(map(str, value)))
    if isinstance(value, dict):
        return tuple(sorted((k, str(v)) for k, v in value.items()))
    return value


def _guarded(field: str) -> bool:
    return field.split(".")[0] in GUARDED_PREFIXES


def reconcile(candidates: list[Candidate], locked: dict[str, Any] | None = None) -> Reconciled:
    out = Reconciled()
    locked = locked or {}
    by_field: dict[str, list[Candidate]] = defaultdict(list)
    for c in candidates:
        if _guarded(c.field) and c.rank != Rank.HUMAN:
            out.notes.append(f"refused {c.field} from {c.source} ({c.provenance.method})")
            continue
        by_field[c.field].append(c)
    for field in sorted(set(by_field) | set(locked)):
        if field in locked:
            if locked[field] is not None:
                out.values[field] = locked[field]
            continue
        cands = sorted(by_field[field], key=lambda c: (c.rank, -(c.provenance.confidence or 0)))
        best = cands[0]
        prov = best.provenance.model_copy()
        sourced = [c for c in cands if c.rank <= Rank.EXTRACTED]
        distinct = {_norm(c.value) for c in sourced}
        nums = [n for n in (_number(c.value) for c in sourced) if n is not None]
        conflict = None
        if len(nums) >= 2 and min(nums) > 0 and max(nums) / min(nums) > 2:
            conflict = "numeric"
        elif len(distinct) > 1 and not nums:
            conflict = "categorical"
        if conflict:
            out.conflicts.append(
                Conflict(
                    field=field,
                    values=[c.value for c in sourced],
                    sources=[c.source for c in sourced],
                    kind=conflict,
                )
            )
        else:
            agreeing = {c.source for c in sourced if _norm(c.value) == _norm(best.value)}
            if len(agreeing) > 1:
                prov.confidence = min(0.95, (prov.confidence or 0.5) + 0.15 * (len(agreeing) - 1))
        out.values[field] = best.value
        out.provenance[field] = prov
    out.licenses = sorted(
        {
            lic.strip()
            for p in out.provenance.values()
            for lic in (p.license or "").split(",")
            if lic.strip()
        }
    )
    out.open_variant = all(lic in OPEN_LICENSES for lic in out.licenses)
    conflicted = {c.field for c in out.conflicts}

    def priority(field: str) -> float:
        uncertainty = 1 - (out.provenance[field].confidence or 0.3)
        if field in conflicted:
            uncertainty = min(1.0, uncertainty + 0.4)
        return uncertainty * FIELD_IMPACT.get(field, 0.3)

    out.review_queue = sorted(out.provenance, key=priority, reverse=True)
    out.notes += sanity_checks(out.values)
    return out


def sanity_checks(values: dict[str, Any]) -> list[str]:
    """Cross-checks between trait values and what the occurrence data shows."""
    notes = []
    activity = values.get("traits.activity_pattern")
    diel = (values.get("traits.observed_diel") or {}).get("pattern")
    if activity and diel and {activity, diel} == {"diurnal", "nocturnal"}:
        notes.append(
            f"activity_pattern {activity!r} contradicts observed records ({diel!r}); "
            "observed times are observer-biased, so review both"
        )
    seasonal = (values.get("traits.observed_seasonality") or {}).get("pattern")
    if values.get("traits.migratory") is True and seasonal == "year_round":
        notes.append(
            "listed as migratory but present year-round in the region "
            "(resident population, or overlapping migrants?)"
        )
    if values.get("traits.migratory") is False and seasonal == "seasonal_visitor":
        notes.append("listed as non-migratory but absent part of the year in the region")
    return notes
