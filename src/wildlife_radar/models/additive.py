"""The additive log-odds structure shared by all species models.

    logit P = prior + Σ f_k(signal_k) + nowcast + detect

Each term's contribution is kept, so every prediction explains itself ("why") and the policy
layer can drop terms (e.g., the nowcast for sensitive tiers) and recompute ``p`` exactly.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

PRIOR = "prior"
NOWCAST = "nowcast"

_EPS = 1e-9


def logit(p: float) -> float:
    p = min(max(p, _EPS), 1 - _EPS)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)


@dataclass(frozen=True)
class AdditiveResult:
    contributions: dict[str, float] = field(default_factory=dict)

    @property
    def log_odds(self) -> float:
        return sum(self.contributions.values())

    @property
    def p(self) -> float:
        return sigmoid(self.log_odds)

    def without(self, terms: Iterable[str]) -> AdditiveResult:
        drop = set(terms)
        return AdditiveResult({k: v for k, v in self.contributions.items() if k not in drop})

    def top_drivers(self, n: int = 3, exclude: Iterable[str] = (PRIOR,)) -> list[tuple[str, float]]:
        skip = set(exclude)
        items = [(k, v) for k, v in self.contributions.items() if k not in skip and v != 0]
        return sorted(items, key=lambda kv: abs(kv[1]), reverse=True)[:n]


def combine(prior_p: float, terms: Mapping[str, float] | None = None) -> AdditiveResult:
    """Start from a prior probability and add log-odds terms."""
    contributions = {PRIOR: logit(prior_p)}
    for name, value in (terms or {}).items():
        if name == PRIOR:
            raise ValueError("'prior' is reserved for the baseline term")
        contributions[name] = float(value)
    return AdditiveResult(contributions)


def recompute_p(contributions: Mapping[str, float], drop: Iterable[str] = ()) -> float:
    """Probability implied by contributions, optionally dropping terms."""
    return AdditiveResult(dict(contributions)).without(drop).p


def lift(p: float, p_region: float) -> float:
    """How much more likely here than in the surrounding region ("special to here")."""
    return p / max(p_region, _EPS)


def anomaly(p_now: float, p_norm: float) -> float:
    """How unusual now is vs. the seasonal norm for this place ("unusual right now")."""
    return p_now / max(p_norm, _EPS)
