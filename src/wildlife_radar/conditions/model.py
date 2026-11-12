"""Additive condition terms on top of the Level-0 baseline (framework.md §5.1).

    logit p = logit p_L0(cell, week) + b0 + Σ_k f_k(signal_k)

``f_k`` takes its form from the profile's ``shape`` (linear/monotone: z; optimum/peak: z, z²;
cyclic: sin, cos of an angle) and its prior strength from ``strength``: a ridge penalty on
standardized features (weak → strong shrinkage toward "no effect"). The Level-0 logit enters as
an offset, so terms explain departures from the usual place-and-season rate, not the season
itself. Fitted by penalized iteratively reweighted least squares with case weights (negatives
are subsampled and up-weighted).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

#: Ridge penalty per standardized basis column, by profile strength.
PENALTY = {"strong": 1.0, "moderate": 5.0, "weak": 25.0, None: 10.0}
INTERCEPT_PENALTY = 1.0
CLIP = 1e-6


@dataclass(frozen=True)
class TermSpec:
    name: str
    signal: str
    shape: str = "linear"
    strength: str | None = None
    hypothesis: bool = False
    role: str = "presence"
    direction: str | None = None
    """Expected direction from the profile ("+"/"-"), compared with the fitted one."""

    def basis(self, x: np.ndarray) -> list[np.ndarray]:
        if self.shape == "cyclic":
            rad = np.radians(x)
            return [np.sin(rad), np.cos(rad)]
        if self.shape in ("optimum", "peak"):
            return [x, x * x]
        return [x]

    @property
    def width(self) -> int:
        return 2 if self.shape in ("cyclic", "optimum", "peak") else 1


@dataclass
class OffsetLogit:
    terms: list[TermSpec]
    coef: np.ndarray = field(default_factory=lambda: np.zeros(0))
    intercept: float = 0.0
    means: np.ndarray = field(default_factory=lambda: np.zeros(0))
    sds: np.ndarray = field(default_factory=lambda: np.zeros(0))
    converged: bool = False

    def design(self, signals: dict[str, np.ndarray]) -> np.ndarray:
        cols = []
        for t in self.terms:
            cols += t.basis(signals[t.signal].astype(float))
        if not cols:
            n = len(next(iter(signals.values()))) if signals else 0
            return np.zeros((n, 0))
        return np.column_stack(cols)

    def _standardize(self, X: np.ndarray) -> np.ndarray:
        return (X - self.means) / self.sds if X.shape[1] else X

    def fit(
        self,
        signals: dict[str, np.ndarray],
        y: np.ndarray,
        offset: np.ndarray,
        weights: np.ndarray | None = None,
        max_iter: int = 50,
    ) -> OffsetLogit:
        X = self.design(signals)
        w0 = np.ones(len(y)) if weights is None else weights
        if X.shape[1]:
            self.means = np.average(X, axis=0, weights=w0)
            sds = np.sqrt(np.average((X - self.means) ** 2, axis=0, weights=w0))
            self.sds = np.where(sds > 1e-9, sds, 1.0)
        Z = np.column_stack([np.ones(len(y)), self._standardize(X)])
        penalties = [INTERCEPT_PENALTY]
        for t in self.terms:
            penalties += [PENALTY.get(t.strength, PENALTY[None])] * t.width
        P = np.diag(penalties)
        beta = np.zeros(Z.shape[1])
        for _ in range(max_iter):
            eta = offset + Z @ beta
            p = np.clip(1 / (1 + np.exp(-eta)), CLIP, 1 - CLIP)
            W = w0 * p * (1 - p)
            grad = Z.T @ (w0 * (y - p)) - P @ beta
            H = (Z * W[:, None]).T @ Z + P
            step = np.linalg.solve(H, grad)
            beta += step
            if np.max(np.abs(step)) < 1e-6:
                self.converged = True
                break
        self.intercept = float(beta[0])
        self.coef = beta[1:]
        return self

    def predict(self, signals: dict[str, np.ndarray], offset: np.ndarray) -> np.ndarray:
        Z = self._standardize(self.design(signals))
        eta = offset + self.intercept + (Z @ self.coef if Z.shape[1] else 0)
        return 1 / (1 + np.exp(-eta))

    def contributions(self, signals: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Log-odds contribution of each term (the "why" behind a prediction)."""
        Z = self._standardize(self.design(signals))
        out, j = {}, 0
        for t in self.terms:
            out[t.name] = Z[:, j : j + t.width] @ self.coef[j : j + t.width]
            j += t.width
        return out

    def effect_curve(self, term: str, values: Sequence[float]) -> list[tuple[float, float]]:
        """Log-odds contribution of one term across signal values (others at their mean)."""
        j = 0
        for t in self.terms:
            if t.name == term:
                x = np.asarray(values, dtype=float)
                cols = np.column_stack(t.basis(x))
                z = (cols - self.means[j : j + t.width]) / self.sds[j : j + t.width]
                return list(zip(values, (z @ self.coef[j : j + t.width]).tolist(), strict=True))
            j += t.width
        raise KeyError(term)

    def to_dict(self) -> dict:
        return {
            "terms": [t.__dict__ for t in self.terms],
            "coef": self.coef.tolist(),
            "intercept": self.intercept,
            "means": self.means.tolist(),
            "sds": self.sds.tolist(),
            "converged": self.converged,
        }


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, CLIP, 1 - CLIP)
    return np.log(p / (1 - p))


def brier(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    return float(np.sum(w * (p - y) ** 2) / np.sum(w))


def log_loss(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    p = np.clip(p, CLIP, 1 - CLIP)
    return float(-np.sum(w * (y * np.log(p) + (1 - y) * np.log(1 - p))) / np.sum(w))


def block_bootstrap(
    blocks: np.ndarray,
    stat,
    reps: int = 200,
    seed: int = 7,
) -> tuple[float, float]:
    """90% interval of ``stat(index)`` resampling whole blocks (e.g. days) with replacement."""
    rng = np.random.default_rng(seed)
    uniq, inverse = np.unique(blocks, return_inverse=True)
    order = np.argsort(inverse, kind="stable")
    counts = np.bincount(inverse, minlength=len(uniq))
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    members = [order[s : s + c] for s, c in zip(starts, counts, strict=True)]
    values = []
    for _ in range(reps):
        pick = rng.integers(0, len(uniq), len(uniq))
        idx = np.concatenate([members[i] for i in pick]) if len(pick) else np.array([], int)
        if len(idx):
            values.append(stat(idx))
    if not values:
        return math.nan, math.nan
    return float(np.percentile(values, 5)), float(np.percentile(values, 95))
