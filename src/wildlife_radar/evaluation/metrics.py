"""Proper scoring rules and calibration diagnostics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


def _check(y: Sequence[int], p: Sequence[float]) -> None:
    if len(y) != len(p):
        raise ValueError("y and p must have the same length")
    if not y:
        raise ValueError("empty inputs")
    if any(v not in (0, 1) for v in y):
        raise ValueError("y must be 0/1")
    if any(not 0 <= q <= 1 for q in p):
        raise ValueError("p must be within [0, 1]")


def brier_score(y: Sequence[int], p: Sequence[float]) -> float:
    _check(y, p)
    return sum((q - v) ** 2 for v, q in zip(y, p, strict=True)) / len(y)


def log_loss(y: Sequence[int], p: Sequence[float], eps: float = 1e-12) -> float:
    _check(y, p)
    total = 0.0
    for v, q in zip(y, p, strict=True):
        q = min(max(q, eps), 1 - eps)
        total += -math.log(q) if v == 1 else -math.log(1 - q)
    return total / len(y)


def brier_skill_score(y: Sequence[int], p: Sequence[float], p_ref: Sequence[float]) -> float:
    """1 − BS/BS_ref: > 0 beats the reference (e.g., climatology), < 0 is worse."""
    ref = brier_score(y, p_ref)
    if ref == 0:
        return 0.0 if brier_score(y, p) == 0 else -math.inf
    return 1 - brier_score(y, p) / ref


@dataclass(frozen=True)
class ReliabilityBin:
    lo: float
    hi: float
    n: int
    mean_p: float
    observed_rate: float


def reliability_table(y: Sequence[int], p: Sequence[float], bins: int = 10) -> list[ReliabilityBin]:
    """Equal-width reliability diagram bins (empty bins omitted)."""
    _check(y, p)
    out: list[ReliabilityBin] = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, q in enumerate(p) if lo <= q < hi or (b == bins - 1 and q == 1.0)]
        if not idx:
            continue
        out.append(
            ReliabilityBin(
                lo=lo,
                hi=hi,
                n=len(idx),
                mean_p=sum(p[i] for i in idx) / len(idx),
                observed_rate=sum(y[i] for i in idx) / len(idx),
            )
        )
    return out
