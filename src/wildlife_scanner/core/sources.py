"""Data sources and how each one observes the world.

The ``ObservationProcess`` is the key to fusing heterogeneous data: it declares how a source's
records relate to the true (latent) state — presence-only vs. detection/non-detection, effort,
biases, false-positive rates and look-alike taxa — so models can use each source correctly.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from wildlife_scanner.core.licenses import License


class SourceKind(StrEnum):
    OBSERVATION = "observation"
    SIGNAL = "signal"
    CONTEXT = "context"


class ObservationType(StrEnum):
    PRESENCE_ONLY = "presence_only"
    DETECTION_NONDETECTION = "detection_nondetection"
    COUNT = "count"
    CATCH_RATE = "catch_rate"
    ACOUSTIC = "acoustic"
    CAMERA = "camera"


class ObservationProcess(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ObservationType
    effort_fields: tuple[str, ...] = ()
    """Which ``Effort`` fields are meaningful for this source."""
    bias: tuple[str, ...] = ()
    """Known sampling biases, e.g. ``observer_density``, ``access``, ``roads``."""
    false_positive_prior: float | None = Field(default=None, ge=0, le=1)
    lookalikes: tuple[str, ...] = ()
    dedup_rule: str | None = None
    reporting_dynamics: tuple[str, ...] = ()
    """E.g. ``duplicate_reports``, ``media_spikes``, ``preferential_sampling``."""
    latency: str | None = None


class Source(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    name: str
    kind: SourceKind
    homepage: str | None = None
    terms_url: str | None = None
    license: License | None = None
    """Source-level license; ``None`` when licensed per record (see ``per_record_license``)."""
    per_record_license: bool = False
    attribution: str
    coverage: str = "global"
    requires_credentials: bool = False
    observation_process: ObservationProcess | None = None
    notes: str | None = None
