"""Load profile documents and resolve inheritance (``base`` → guild templates → species)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from wildlife_radar.profiles.schema import SpeciesProfile

#: ``profiles/`` at the repository root (works for source checkouts and editable installs).
DEFAULT_PROFILES_DIR = Path(__file__).resolve().parents[3] / "profiles"

#: List-valued keys that accumulate through inheritance instead of being replaced.
UNION_LIST_KEYS = frozenset({"always_suppress", "guilds"})

#: Keys that describe the document itself and are never inherited from parents.
NON_INHERITED_KEYS = frozenset(
    {"id", "kind", "extends", "scientific_name", "common_name", "status", "notes"}
)


class ProfileError(ValueError):
    pass


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge mappings; lists and scalars in ``override`` replace those in ``base``,
    except ``UNION_LIST_KEYS``, which accumulate (order-preserving, de-duplicated)."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        elif key in UNION_LIST_KEYS and isinstance(value, list) and isinstance(out.get(key), list):
            out[key] = list(dict.fromkeys([*out[key], *value]))
        else:
            out[key] = copy.deepcopy(value)
    return out


class ProfileLibrary:
    def __init__(self, root: Path | str = DEFAULT_PROFILES_DIR) -> None:
        self.root = Path(root)
        self._raw: dict[str, dict[str, Any]] = {}
        self._paths: dict[str, Path] = {}
        if not self.root.is_dir():
            raise ProfileError(f"profiles directory not found: {self.root}")
        for path in sorted(self.root.rglob("*.yaml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or "id" not in doc:
                raise ProfileError(f"{path}: profile documents need an 'id'")
            pid = doc["id"]
            if pid in self._raw:
                raise ProfileError(f"duplicate profile id {pid!r} in {path} and {self._paths[pid]}")
            self._raw[pid] = doc
            self._paths[pid] = path

    def ids(self, kind: str | None = None) -> list[str]:
        return sorted(
            pid for pid, doc in self._raw.items() if kind is None or doc.get("kind") == kind
        )

    def path(self, profile_id: str) -> Path:
        return self._paths[profile_id]

    def raw(self, profile_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._raw[profile_id])
        except KeyError:
            raise ProfileError(f"unknown profile {profile_id!r}") from None

    def merged(self, profile_id: str) -> dict[str, Any]:
        return self._merged(profile_id, ())

    def _merged(self, profile_id: str, stack: tuple[str, ...]) -> dict[str, Any]:
        if profile_id in stack:
            raise ProfileError(f"inheritance cycle: {' -> '.join([*stack, profile_id])}")
        doc = self.raw(profile_id)
        merged: dict[str, Any] = {}
        for parent in doc.get("extends", []):
            parent_doc = self._merged(parent, (*stack, profile_id))
            inheritable = {k: v for k, v in parent_doc.items() if k not in NON_INHERITED_KEYS}
            merged = deep_merge(merged, inheritable)
        return deep_merge(merged, doc)

    def resolve(self, profile_id: str) -> SpeciesProfile:
        try:
            return SpeciesProfile.model_validate(self.merged(profile_id))
        except ProfileError:
            raise
        except ValueError as exc:
            raise ProfileError(f"profile {profile_id!r} is invalid: {exc}") from exc

    def species(self) -> list[SpeciesProfile]:
        return [self.resolve(pid) for pid in self.ids(kind="species")]
