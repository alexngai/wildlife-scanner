"""Automatic, fail-closed sensitivity tier assignment.

The tier is the maximum over all triggers that apply in the place's scopes. Anything unknown,
unresolved, failed or stale yields ``COARSE`` — never ``OPEN``. LLM output is never an input here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from wildlife_scanner.core.observations import SENSITIVE_CONTEXTS
from wildlife_scanner.core.time import utcnow
from wildlife_scanner.policy.tiers import PolicyTier

#: IUCN threat keywords that escalate threatened taxa to WITHHELD.
TAKE_THREATS = frozenset({"hunting", "collection", "collecting", "persecution", "poaching"})


class ConservationStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    authority: str
    """E.g. ``IUCN``, ``ESA``, ``CESA``, ``NatureServe``, ``CA-SSC``, ``CA-FP``, ``CITES``.

    ``IUCN-EQUIV`` is an IUCN-equivalent category assigned by another authority (as iNaturalist
    reports for state and national lists) and is treated like IUCN."""
    code: str
    scope: str = "global"
    """Where the status applies: ``global`` or a region/place scope id (e.g. ``us-ca``)."""
    threats: frozenset[str] = frozenset()
    population: str | None = None
    """Subspecies / DPS / ESU the status applies to, if not the whole taxon."""
    source: str | None = None
    """Where the status came from (e.g. ``inaturalist: CDFW threatened``, a citation)."""


class SensitivityInputs(BaseModel):
    """Everything the tier decision may depend on. ``None`` means "not looked up" (fail closed)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    taxon_resolved: bool
    statuses: tuple[ConservationStatus, ...] | None = None
    inat_geoprivacy: str | None = None
    ebird_sensitive: bool | None = None
    poaching_target: bool = False
    contexts: frozenset[str] = frozenset()
    lookups_failed: tuple[str, ...] = ()
    stale_sources: tuple[str, ...] = ()


class TierDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: PolicyTier
    reasons: tuple[str, ...]
    inputs: SensitivityInputs
    decided_at: datetime = Field(default_factory=utcnow)


_NS_RANK = re.compile(r"^[GTSN]([1-5HX])", re.IGNORECASE)


def _status_tier(s: ConservationStatus) -> tuple[PolicyTier, str] | None:
    auth = s.authority.upper()
    code = s.code.strip().upper()
    label = f"{s.authority}:{s.code}" + (f" ({s.population})" if s.population else "")
    if auth in {"IUCN", "IUCN-EQUIV"}:
        if code in {"EX", "EW"}:
            return PolicyTier.WITHHELD, f"{label}: extinct/extinct in the wild"
        if code in {"VU", "EN", "CR"} and s.threats & TAKE_THREATS:
            threats = ", ".join(sorted(s.threats & TAKE_THREATS))
            return PolicyTier.WITHHELD, f"{label} with take threats ({threats})"
        if code in {"EN", "CR"}:
            return PolicyTier.COARSE, label
        if code in {"NT", "VU"}:
            return PolicyTier.GENERALIZED, label
        if code == "DD":
            return PolicyTier.GENERALIZED, f"{label}: data deficient"
        return None
    if auth in {"ESA", "CESA"} or auth.endswith("-ESA"):
        if code in {"E", "T", "EN", "TH", "ENDANGERED", "THREATENED"}:
            return PolicyTier.COARSE, label
        if code in {"C", "CANDIDATE"}:
            # CESA candidates receive full protection; ESA candidates do not.
            tier = PolicyTier.COARSE if auth == "CESA" else PolicyTier.GENERALIZED
            return tier, label
        return None
    if auth == "NATURESERVE":
        m = _NS_RANK.match(code)
        if not m:
            return None
        rank = m.group(1)
        if rank in {"H", "X", "1", "2"}:
            return PolicyTier.COARSE, label
        if rank == "3":
            return PolicyTier.GENERALIZED, label
        return None
    if auth == "CITES":
        return {
            "I": (PolicyTier.WITHHELD, label),
            "II": (PolicyTier.COARSE, label),
            "III": (PolicyTier.GENERALIZED, label),
        }.get(code)
    if auth == "CA-FP":  # California Fully Protected
        return PolicyTier.COARSE, label
    if auth == "CA-SSC":  # California Species of Special Concern
        return PolicyTier.GENERALIZED, label
    # Unknown authority: record it conservatively rather than ignore it.
    return PolicyTier.GENERALIZED, f"{label}: unrecognized authority"


def assign_tier(inputs: SensitivityInputs, scopes: Iterable[str] = ("global",)) -> TierDecision:
    """Fail-closed tier from statuses, geoprivacy, sensitive lists and life-stage context."""
    scopes = set(scopes)
    tier = PolicyTier.OPEN
    reasons: list[str] = []

    def raise_to(t: PolicyTier, why: str) -> None:
        nonlocal tier
        tier = max(tier, t)
        reasons.append(f"{t.name}: {why}")

    if not inputs.taxon_resolved:
        raise_to(PolicyTier.COARSE, "taxon not resolved")
    if inputs.statuses is None:
        raise_to(PolicyTier.COARSE, "conservation statuses not looked up")
    if inputs.lookups_failed:
        raise_to(PolicyTier.COARSE, f"lookups failed: {', '.join(inputs.lookups_failed)}")
    if inputs.stale_sources:
        raise_to(PolicyTier.COARSE, f"stale sources: {', '.join(inputs.stale_sources)}")

    for status in inputs.statuses or ():
        if status.scope != "global" and status.scope not in scopes:
            continue
        result = _status_tier(status)
        if result is not None:
            raise_to(*result)

    geo = (inputs.inat_geoprivacy or "").lower()
    if geo == "private":
        raise_to(PolicyTier.WITHHELD, "iNaturalist taxon geoprivacy: private")
    elif geo == "obscured":
        raise_to(PolicyTier.COARSE, "iNaturalist taxon geoprivacy: obscured")

    if inputs.ebird_sensitive:
        raise_to(PolicyTier.COARSE, "eBird sensitive species")
    if inputs.poaching_target:
        raise_to(PolicyTier.WITHHELD, "known poaching/collection target")
    sensitive = inputs.contexts & SENSITIVE_CONTEXTS
    if sensitive:
        raise_to(PolicyTier.WITHHELD, f"sensitive context: {', '.join(sorted(sensitive))}")

    if not reasons:
        reasons.append("OPEN: no triggers; taxon resolved and lookups fresh")
    return TierDecision(tier=tier, reasons=tuple(reasons), inputs=inputs)
