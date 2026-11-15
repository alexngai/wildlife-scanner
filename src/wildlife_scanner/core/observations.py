"""Observations: evidence that a taxon was (or was not) detected somewhere, somewhen, somehow."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wildlife_scanner.core.geometry import Footprint
from wildlife_scanner.core.licenses import License
from wildlife_scanner.core.taxa import TaxonRef
from wildlife_scanner.core.time import TimeWindow, ensure_utc, utcnow


class Modality(StrEnum):
    """How the evidence was obtained."""

    SEE = "see"
    HEAR = "hear"
    SIGN = "sign"  # tracks, scat, scrapes, kills
    CAMERA = "camera"
    CATCH = "catch"  # used only as an input, never as a product output
    SENSOR = "sensor"  # acoustic recorder, radar, other automated sensors
    DNA = "dna"  # eDNA, genetic samples
    UNKNOWN = "unknown"


class Outcome(StrEnum):
    DETECTED = "detected"
    NOT_DETECTED = "not_detected"
    COUNT = "count"
    PRESENCE_ONLY = "presence_only"


class EvidenceGrade(StrEnum):
    """SCALP-style evidence grades (as used in European large-carnivore monitoring)."""

    C1 = "C1"  # hard evidence: verified photo/audio/specimen/DNA/carcass
    C2 = "C2"  # expert-verified sign
    C3 = "C3"  # unverified report
    M = "M"  # automated model/classifier detection (see classifier_score)


class Effort(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    duration_min: float | None = Field(default=None, ge=0)
    distance_km: float | None = Field(default=None, ge=0)
    area_m2: float | None = Field(default=None, ge=0)
    observers: int | None = Field(default=None, ge=0)
    angler_hours: float | None = Field(default=None, ge=0)
    trap_nights: float | None = Field(default=None, ge=0)
    extra: dict[str, float] = Field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.extra and all(
            getattr(self, f) is None
            for f in (
                "duration_min",
                "distance_km",
                "area_m2",
                "observers",
                "angler_hours",
                "trap_nights",
            )
        )


#: Life-stage / site contexts whose records are never published, whatever the policy tier.
SENSITIVE_CONTEXTS = frozenset(
    {
        "nest",
        "den",
        "roost",
        "rendezvous_site",
        "lek",
        "hibernaculum",
        "spawning_aggregation",
    }
)


class SensitivityFlags(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    obscured: bool = False
    """Coordinates were deliberately generalized upstream."""
    geoprivacy: str | None = None
    taxon_geoprivacy: str | None = None
    embargoed_until: datetime | None = None
    contexts: frozenset[str] = frozenset()
    individual_id: str | None = None
    """Named or collared individual — never published."""

    @field_validator("embargoed_until")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else ensure_utc(v)


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    obs_id: str
    source_id: str
    source_record_id: str | None = None
    source_url: str | None = None
    taxon: TaxonRef
    taxon_id: str | None = None
    """Resolved internal taxon concept; ``None`` until resolved (policy treats it as sensitive)."""
    footprint: Footprint
    time: TimeWindow
    modality: Modality = Modality.UNKNOWN
    method: str | None = None
    """Protocol, e.g. ``scuba_dive``, ``ebird_complete_checklist``, ``cpfv_trip``."""
    effort: Effort | None = None
    outcome: Outcome
    count: float | None = Field(default=None, ge=0)
    evidence_grade: EvidenceGrade = EvidenceGrade.C3
    classifier_score: float | None = Field(default=None, ge=0, le=1)
    license: License
    sensitivity: SensitivityFlags = Field(default_factory=SensitivityFlags)
    ingested_at: datetime = Field(default_factory=utcnow)
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ingested_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)

    @model_validator(mode="after")
    def _count_consistency(self) -> Observation:
        if self.outcome is Outcome.COUNT and self.count is None:
            raise ValueError("outcome 'count' requires a count")
        return self

    @property
    def is_detection(self) -> bool:
        if self.outcome is Outcome.NOT_DETECTED:
            return False
        if self.outcome is Outcome.COUNT:
            return bool(self.count)
        return True
