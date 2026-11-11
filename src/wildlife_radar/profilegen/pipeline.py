"""Run the generation steps for a list of names and write draft profiles."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb

from wildlife_radar.connectors.base import ConnectorError
from wildlife_radar.profilegen.candidates import Candidate
from wildlife_radar.profilegen.draft import (
    DEFAULT_DRAFT_DIR,
    build_draft,
    draft_path,
    load_doc,
    locked_values,
    write_draft,
)
from wildlife_radar.profilegen.extract import (
    EXTRACTION_FIELDS,
    Extractor,
    extraction_candidates,
)
from wildlife_radar.profilegen.identity import IdentityResolver, TaxonIdentity, save_identities
from wildlife_radar.profilegen.occurrence import diel_candidates, seasonality_candidates
from wildlife_radar.profilegen.reconcile import reconcile
from wildlife_radar.profilegen.traits import TetrapodTraits
from wildlife_radar.profilegen.wikipedia import WikipediaClient
from wildlife_radar.profiles.loader import DEFAULT_PROFILES_DIR


@dataclass
class GenerationReport:
    query_name: str
    taxon_id: str | None = None
    path: Path | None = None
    fields: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "query_name": self.query_name,
            "taxon_id": self.taxon_id,
            "path": str(self.path) if self.path else None,
            "fields": self.fields,
            "conflicts": self.conflicts,
            "rejected_extractions": self.rejected,
            "notes": self.notes,
        }


@dataclass
class Generator:
    resolver: IdentityResolver
    traits: TetrapodTraits | None = None
    store: duckdb.DuckDBPyConnection | None = None
    region_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    wiki: WikipediaClient | None = None
    extractor: Extractor | None = None
    out_dir: Path = DEFAULT_DRAFT_DIR
    curated_dir: Path = DEFAULT_PROFILES_DIR / "species"
    now: datetime | None = None

    def candidates(self, ident: TaxonIdentity, report: GenerationReport) -> list[Candidate]:
        out: list[Candidate] = []
        if self.traits is not None:
            out += self.traits.candidates(ident.names)
        if self.store is not None and self.region_id and ident.taxon_id:
            out += seasonality_candidates(self.store, self.region_id, ident.alias_ids)
            out += diel_candidates(self.store, ident.alias_ids, self.bbox)
        if self.wiki is not None and self.extractor is not None:
            if not ident.wikipedia_title:
                report.notes.append("no English Wikipedia article linked on Wikidata")
            else:
                try:
                    article = self.wiki.fetch(ident.wikipedia_title)
                except ConnectorError as exc:
                    report.notes.append(str(exc))
                else:
                    result = self.extractor.extract(article, ident.names, EXTRACTION_FIELDS)
                    if result.error:
                        report.notes.append(f"extraction: {result.error}")
                    cands, checks = extraction_candidates(
                        result, article, ident.names, ident.common_name
                    )
                    out += cands
                    report.rejected += [f"{c.field}: {c.reason}" for c in checks if not c.accepted]
                    self._save_checks(ident, article.citation, result.extractor, checks, result)
        return out

    def _save_checks(self, ident, citation, extractor, checks, result) -> None:
        """Audit trail for reviewers (includes quoted evidence, so it stays under data/)."""
        path = self.out_dir.parent / "extractions" / f"{ident.taxon_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "source": citation,
                    "extractor": extractor,
                    "raw": [e.model_dump() for e in result.extractions],
                    "checks": [c.model_dump() for c in checks],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    def run(self, names: Sequence[str]) -> list[GenerationReport]:
        idents = self.resolver.resolve_many(list(names))
        if self.store is not None:
            save_identities(self.store, idents)
        reports = []
        for ident in idents:
            report = GenerationReport(query_name=ident.query_name, taxon_id=ident.taxon_id)
            reports.append(report)
            if not ident.resolved:
                report.notes += ident.notes or ["could not resolve the name"]
                continue
            candidates = self.candidates(ident, report)
            existing = load_doc(draft_path(self.out_dir, ident.taxon_id))
            rec = reconcile(candidates, locked=locked_values(existing))
            doc = build_draft(ident, rec, existing=existing, now=self.now)
            report.path = write_draft(doc, self.out_dir)
            report.fields = sorted(rec.values)
            report.conflicts = [c.field for c in rec.conflicts]
            report.notes += doc.get("generation", {}).get("notes", [])
            if (self.curated_dir / f"{ident.taxon_id}.yaml").exists():
                report.notes.append(
                    "a curated profile exists; this draft is for comparison and review"
                )
        return reports
