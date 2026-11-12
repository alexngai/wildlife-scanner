"""Measure LLM extraction accuracy against curated trait values (framework.md §4.3 step 5).

Extraction runs on species that TetrapodTraits covers with **measured** (not imputed) values,
and each comparable field is scored:

- ``activity_pattern``: exact agreement, plus "compatible" agreement because TetrapodTraits has
  no crepuscular class (crepuscular is compatible with cathemeral or nocturnal);
- ``habitats``: extracted habitats are mapped onto IUCN habitat classes and scored by
  precision (extracted classes the database also lists) and recall.

The per-field accuracy becomes the confidence of extracted values (``accuracy.json``), and a
field is recommended for automatic acceptance only with enough comparisons and high agreement.
Everything else stays in the review queue.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from wildlife_radar.connectors.base import ConnectorError
from wildlife_radar.profilegen.candidates import Candidate, Rank
from wildlife_radar.profilegen.extract import EXTRACTION_FIELDS, Extractor, extraction_candidates
from wildlife_radar.profilegen.identity import IdentityResolver
from wildlife_radar.profilegen.traits import TetrapodTraits
from wildlife_radar.profilegen.wikipedia import WikipediaClient

#: Extraction habitat vocabulary → IUCN habitat classes (as in TetrapodTraits).
HABITAT_TO_IUCN = {
    "kelp_forest": {"marine_neritic"},
    "rocky_reef": {"marine_neritic"},
    "sandy_bottom": {"marine_neritic"},
    "seagrass": {"marine_neritic"},
    "open_ocean": {"marine_oceanic"},
    "bay_estuary": {"marine_coastal", "marine_neritic", "wetlands"},
    "intertidal": {"marine_intertidal"},
    "sandy_beach": {"marine_intertidal", "marine_coastal"},
    "mudflat": {"marine_intertidal", "wetlands"},
    "salt_marsh": {"marine_coastal", "wetlands"},
    "freshwater_wetland": {"wetlands"},
    "river_stream": {"wetlands"},
    "lake_pond": {"wetlands"},
    "grassland": {"grassland"},
    "coastal_scrub": {"shrubland"},
    "chaparral": {"shrubland"},
    "oak_woodland": {"forest"},
    "conifer_forest": {"forest"},
    "broadleaf_forest": {"forest"},
    "riparian": {"forest", "wetlands"},
    "desert": {"desert"},
    "alpine": {"grassland", "rocky_areas", "shrubland"},
    "cave": {"caves"},
    "urban_suburban": {"artificial_terrestrial"},
    "agricultural": {"artificial_terrestrial"},
}
COMPATIBLE_ACTIVITY = {"crepuscular": {"crepuscular", "cathemeral", "nocturnal"}}

DEFAULT_ACCURACY_PATH = Path(__file__).resolve().parents[3] / "data" / "profiles" / "accuracy.json"


@dataclass
class FieldScore:
    field: str
    n: int = 0
    agree: float = 0.0
    """Sum of per-species agreement (1 per exact match; precision for set fields)."""
    compatible: float = 0.0
    recall: float = 0.0
    examples: list[dict] = field(default_factory=list)

    @property
    def accuracy(self) -> float | None:
        return self.agree / self.n if self.n else None

    def decision(self, threshold: float, min_n: int) -> str:
        if self.n < min_n:
            return f"review (only {self.n} comparisons; need {min_n})"
        if (self.accuracy or 0) >= threshold:
            return "auto-accept"
        return f"review (accuracy {self.accuracy:.2f} < {threshold})"


def compare(field_name: str, extracted, reference) -> tuple[float, float, float] | None:
    """``(agreement, compatible, recall)`` for one species, or ``None`` if not comparable."""
    if field_name == "traits.activity_pattern":
        exact = float(extracted == reference)
        ok = float(reference in COMPATIBLE_ACTIVITY.get(extracted, {extracted}))
        return exact, ok, exact
    if field_name == "traits.habitats":
        mapped = set().union(*(HABITAT_TO_IUCN.get(h, set()) for h in extracted))
        ref = set(reference or [])
        if not mapped or not ref:
            return None
        hits = mapped & ref
        precision = len(hits) / len(mapped)
        return precision, precision, len(hits) / len(ref)
    return None


REFERENCE_FIELD = {
    "traits.activity_pattern": "traits.activity_pattern",
    "traits.habitats": "traits.iucn_habitats",
}


def score(
    pairs: Sequence[tuple[str, list[Candidate], list[Candidate]]],
) -> dict[str, FieldScore]:
    """Score ``(taxon, extracted candidates, measured trait candidates)`` triples."""
    scores = {f: FieldScore(field=f) for f in REFERENCE_FIELD}
    for taxon, extracted, traits in pairs:
        measured = {c.field: c.value for c in traits if c.rank == Rank.DB_MEASURED}
        for c in extracted:
            ref_field = REFERENCE_FIELD.get(c.field)
            if ref_field is None or ref_field not in measured:
                continue
            result = compare(c.field, c.value, measured[ref_field])
            if result is None:
                continue
            s = scores[c.field]
            s.n += 1
            s.agree += result[0]
            s.compatible += result[1]
            s.recall += result[2]
            if result[0] < 1 and len(s.examples) < 10:
                s.examples.append(
                    {"taxon": taxon, "extracted": c.value, "reference": measured[ref_field]}
                )
    return scores


def report(scores: dict[str, FieldScore], threshold: float = 0.9, min_n: int = 30) -> dict:
    return {
        "threshold": threshold,
        "min_comparisons": min_n,
        "fields": {
            f: {
                "n": s.n,
                "accuracy": round(s.accuracy, 3) if s.accuracy is not None else None,
                "compatible": round(s.compatible / s.n, 3) if s.n else None,
                "recall": round(s.recall / s.n, 3) if s.n else None,
                "decision": s.decision(threshold, min_n),
                "disagreements": s.examples,
            }
            for f, s in scores.items()
        },
        # Confidence for extracted values of each field (used by extraction_candidates).
        "confidence": {
            f.removeprefix("traits."): round(s.accuracy, 3)
            for f, s in scores.items()
            if s.accuracy is not None and s.n >= min_n
        },
    }


def load_accuracy(path: Path | None = None) -> dict[str, float]:
    path = path or DEFAULT_ACCURACY_PATH
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("confidence", {})


def run_calibration(
    names: Sequence[str],
    *,
    resolver: IdentityResolver,
    traits: TetrapodTraits,
    wiki: WikipediaClient,
    extractor: Extractor,
) -> tuple[dict[str, FieldScore], list[str]]:
    """Extract for species with measured trait values and score against them."""
    pairs = []
    notes = []
    for ident in resolver.resolve_many(list(names)):
        if not ident.resolved or not ident.wikipedia_title:
            notes.append(f"{ident.query_name}: skipped (no identity or Wikipedia article)")
            continue
        reference = [c for c in traits.candidates(ident.names) if c.rank == Rank.DB_MEASURED]
        if not reference:
            notes.append(f"{ident.query_name}: skipped (no measured trait values)")
            continue
        try:
            article = wiki.fetch(ident.wikipedia_title)
        except ConnectorError as exc:
            notes.append(f"{ident.query_name}: {exc}")
            continue
        result = extractor.extract(article, ident.names, EXTRACTION_FIELDS)
        if result.error:
            notes.append(f"{ident.query_name}: {result.error}")
        extracted, _ = extraction_candidates(result, article, ident.names, ident.common_name)
        pairs.append((ident.taxon_id or ident.query_name, extracted, reference))
    return score(pairs), notes


def save_report(data: dict, path: Path | None = None) -> Path:
    path = path or DEFAULT_ACCURACY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=list), encoding="utf-8")
    return path
