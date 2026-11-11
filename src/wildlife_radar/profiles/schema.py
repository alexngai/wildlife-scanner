"""Species profile schema.

A profile declares which signals, sources, methods, priors and policy apply to a taxon. Profiles
inherit from templates (``base`` → guild → species). Generated content enters as weak priors and
hypotheses with provenance; observed data overrides it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wildlife_radar.core.methods import STANDARD_METHODS
from wildlife_radar.core.sources import ObservationType
from wildlife_radar.policy.resolve import EffectiveTier, TierOverride, TierWindow, resolve_tier
from wildlife_radar.policy.tiers import PolicyTier

Strength = Literal["weak", "moderate", "strong"]


class SignalSpec(BaseModel):
    """How a signal is expected to affect encounters. Extra keys become shape parameters."""

    model_config = ConfigDict(extra="allow")

    signal: str | None = None
    """Signal id in the registry; defaults to the key under which the spec is declared."""
    role: Literal["presence", "availability", "detectability"] = "presence"
    shape: Literal["linear", "optimum", "peak", "monotone", "categorical"] | None = None
    direction: Literal["+", "-"] | None = None
    strength: Strength | None = None
    hypothesis: bool = False
    """A candidate signal to be tested by ablation before it is trusted."""
    from_trait: str | None = None
    applies_to: list[str] = Field(default_factory=list)
    citation: str | None = None

    @property
    def params(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    obs: ObservationType
    status: Literal["active", "planned", "partnership_pending", "disabled"] = "active"
    effort: str | None = None
    footprint: str | None = None
    background: str | None = None
    false_positive: str | float | None = None
    method: str | None = None
    bias: list[str] = Field(default_factory=list)
    lookalikes: list[str] = Field(default_factory=list)


class MethodsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    also: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _from_list(cls, v: Any) -> Any:
        if isinstance(v, list):
            if not v:
                raise ValueError("methods list must not be empty")
            return {"headline": v[0], "also": v[1:]}
        return v

    @model_validator(mode="after")
    def _known(self) -> MethodsSpec:
        unknown = [m for m in [self.headline, *self.also] if m not in STANDARD_METHODS]
        if unknown:
            raise ValueError(f"unknown encounter methods: {unknown}")
        return self

    @property
    def all(self) -> list[str]:
        return [self.headline, *self.also]


class LatentStateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scale: Literal["site", "zone", "territory", "range"]
    spatial_km: float | None = None
    from_trait: str | None = None
    dynamics: Literal["fast", "seasonal", "slow"] | None = None


class PriorSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    seasonal: Literal["elicited", "learned", "none"] = "learned"
    peak: str | None = None
    citation: str | None = None


class NowcastSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    half_life_days: float | tuple[float, float] | None = None
    spatial_km: float | None = None


class WindowSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    start: str = Field(alias="from")
    end: str = Field(alias="to")
    tier: PolicyTier
    regions: list[str] | None = None
    reason: str = ""

    def to_tier_window(self) -> TierWindow:
        return TierWindow(
            start=self.start,
            end=self.end,
            tier=self.tier,
            regions=tuple(self.regions) if self.regions is not None else None,
            reason=self.reason,
        )


class RegionalPolicySpec(BaseModel):
    """Per-region tier. Lowering below the default requires approvals (see ``resolve_tier``)."""

    model_config = ConfigDict(extra="forbid")

    tier: PolicyTier
    mode: Literal["awareness", "viewing"] | None = None
    via: str | None = None
    note: str = ""
    exclude: list[str] = Field(default_factory=list)
    approved_by: list[str] = Field(default_factory=list)
    review_by: date | None = None


class PolicySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_tier: PolicyTier | None = None
    windows: list[WindowSpec] = Field(default_factory=list)
    regions: dict[str, RegionalPolicySpec] = Field(default_factory=dict)
    always_suppress: list[str] = Field(default_factory=list)

    def tier_windows(self) -> list[TierWindow]:
        return [w.to_tier_window() for w in self.windows]

    def overrides(self, taxon_id: str) -> list[TierOverride]:
        return [
            TierOverride(
                taxon_id=taxon_id,
                tier=spec.tier,
                region=region,
                rationale=spec.note,
                approvers=tuple(spec.approved_by),
                expires_at=(
                    datetime.combine(spec.review_by, time(0), tzinfo=UTC)
                    if spec.review_by
                    else None
                ),
                mode=spec.mode,
            )
            for region, spec in self.regions.items()
        ]


ProvenanceMethod = Literal["import", "extracted", "imputed", "computed", "human", "elicited"]


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    method: ProvenanceMethod
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: str | None = None
    """Where to verify the value (e.g. a revision id and character range), never copied text."""
    license: str | None = None
    retrieved: date | None = None
    measured: bool | None = None
    """For curated trait databases: measured (True) vs imputed by the database (False)."""
    extractor: str | None = None
    """For LLM extraction: extraction model and prompt hash."""
    review: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"


class Conflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    values: list[Any]
    sources: list[str]
    kind: Literal["categorical", "numeric"]


class GenerationInfo(BaseModel):
    """How a generated profile was made; kept with the draft for review and regeneration."""

    model_config = ConfigDict(extra="forbid")

    pipeline_version: str
    generated_at: datetime
    licenses: list[str] = Field(default_factory=list)
    """Licenses inherited from every source used (license taint)."""
    open_variant: bool = False
    """True when every value comes from CC0/CC BY/public-domain sources."""
    conflicts: list[Conflict] = Field(default_factory=list)
    review_queue: list[str] = Field(default_factory=list)
    """Fields to review first, ranked by uncertainty × impact."""
    notes: list[str] = Field(default_factory=list)


class SpeciesProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["species", "template"] = "species"
    scientific_name: str | None = None
    common_name: str | None = None
    extends: list[str] = Field(default_factory=list)
    status: Literal["draft", "reviewed"] = "draft"
    guilds: list[str] = Field(default_factory=list)
    traits: dict[str, Any] = Field(default_factory=dict)
    methods: MethodsSpec | None = None
    latent_state: LatentStateSpec | None = None
    prior: PriorSpec | None = None
    signals: dict[str, SignalSpec] = Field(default_factory=dict)
    sources: dict[str, SourceSpec] = Field(default_factory=dict)
    nowcast: NowcastSpec | None = None
    policy: PolicySpec = Field(default_factory=PolicySpec)
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    crosswalk: dict[str, str] = Field(default_factory=dict)
    """Verified identifiers in other databases (``gbif``, ``inaturalist``, ``wikidata``, ...)."""
    locked: list[str] = Field(default_factory=list)
    """Field paths a reviewer fixed; regeneration never changes them."""
    generation: GenerationInfo | None = None
    notes: str | None = None

    @field_validator("signals")
    @classmethod
    def _default_signal_ids(cls, v: dict[str, SignalSpec]) -> dict[str, SignalSpec]:
        return {k: s if s.signal else s.model_copy(update={"signal": k}) for k, s in v.items()}

    @model_validator(mode="after")
    def _species_requirements(self) -> SpeciesProfile:
        if self.kind == "species":
            if not self.scientific_name:
                raise ValueError(f"species profile {self.id!r} needs a scientific_name")
            if self.methods is None:
                raise ValueError(f"species profile {self.id!r} needs methods")
        return self

    def hypotheses(self) -> list[str]:
        """Signals declared as hypotheses — queued for ablation testing."""
        return [k for k, s in self.signals.items() if s.hypothesis]

    def effective_tier(
        self,
        auto_tier: PolicyTier,
        *,
        region: str | None,
        on: date,
        now: datetime,
        extra_overrides: list[TierOverride] | None = None,
        auto_reasons: tuple[str, ...] = (),
    ) -> EffectiveTier:
        return resolve_tier(
            auto_tier=auto_tier,
            taxon_id=self.id,
            on=on,
            region=region,
            now=now,
            profile_default=self.policy.default_tier,
            windows=self.policy.tier_windows(),
            overrides=[*self.policy.overrides(self.id), *(extra_overrides or [])],
            auto_reasons=auto_reasons,
        )
