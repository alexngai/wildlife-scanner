"""Identifier helpers, including privacy-preserving hashing of personal identifiers.

Observer names and user ids are personal data. We keep only salted hashes, which are enough to
group records into "visits" (same observer, day and place) without storing who the observer is.
Set ``WILDLIFE_RADAR_HASH_SALT`` per deployment so hashes can't be matched across deployments.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable

HASH_SALT_ENV = "WILDLIFE_RADAR_HASH_SALT"
_DEFAULT_SALT = "wildlife-radar"


def hash_identifier(value: str | Iterable[str] | None) -> str | None:
    """Salted, truncated SHA-256 of an identifier (or of several, order-independent)."""
    if value is None:
        return None
    if not isinstance(value, str):
        parts = sorted(str(v).strip() for v in value if v is not None and str(v).strip())
        if not parts:
            return None
        value = "|".join(parts)
    value = value.strip()
    if not value:
        return None
    salt = os.environ.get(HASH_SALT_ENV, _DEFAULT_SALT)
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:16]
