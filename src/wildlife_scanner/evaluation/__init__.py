"""Evaluation harness: scoring rules, calibration, baselines and time-forward splits."""

from wildlife_scanner.evaluation.baselines import Climatology, Event, Persistence
from wildlife_scanner.evaluation.metrics import (
    ReliabilityBin,
    brier_score,
    brier_skill_score,
    log_loss,
    reliability_table,
)
from wildlife_scanner.evaluation.splits import Fold, forward_chaining_folds

__all__ = [
    "Climatology",
    "Event",
    "Fold",
    "Persistence",
    "ReliabilityBin",
    "brier_score",
    "brier_skill_score",
    "forward_chaining_folds",
    "log_loss",
    "reliability_table",
]
