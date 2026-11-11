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
