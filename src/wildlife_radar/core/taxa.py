"""Taxon identity: internal concepts, cross-source references, and taxonomy change events.

We model taxon *concepts*, not names. Observations arrive with a source-specific ``TaxonRef``
(e.g., an iNaturalist taxon id) and are resolved to an internal ``taxon_id`` via the crosswalk.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TaxonScheme(StrEnum):
    INTERNAL = "internal"
    NAME = "name"  # scientific name only, unresolved
    WIKIDATA = "wikidata"
    COL = "col"
    GBIF = "gbif"
    INATURALIST = "inaturalist"
    EBIRD = "ebird"
    ITIS = "itis"
    WORMS = "worms"
    NCBI = "ncbi"
    IUCN = "iucn"
    FISHBASE = "fishbase"
    AVIBASE = "avibase"


class TaxonRef(BaseModel):
    """A taxon as named by one source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scheme: TaxonScheme
    id: str
    name: str | None = None
    rank: str | None = None


class Taxon(BaseModel):
    """An internal taxon concept with its cross-source identifiers."""

    model_config = ConfigDict(extra="forbid")

    taxon_id: str
    scientific_name: str
    rank: str = "species"
    parent_id: str | None = None
    common_names: dict[str, list[str]] = Field(default_factory=dict)
    crosswalk: dict[TaxonScheme, str] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    guilds: list[str] = Field(default_factory=list)
    taxonomy_version: str | None = None

    def ref(self, scheme: TaxonScheme) -> TaxonRef | None:
        source_id = self.crosswalk.get(scheme)
        if source_id is None:
            return None
        return TaxonRef(scheme=scheme, id=source_id, name=self.scientific_name, rank=self.rank)


class TaxonChangeKind(StrEnum):
    SWAP = "swap"  # rename only: move the pointer
    LUMP = "lump"  # several concepts → one: union ranges, recompute traits
    SPLIT = "split"  # one concept → several: children inherit profile (needs review), tier ≥ parent


class TaxonChange(BaseModel):
    """A taxonomy change event from a checklist release (eBird, iNat, COL diffs...)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: TaxonChangeKind
    from_ids: tuple[str, ...]
    to_ids: tuple[str, ...]
    taxonomy_version: str
    source: str


_SLUG = re.compile(r"[^a-z0-9]+")


def slugify_name(scientific_name: str) -> str:
    """Internal id from a scientific name: ``"Puma concolor"`` → ``"puma-concolor"``."""
    return _SLUG.sub("-", scientific_name.strip().lower()).strip("-")


#: Ranks at or below species; records at these ranks resolve to their species.
SPECIES_OR_BELOW = frozenset(
    {"species", "subspecies", "variety", "form", "infraspecies", "hybrid", "complex"}
)


def species_id_from_name(name: str | None, rank: str | None) -> str | None:
    """Phase-1 name-based resolution to a species-level internal id.

    Infraspecific names collapse to their species (first two words). Records above species rank
    return ``None``: they still count as observer effort, but not as detections of a species.
    Phase 2 replaces this with concept-based resolution via the taxonomic backbone.
    """
    if not name:
        return None
    if rank is not None and rank.lower() not in SPECIES_OR_BELOW:
        return None
    words = [w for w in name.replace("×", " ").split() if w]
    if len(words) < 2 or not words[0][:1].isupper() or not words[1][:1].islower():
        return None
    return slugify_name(f"{words[0]} {words[1]}")


_CLASS_GROUPS = {
    "aves": "birds",
    "mammalia": "mammals",
    "actinopterygii": "fishes",
    "elasmobranchii": "fishes",
    "chondrichthyes": "fishes",
    "holocephali": "fishes",
    "myxini": "fishes",
    "petromyzonti": "fishes",
    "sarcopterygii": "fishes",
    "teleostei": "fishes",
    "reptilia": "herps",
    "squamata": "herps",
    "testudines": "herps",
    "crocodylia": "herps",
    "amphibia": "herps",
    "insecta": "insects",
    "arachnida": "arachnids",
}
_PHYLUM_GROUPS = {
    "mollusca": "mollusks",
    "cnidaria": "cnidarians",
    "echinodermata": "echinoderms",
    "arthropoda": "arthropods",
}
_KINGDOM_GROUPS = {"plantae": "plants", "fungi": "fungi"}
_INAT_ICONIC_GROUPS = {
    "aves": "birds",
    "mammalia": "mammals",
    "actinopterygii": "fishes",
    "reptilia": "herps",
    "amphibia": "herps",
    "insecta": "insects",
    "arachnida": "arachnids",
    "mollusca": "mollusks",
    "plantae": "plants",
    "fungi": "fungi",
}


def target_group(
    kingdom: str | None = None,
    phylum: str | None = None,
    class_: str | None = None,
    inat_iconic: str | None = None,
) -> str:
    """Target group used as the sampling-effort background for presence-only data.

    Records of the same group are assumed to be collected by similar observers in similar ways,
    so the group's records measure effort (the "target-group background" correction).
    """
    for value, table in (
        (class_, _CLASS_GROUPS),
        (phylum, _PHYLUM_GROUPS),
        (kingdom, _KINGDOM_GROUPS),
        (inat_iconic, _INAT_ICONIC_GROUPS),
    ):
        if value and value.lower() in table:
            return table[value.lower()]
    if (kingdom or "").lower() == "animalia" or (inat_iconic or "").lower() == "animalia":
        return "other_animals"
    return "other"
