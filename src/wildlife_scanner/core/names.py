"""Display forms of names."""

from __future__ import annotations

_MINOR = {"a", "an", "and", "at", "by", "de", "del", "in", "of", "on", "or", "the", "to"}


def display_common_name(name: str | None) -> str | None:
    """Common names in title case, as most sources write them ("Coyote Brush").

    Sources mix "coyote brush" with "European Searocket". Names with any capital letter are
    kept as written (they follow a source's own rules, e.g. "Black-crowned Night-Heron");
    all-lowercase names get each word capitalised, except short joining words inside the
    name, and the part after a hyphen keeps its case ("Bird's-foot Trefoil")."""
    if not name or any(c.isupper() for c in name):
        return name
    words = name.split(" ")
    out = []
    for i, w in enumerate(words):
        if i > 0 and w in _MINOR:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)
