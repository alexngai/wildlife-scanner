"""Evaluation harness: scoring rules, calibration, baselines and time-forward splits."""

from wildlife_radar.evaluation.baselines import Climatology, Event, Persistence
from wildlife_radar.evaluation.metrics import (
    ReliabilityBin,
    brier_score,
    brier_skill_score,
    log_loss,
    reliability_table,
)
from wildlife_radar.evaluation.splits import Fold, forward_chaining_folds

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
