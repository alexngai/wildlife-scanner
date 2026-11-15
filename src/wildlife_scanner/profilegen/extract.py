"""LLM extraction of profile fields from retrieved text, with machine-checked evidence.

Rules (framework.md §4.3 step 5):

- Extract only from the supplied text, never from model memory.
- Controlled vocabularies, with an explicit "not stated" for every field.
- Every value carries a **verbatim evidence span**, checked here to exist in the text; values
  whose evidence can't be found are rejected, as are numbers outside plausible bounds.
- Each extraction records the serving model and a prompt hash.
- Status, protection and policy are **never** extraction fields: the catalogue below has no such
  field and reconciliation refuses them from any non-human source.

The extraction model is configured by the operator (``--model`` or
``WILDLIFE_SCANNER_EXTRACTION_MODEL``); the Anthropic SDK is the optional ``llm`` extra.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from wildlife_scanner.profilegen.candidates import Candidate, Rank
from wildlife_scanner.profilegen.wikipedia import Article
from wildlife_scanner.profiles.schema import Provenance

MODEL_ENV = "WILDLIFE_SCANNER_EXTRACTION_MODEL"

FieldKind = Literal["enum", "enum_list", "bool", "range", "months"]


class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: FieldKind
    description: str
    vocabulary: tuple[str, ...] = ()
    unit: str | None = None
    bounds: tuple[float, float] | None = None


HABITATS = (
    "kelp_forest",
    "rocky_reef",
    "sandy_bottom",
    "seagrass",
    "open_ocean",
    "bay_estuary",
    "intertidal",
    "sandy_beach",
    "salt_marsh",
    "mudflat",
    "freshwater_wetland",
    "river_stream",
    "lake_pond",
    "grassland",
    "coastal_scrub",
    "chaparral",
    "oak_woodland",
    "conifer_forest",
    "broadleaf_forest",
    "riparian",
    "desert",
    "alpine",
    "cave",
    "urban_suburban",
    "agricultural",
)

EXTRACTION_FIELDS: dict[str, FieldSpec] = {
    "activity_pattern": FieldSpec(
        kind="enum",
        description="When the animal is mainly active.",
        vocabulary=("diurnal", "nocturnal", "crepuscular", "cathemeral"),
    ),
    "migratory": FieldSpec(
        kind="bool", description="Whether populations make regular seasonal migrations."
    ),
    "habitats": FieldSpec(
        kind="enum_list", description="Habitats where it is found.", vocabulary=HABITATS
    ),
    "depth_m": FieldSpec(
        kind="range",
        description="Usual depth range in water, in meters (convert from feet: 1 ft = 0.3048 m).",
        unit="m",
        bounds=(0, 11000),
    ),
    "elevation_m": FieldSpec(
        kind="range",
        description="Elevation range on land, in meters.",
        unit="m",
        bounds=(-430, 8850),
    ),
    "home_range_km2": FieldSpec(
        kind="range",
        description="Home range or territory size, in square kilometers.",
        unit="km2",
        bounds=(0, 1_000_000),
    ),
    "breeding_months": FieldSpec(
        kind="months",
        description="Months (1-12) of breeding, nesting, spawning or birthing, as stated.",
    ),
    "social_behavior": FieldSpec(
        kind="enum_list",
        description="How individuals usually occur.",
        vocabulary=(
            "solitary",
            "pairs",
            "family_groups",
            "flocks",
            "schools",
            "colonies",
            "aggregations",
        ),
    ),
    "diet": FieldSpec(
        kind="enum_list",
        description="Main diet categories.",
        vocabulary=(
            "herbivore",
            "insectivore",
            "piscivore",
            "carnivore",
            "omnivore",
            "planktivore",
            "nectarivore",
            "granivore",
            "frugivore",
            "scavenger",
            "detritivore",
        ),
    ),
}

#: Profile paths that extraction (or any non-human source) must never set.
GUARDED_PREFIXES = ("policy", "status", "locked", "crosswalk", "generation")

SYSTEM_PROMPT = """\
You extract structured natural-history facts about one taxon from a single source text, for a \
wildlife-encounter forecasting project. Values you return are treated as weak priors and are \
checked by a program and then by human reviewers.

Rules:
- Use only the source text in the user message. Do not use outside knowledge, even if the text \
seems incomplete or wrong.
- Report a field only if the text states it for this taxon (not for a relative, a genus or a \
lookalike). Otherwise set "stated" to false, "value" to null and "evidence" to "".
- "evidence" must be one contiguous passage copied exactly, character for character, from the \
source text (at most 300 characters) that supports the value. Do not paraphrase or join passages.
- Use only the allowed vocabulary. Convert units to the requested unit when the text uses \
another one; the evidence keeps the original wording.
- For ranges give min and max; for a single number set both to it.
- Never report conservation status, legal protection or sensitivity: those are not fields here.
"""


def output_schema(fields: dict[str, FieldSpec]) -> dict[str, Any]:
    def value_schema(spec: FieldSpec) -> dict[str, Any]:
        if spec.kind == "enum":
            return {"type": "string", "enum": list(spec.vocabulary)}
        if spec.kind == "enum_list":
            return {"type": "array", "items": {"type": "string", "enum": list(spec.vocabulary)}}
        if spec.kind == "bool":
            return {"type": "boolean"}
        if spec.kind == "months":
            return {"type": "array", "items": {"type": "integer", "enum": list(range(1, 13))}}
        return {
            "type": "object",
            "properties": {"min": {"type": "number"}, "max": {"type": "number"}},
            "required": ["min", "max"],
            "additionalProperties": False,
        }

    props = {
        name: {
            "type": "object",
            "properties": {
                "stated": {"type": "boolean"},
                "value": {"anyOf": [value_schema(spec), {"type": "null"}]},
                "evidence": {"type": "string"},
            },
            "required": ["stated", "value", "evidence"],
            "additionalProperties": False,
        }
        for name, spec in fields.items()
    }
    return {
        "type": "object",
        "properties": props,
        "required": list(fields),
        "additionalProperties": False,
    }


def user_prompt(article: Article, names: list[str], fields: dict[str, FieldSpec]) -> str:
    lines = [
        f"Taxon: {names[0]}" + (f" (also known as: {', '.join(names[1:])})" if names[1:] else ""),
        "",
        "Fields:",
    ]
    for name, spec in fields.items():
        extra = f" Allowed: {', '.join(spec.vocabulary)}." if spec.vocabulary else ""
        unit = f" Unit: {spec.unit}." if spec.unit else ""
        lines.append(f"- {name}: {spec.description}{unit}{extra}")
    lines += ["", f"<source title={json.dumps(article.title)}>", article.text, "</source>"]
    return "\n".join(lines)


def prompt_hash(fields: dict[str, FieldSpec]) -> str:
    blob = SYSTEM_PROMPT + json.dumps(output_schema(fields), sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


class RawExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    value: Any
    evidence: str


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extractions: list[RawExtraction] = Field(default_factory=list)
    extractor: str
    error: str | None = None


class Extractor(Protocol):
    def extract(
        self, article: Article, names: list[str], fields: dict[str, FieldSpec]
    ) -> ExtractionResult: ...


def parse_output(data: dict[str, Any], fields: dict[str, FieldSpec]) -> list[RawExtraction]:
    out = []
    for name in fields:
        item = data.get(name) or {}
        if item.get("stated") and item.get("value") not in (None, [], ""):
            out.append(
                RawExtraction(field=name, value=item["value"], evidence=item.get("evidence") or "")
            )
    return out


class ClaudeExtractor:
    """Structured-output extraction with the Anthropic API (optional ``llm`` extra)."""

    def __init__(self, model: str | None = None, client: Any = None, effort: str = "medium"):
        self.model = model or os.environ.get(MODEL_ENV)
        if not self.model:
            raise ValueError(f"no extraction model: pass --model or set {MODEL_ENV}")
        self.effort = effort
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise RuntimeError(
                    "LLM extraction needs the Anthropic SDK: install the 'llm' extra "
                    "(uv sync --extra llm)"
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    def extract(
        self, article: Article, names: list[str], fields: dict[str, FieldSpec]
    ) -> ExtractionResult:
        tag = f"{self.model}+prompt:{prompt_hash(fields)}"
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[
                {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
            ],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": output_schema(fields)},
            },
            messages=[{"role": "user", "content": user_prompt(article, names, fields)}],
        )
        served = getattr(response, "model", None) or self.model
        tag = f"{served}+prompt:{prompt_hash(fields)}"
        if response.stop_reason == "refusal":
            return ExtractionResult(extractor=tag, error="the model declined the request")
        if response.stop_reason == "max_tokens":
            return ExtractionResult(extractor=tag, error="output truncated (max_tokens)")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except ValueError:
            return ExtractionResult(extractor=tag, error="output was not valid JSON")
        return ExtractionResult(extractions=parse_output(data, fields), extractor=tag)


class StaticExtractor:
    """Returns preset outputs (tests, offline demos, replaying cached extractions)."""

    def __init__(self, outputs: dict[str, dict[str, Any]], name: str = "static") -> None:
        self.outputs = outputs
        self.name = name

    def extract(
        self, article: Article, names: list[str], fields: dict[str, FieldSpec]
    ) -> ExtractionResult:
        data = self.outputs.get(article.title, {})
        return ExtractionResult(
            extractions=parse_output(data, fields),
            extractor=f"{self.name}+prompt:{prompt_hash(fields)}",
        )


# -- Verification ------------------------------------------------------------------------

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip()


class Verified(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    value: Any
    accepted: bool
    reason: str | None = None
    start: int | None = None
    end: int | None = None
    names_taxon: bool = False


def verify(
    extraction: RawExtraction, article: Article, names: list[str], normalized: str | None = None
) -> Verified:
    spec = EXTRACTION_FIELDS.get(extraction.field)
    text = normalized if normalized is not None else normalize(article.text)

    def reject(reason: str) -> Verified:
        return Verified(
            field=extraction.field, value=extraction.value, accepted=False, reason=reason
        )

    if spec is None:
        return reject("unknown field")
    if extraction.field.split(".")[0] in GUARDED_PREFIXES:
        return reject("guarded field")
    evidence = normalize(extraction.evidence)
    if len(evidence) < 8:
        return reject("missing evidence")
    if len(evidence) > 400:
        return reject("evidence too long")
    start = text.find(evidence)
    if start < 0:
        start = text.lower().find(evidence.lower())
    if start < 0:
        return reject("evidence not found in source text")
    value = extraction.value
    if spec.kind == "range":
        try:
            lo, hi = float(value["min"]), float(value["max"])
        except (KeyError, TypeError, ValueError):
            return reject("malformed range")
        if lo > hi:
            return reject("min > max")
        if spec.bounds and not (spec.bounds[0] <= lo and hi <= spec.bounds[1]):
            return reject(f"outside plausible bounds {spec.bounds}")
        if not re.search(r"\d", evidence):
            return reject("numeric value without a number in the evidence")
        value = [lo, hi]
    elif spec.kind in ("enum", "enum_list"):
        values = value if isinstance(value, list) else [value]
        if any(v not in spec.vocabulary for v in values):
            return reject("value outside vocabulary")
        value = sorted(set(values)) if spec.kind == "enum_list" else value
    elif spec.kind == "months":
        if not all(isinstance(m, int) and 1 <= m <= 12 for m in value):
            return reject("invalid month")
        value = sorted(set(value))
    names_taxon = any(n.lower() in evidence.lower() for n in names)
    return Verified(
        field=extraction.field,
        value=value,
        accepted=True,
        start=start,
        end=start + len(evidence),
        names_taxon=names_taxon,
    )


def article_is_about(article: Article, names: list[str], common_name: str | None) -> bool:
    text = article.text.lower()
    candidates = [*names, common_name or ""]
    return any(n and n.lower() in text for n in candidates) or any(
        n and n.lower() == article.title.lower() for n in candidates
    )


def extraction_candidates(
    result: ExtractionResult,
    article: Article,
    names: list[str],
    common_name: str | None = None,
    accuracy: dict[str, float] | None = None,
) -> tuple[list[Candidate], list[Verified]]:
    """Verify raw extractions; accepted ones become rank-EXTRACTED candidates.

    ``accuracy`` (from ``profilegen calibrate``) sets each field's confidence from measured
    agreement with curated trait values; otherwise a fixed low prior is used.
    """
    accuracy = accuracy or {}
    if not article_is_about(article, names, common_name):
        return [], [
            Verified(field=e.field, value=e.value, accepted=False, reason="article not about taxon")
            for e in result.extractions
        ]
    normalized = normalize(article.text)
    checks = [verify(e, article, names, normalized) for e in result.extractions]
    candidates = [
        Candidate(
            field=f"traits.{v.field}",
            value=v.value,
            rank=Rank.EXTRACTED,
            provenance=Provenance(
                source=article.citation,
                method="extracted",
                confidence=accuracy.get(v.field, 0.6 if v.names_taxon else 0.5),
                evidence=f"{article.url} chars {v.start}-{v.end} (whitespace-normalized)",
                license=article.license,
                retrieved=article.retrieved,
                extractor=result.extractor,
            ),
        )
        for v in checks
        if v.accepted
    ]
    return candidates, checks
