"""Forward-in-time cross-validation splits (never random CV for spatio-temporal data)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Fold:
    train_idx: tuple[int, ...]
    test_idx: tuple[int, ...]
    test_start: datetime
    test_end: datetime


def forward_chaining_folds(times: Sequence[datetime], boundaries: Sequence[datetime]) -> list[Fold]:
    """Folds that train on everything before each boundary and test until the next one.

    ``boundaries`` must be increasing; the last boundary closes the final test period.
    """
    if len(boundaries) < 2:
        raise ValueError("need at least two boundaries")
    if any(b1 <= b0 for b0, b1 in zip(boundaries, boundaries[1:], strict=False)):
        raise ValueError("boundaries must be strictly increasing")
    folds = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        train = tuple(i for i, t in enumerate(times) if t < start)
        test = tuple(i for i, t in enumerate(times) if start <= t < end)
        if train and test:
            folds.append(Fold(train, test, start, end))
    return folds
