"""Assemble, write, regenerate and promote draft profiles.

Drafts go to ``data/profiles/generated/`` by default: they are derived from third-party data
and stay out of the repository until a reviewer promotes them. Promotion copies a draft into
``profiles/species/``, marks it ``reviewed`` and **locks** the fields the reviewer checked, so
later regeneration never changes them (a rejected field is locked as absent).

Drafts never contain ``policy``: tiers come only from status providers and human overrides.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from wildlife_radar.profilegen import PIPELINE_VERSION
from wildlife_radar.profilegen.identity import TaxonIdentity
from wildlife_radar.profilegen.reconcile import Reconciled
from wildlife_radar.profiles.loader import NON_INHERITED_KEYS, ProfileLibrary, deep_merge
from wildlife_radar.profiles.schema import GenerationInfo, SpeciesProfile

DEFAULT_DRAFT_DIR = Path(__file__).resolve().parents[3] / "data" / "profiles" / "generated"

DRAFT_NOTE = (
    "Generated draft. Values are weak priors and hypotheses with per-field provenance; observed "
    "data overrides them. Review fields in generation.review_queue first."
)


def _get(doc: dict[str, Any], path: str) -> Any:
    node: Any = doc
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set(doc: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = doc
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    if value is None:
        node.pop(parts[-1], None)
    else:
        node[parts[-1]] = value


def validate(doc: dict[str, Any], library: ProfileLibrary | None = None) -> SpeciesProfile:
    """Validate ``doc`` with its templates merged in (as the library would resolve it)."""
    lib = library or ProfileLibrary()
    merged: dict[str, Any] = {}
    for parent in doc.get("extends", []):
        inheritable = {k: v for k, v in lib.merged(parent).items() if k not in NON_INHERITED_KEYS}
        merged = deep_merge(merged, inheritable)
    return SpeciesProfile.model_validate(deep_merge(merged, doc))


def locked_values(existing: dict[str, Any] | None) -> dict[str, Any]:
    if not existing:
        return {}
    return {path: _get(existing, path) for path in existing.get("locked", [])}


def build_draft(
    ident: TaxonIdentity,
    rec: Reconciled,
    *,
    existing: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """A profile document for ``ident`` from reconciled values (respecting existing locks)."""
    if not ident.taxon_id or not ident.accepted_name:
        raise ValueError(f"unresolved taxon {ident.query_name!r}")
    doc: dict[str, Any] = {
        "id": ident.taxon_id,
        "kind": "species",
        "scientific_name": ident.accepted_name,
        "common_name": ident.common_name,
        "extends": [f"group/{ident.taxon_group}"],
        "status": "draft",
        "prior": {"seasonal": "learned"},
    }
    for path, value in rec.values.items():
        _set(doc, path, copy.deepcopy(value))
    doc["provenance"] = {
        k: p.model_dump(mode="json", exclude_none=True) for k, p in rec.provenance.items()
    }
    doc["crosswalk"] = {
        scheme: value
        for scheme, value in sorted(ident.ids.items())
        if ident.verified.get(scheme, scheme not in ("inaturalist",))
    }
    if ident.wikidata:
        doc["crosswalk"]["wikidata"] = ident.wikidata
    notes = [*ident.notes, *rec.notes]
    if ident.iucn_category:
        notes.append(f"Wikidata IUCN category {ident.iucn_category} (status hint for tiering only)")
    doc["generation"] = GenerationInfo(
        pipeline_version=PIPELINE_VERSION,
        generated_at=now or datetime.now(UTC),
        licenses=rec.licenses,
        open_variant=rec.open_variant,
        conflicts=rec.conflicts,
        review_queue=rec.review_queue,
        notes=notes,
    ).model_dump(mode="json")
    doc["notes"] = DRAFT_NOTE
    if existing:
        doc = apply_locks(doc, existing)
    doc.pop("policy", None)  # never generated
    validate(doc)
    return {k: v for k, v in doc.items() if v not in (None, {}, [])}


def apply_locks(doc: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    locks = existing.get("locked", [])
    if not locks:
        return doc
    out = copy.deepcopy(doc)
    for path in locks:
        _set(out, path, copy.deepcopy(_get(existing, path)))
        prov = (existing.get("provenance") or {}).get(path)
        if prov is not None:
            out.setdefault("provenance", {})[path] = copy.deepcopy(prov)
        else:
            out.get("provenance", {}).pop(path, None)
    out["locked"] = list(locks)
    for key in ("extends", "common_name", "methods", "guilds", "signals", "sources", "policy"):
        if key in existing and key in locks:
            out[key] = copy.deepcopy(existing[key])
    unlocked_changed = any(
        _get(out, p) != _get(existing, p) for p in (out.get("provenance") or {}) if p not in locks
    )
    if existing.get("status") == "reviewed" and not unlocked_changed:
        out["status"] = "reviewed"
    return out


def dump(doc: dict[str, Any]) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


def draft_path(out_dir: Path, taxon_id: str) -> Path:
    return out_dir / f"{taxon_id}.yaml"


def write_draft(doc: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = draft_path(out_dir, doc["id"])
    path.write_text(dump(doc), encoding="utf-8")
    return path


def load_doc(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def promote(
    draft: dict[str, Any],
    *,
    reviewer: str,
    lock: Sequence[str],
    reject: Sequence[str] = (),
    existing: dict[str, Any] | None = None,
    today: datetime | None = None,
) -> dict[str, Any]:
    """Reviewed copy of ``draft``: accepted fields locked, rejected fields removed and locked."""
    if not reviewer.strip():
        raise ValueError("promotion needs a reviewer")
    doc = copy.deepcopy(draft)
    if existing:
        doc = apply_locks(doc, existing)
    provenance = doc.setdefault("provenance", {})
    unknown = [f for f in [*lock, *reject] if f not in provenance and _get(doc, f) is None]
    if unknown:
        raise ValueError(f"no such fields in the draft: {unknown}")
    for field in lock:
        if field in provenance:
            provenance[field]["review"] = "accepted"
    for field in reject:
        _set(doc, field, None)
        provenance.pop(field, None)
    doc["locked"] = sorted(set(doc.get("locked", [])) | set(lock) | set(reject))
    doc["status"] = "reviewed"
    when = (today or datetime.now(UTC)).date().isoformat()
    gen = doc.setdefault("generation", {})
    gen.setdefault("notes", []).append(
        f"reviewed by {reviewer} on {when}: locked {sorted(lock)}, rejected {sorted(reject)}"
    )
    gen["review_queue"] = [f for f in gen.get("review_queue", []) if f not in doc["locked"]]
    validate(doc)
    return doc
