"""Field candidates: a proposed profile value with provenance and a precedence rank."""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from wildlife_scanner.profiles.schema import Provenance


class Rank(IntEnum):
    """Reconciliation precedence (framework.md §4.3 step 7); lower wins."""

    HUMAN = 0
    AUTHORITATIVE = 1
    DB_MEASURED = 2
    COMPUTED = 2
    """Occurrence-derived priors: measured from data, ranked with measured trait values."""
    DB_IMPUTED = 3
    WIKIDATA = 4
    EXTRACTED = 5
    TAXONOMIC_IMPUTATION = 6
    LLM_HINT = 7


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    """Dotted profile path, e.g. ``traits.activity_pattern``."""
    value: Any
    provenance: Provenance
    rank: Rank

    @property
    def source(self) -> str:
        return self.provenance.source
