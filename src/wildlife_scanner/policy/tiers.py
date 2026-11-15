"""Sensitivity tiers and the output rules each one imposes."""

from __future__ import annotations

from datetime import timedelta
from enum import IntEnum

from pydantic import BaseModel, ConfigDict

from wildlife_scanner.core import spatial
from wildlife_scanner.core.time import Granularity


class PolicyTier(IntEnum):
    OPEN = 0
    GENERALIZED = 1
    COARSE = 2
    WITHHELD = 3


class TierRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: PolicyTier
    h3_res: int | None
    """Finest H3 resolution allowed in outputs; ``None`` = no spatial output at all."""
    time_granularity: Granularity | None
    min_delay: timedelta
    """Minimum age before recent evidence (sightings) may be shown."""
    allow_nowcast: bool
    allow_place_first_special: bool
    """Whether the taxon may appear in place-first 'special to here' / 'unusual now' lists."""
    redact_source_links: bool
    """Drop source URLs/ids, which can reveal precise upstream coordinates."""


TIER_RULES: dict[PolicyTier, TierRule] = {
    PolicyTier.OPEN: TierRule(
        tier=PolicyTier.OPEN,
        h3_res=spatial.RES_LOCAL,  # ~1.4 km edge
        time_granularity=Granularity.HOUR,
        min_delay=timedelta(hours=24),
        allow_nowcast=True,
        allow_place_first_special=True,
        redact_source_links=False,
    ),
    PolicyTier.GENERALIZED: TierRule(
        tier=PolicyTier.GENERALIZED,
        h3_res=spatial.RES_ZONE,  # ~10 km edge
        time_granularity=Granularity.WEEK,
        min_delay=timedelta(days=7),
        allow_nowcast=False,
        allow_place_first_special=True,
        redact_source_links=True,
    ),
    PolicyTier.COARSE: TierRule(
        tier=PolicyTier.COARSE,
        h3_res=spatial.RES_LANDSCAPE,  # ~69 km edge
        time_granularity=Granularity.MONTH,
        min_delay=timedelta(days=30),
        allow_nowcast=False,
        allow_place_first_special=False,
        redact_source_links=True,
    ),
    PolicyTier.WITHHELD: TierRule(
        tier=PolicyTier.WITHHELD,
        h3_res=None,
        time_granularity=None,
        min_delay=timedelta(days=36500),
        allow_nowcast=False,
        allow_place_first_special=False,
        redact_source_links=True,
    ),
}


def rule_for(tier: PolicyTier | int) -> TierRule:
    return TIER_RULES[PolicyTier(tier)]
