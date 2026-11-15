"""Predictions: the single estimand every model produces.

P(encountering evidence of ``taxon_id`` using ``method_id`` with that method's standard effort,
within ``cell``/``place_id`` during ``time``, given information available ``as_of``).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wildlife_scanner.core import spatial
from wildlife_scanner.core.time import TimeWindow, ensure_utc


class Confidence(StrEnum):
    INSUFFICIENT = "insufficient"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Prediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    taxon_id: str
    cell: str | None = None
    place_id: str | None = None
    time: TimeWindow
    method_id: str
    as_of: datetime
    p: float = Field(ge=0, le=1)
    interval: tuple[float, float] | None = None
    lift_regional: float | None = Field(default=None, ge=0)
    anomaly_vs_norm: float | None = Field(default=None, ge=0)
    """Now vs. the seasonal norm for this place ("unusual right now"); needs a nowcast."""
    seasonal_index: float | None = Field(default=None, ge=0)
    """This time window vs. the annual mean at this place ("peaking now")."""
    confidence: Confidence = Confidence.LOW
    contributions: dict[str, float] = Field(default_factory=dict)
    """Additive log-odds contributions per term (including ``prior``) — the 'why'."""
    maturity_level: int = Field(default=0, ge=0, le=3)
    model_version: str = "unversioned"
    policy_tier_applied: int | None = None

    @field_validator("as_of")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)

    @model_validator(mode="after")
    def _checks(self) -> Prediction:
        if self.cell is None and self.place_id is None:
            raise ValueError("a prediction needs a cell or a place_id")
        if self.cell is not None and not spatial.is_valid_cell(self.cell):
            raise ValueError(f"invalid H3 cell {self.cell!r}")
        if self.interval is not None:
            lo, hi = self.interval
            if not (0 <= lo <= hi <= 1):
                raise ValueError("interval must satisfy 0 <= lo <= hi <= 1")
        return self
