"""Signals: time-varying values over space, with forecast-aware ("as-of") timestamps."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wildlife_scanner.core.time import ensure_utc


class SignalKind(StrEnum):
    RAW = "raw"  # straight from a source (SST, tide height)
    DERIVED = "derived"  # computed from other signals (anomalies, lags, hours since sunset)
    SPECIES = "species"  # another taxon's prediction used as a signal (prey → predator)


class SignalDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str
    units: str
    description: str
    kind: SignalKind = SignalKind.RAW
    source_id: str | None = None
    depends_on: tuple[str, ...] = ()


class SignalValue(BaseModel):
    """One value of a signal at a location.

    ``valid_time`` is the time the value describes; ``issue_time`` is when it became known.
    Forecasts have ``issue_time < valid_time``; observations usually the reverse; revisions share a
    ``valid_time`` with a later ``issue_time``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str
    location_key: str
    valid_time: datetime
    issue_time: datetime
    value: float | None
    attrs: dict[str, str | float] = Field(default_factory=dict)

    @field_validator("valid_time", "issue_time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)
