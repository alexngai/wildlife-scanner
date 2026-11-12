"""Baselines every species model must beat: climatology and persistence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    """One effort unit with a binary outcome (e.g., a dive that did or didn't see the species)."""

    key: Hashable  # e.g., (cell, week_of_year)
    period: int  # sequential period index (e.g., ISO week number since epoch) for persistence
    detected: bool


class Climatology:
    """Detection rate per key (e.g., place × week-of-year), shrunk toward the overall rate.

    ``rate = (k + strength * base) / (n + strength)`` — a Beta-Binomial posterior mean.
    """

    def __init__(self, strength: float = 5.0) -> None:
        self.strength = strength
        self.base = 0.0
        self._k: dict[Hashable, int] = defaultdict(int)
        self._n: dict[Hashable, int] = defaultdict(int)

    def fit(self, events: Iterable[Event]) -> Climatology:
        total_k = total_n = 0
        for e in events:
            self._n[e.key] += 1
            self._k[e.key] += int(e.detected)
            total_n += 1
            total_k += int(e.detected)
        self.base = total_k / total_n if total_n else 0.0
        return self

    def predict(self, key: Hashable) -> float:
        n, k = self._n.get(key, 0), self._k.get(key, 0)
        return (k + self.strength * self.base) / (n + self.strength)


class Persistence:
    """Detection rate in the previous period for the same key; falls back to a default."""

    def __init__(self, default: float) -> None:
        self.default = default
        self._k: dict[tuple[Hashable, int], int] = defaultdict(int)
        self._n: dict[tuple[Hashable, int], int] = defaultdict(int)

    def fit(self, events: Iterable[Event]) -> Persistence:
        for e in events:
            self._n[(e.key, e.period)] += 1
            self._k[(e.key, e.period)] += int(e.detected)
        return self

    def predict(self, key: Hashable, period: int) -> float:
        n = self._n.get((key, period - 1), 0)
        if n == 0:
            return self.default
        return self._k[(key, period - 1)] / n
