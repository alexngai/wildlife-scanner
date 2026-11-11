"""Effective tier for (taxon, region, date): automatic tier + profile + windows + overrides.

Rules:
- Raises (profile defaults, seasonal windows, raising overrides) apply automatically.
- Lowering below the automatic/profile tier requires an override with ≥2 distinct approvers, a
  written rationale and an unexpired review date. Anything else is ignored and reported.
- Seasonal windows are applied after lowering overrides, so they can never be undone by one.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wildlife_radar.core.time import ensure_utc, in_seasonal_window, parse_mmdd
from wildlife_radar.policy.tiers import PolicyTier


class TierWindow(BaseModel):
    """Seasonal raise, e.g. spawning season (``03-15`` → ``06-15``). Inclusive; may wrap."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: str
    end: str
    tier: PolicyTier
    regions: tuple[str, ...] | None = None
    """Region ids where the window applies; ``None`` = everywhere."""
    reason: str = ""

    @field_validator("start", "end")
    @classmethod
    def _mmdd(cls, v: str) -> str:
        parse_mmdd(v)
        return v

    def active(self, d: date, region: str | None) -> bool:
        if self.regions is not None and region not in self.regions:
            return False
        return in_seasonal_window(d, self.start, self.end)


class TierOverride(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    taxon_id: str
    tier: PolicyTier
    region: str | None = None
    """Region the override applies to; ``None`` = everywhere."""
    rationale: str = ""
    approvers: tuple[str, ...] = ()
    expires_at: datetime | None = None
    mode: str | None = None
    """Optional product mode for this region, e.g. ``viewing`` or ``awareness``."""

    @field_validator("expires_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else ensure_utc(v)

    def lowering_problems(self, now: datetime) -> list[str]:
        problems = []
        if len(set(self.approvers)) < 2:
            problems.append("needs ≥2 distinct approvers")
        if not self.rationale.strip():
            problems.append("needs a written rationale")
        if self.expires_at is None:
            problems.append("needs an expiry/review date")
        elif self.expires_at <= ensure_utc(now):
            problems.append("expired")
        return problems


class EffectiveTier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: PolicyTier
    reasons: tuple[str, ...]
    ignored: tuple[str, ...] = ()
    mode: str | None = None


def resolve_tier(
    *,
    auto_tier: PolicyTier,
    taxon_id: str,
    on: date,
    region: str | None,
    now: datetime,
    profile_default: PolicyTier | None = None,
    windows: Iterable[TierWindow] = (),
    overrides: Iterable[TierOverride] = (),
    auto_reasons: Iterable[str] = (),
) -> EffectiveTier:
    reasons = list(auto_reasons) or [f"automatic tier {auto_tier.name}"]
    ignored: list[str] = []
    base = auto_tier
    if profile_default is not None and profile_default > base:
        base = profile_default
        reasons.append(f"profile default raises to {profile_default.name}")

    mode: str | None = None
    applicable = [
        o for o in overrides if o.taxon_id == taxon_id and (o.region is None or o.region == region)
    ]
    lowerings = []
    raises = []
    for o in applicable:
        if o.tier < base:
            problems = o.lowering_problems(now)
            if problems:
                ignored.append(
                    f"override to {o.tier.name} in {o.region or 'all regions'} ignored: "
                    + "; ".join(problems)
                )
            else:
                lowerings.append(o)
        else:
            raises.append(o)

    tier = base
    if lowerings:
        # Several valid lowerings: take the most conservative one.
        chosen = max(lowerings, key=lambda o: o.tier)
        tier = chosen.tier
        mode = chosen.mode
        reasons.append(
            f"approved override lowers to {chosen.tier.name} "
            f"({', '.join(sorted(set(chosen.approvers)))}): {chosen.rationale}"
        )
    for o in raises:
        if o.tier > tier:
            reasons.append(f"override raises to {o.tier.name}: {o.rationale or 'no rationale'}")
        tier = max(tier, o.tier)
        mode = o.mode or mode
    for w in windows:
        if w.active(on, region) and w.tier > tier:
            tier = w.tier
            reasons.append(f"seasonal window {w.start}..{w.end} raises to {w.tier.name}")
    return EffectiveTier(tier=tier, reasons=tuple(reasons), ignored=tuple(ignored), mode=mode)


class TierTable(BaseModel):
    """Precomputed effective tiers keyed by taxon (for a given region and date)."""

    model_config = ConfigDict(extra="forbid")

    tiers: dict[str, PolicyTier] = Field(default_factory=dict)
    default: PolicyTier = PolicyTier.COARSE

    def get(self, taxon_id: str | None) -> PolicyTier:
        if taxon_id is None:
            return max(self.default, PolicyTier.COARSE)
        return self.tiers.get(taxon_id, self.default)
