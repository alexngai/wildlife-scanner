"""Licenses and license "taint tracking".

Every record carries the license it was published under. Derived products combine the
constraints of all their inputs (see ``combine``), so the ledger can label each published product
and build a fully open variant from CC0 / CC BY / public-domain inputs only.

License versions are normalized to the 4.0 entries for constraint purposes; keep the original
string in record extras if the exact version matters for attribution.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict


class License(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    url: str | None = None
    attribution: bool = True
    noncommercial: bool = False
    share_alike: bool = False
    no_derivatives: bool = False
    restricted: bool = False
    """All rights reserved, unknown, or custom terms requiring permission."""


def _cc(code: str, name: str, *, nc: bool = False, sa: bool = False, nd: bool = False) -> License:
    return License(
        id=f"CC-{code.upper()}-4.0",
        name=f"Creative Commons {name} 4.0",
        url=f"https://creativecommons.org/licenses/{code}/4.0/",
        noncommercial=nc,
        share_alike=sa,
        no_derivatives=nd,
    )


CC0 = License(
    id="CC0-1.0",
    name="CC0 1.0 Universal (public domain dedication)",
    url="https://creativecommons.org/publicdomain/zero/1.0/",
    attribution=False,
)
CC_BY = _cc("by", "Attribution")
CC_BY_SA = _cc("by-sa", "Attribution-ShareAlike", sa=True)
CC_BY_NC = _cc("by-nc", "Attribution-NonCommercial", nc=True)
CC_BY_NC_SA = _cc("by-nc-sa", "Attribution-NonCommercial-ShareAlike", nc=True, sa=True)
CC_BY_ND = _cc("by-nd", "Attribution-NoDerivatives", nd=True)
CC_BY_NC_ND = _cc("by-nc-nd", "Attribution-NonCommercial-NoDerivatives", nc=True, nd=True)
PUBLIC_DOMAIN_US_GOV = License(
    id="PD-USGov",
    name="US Government work (public domain, 17 USC 105)",
    attribution=False,
)
ALL_RIGHTS_RESERVED = License(id="ALL-RIGHTS-RESERVED", name="All rights reserved", restricted=True)
UNKNOWN = License(id="UNKNOWN", name="Unknown license", restricted=True)

KNOWN_LICENSES: dict[str, License] = {
    lic.id: lic
    for lic in (
        CC0,
        CC_BY,
        CC_BY_SA,
        CC_BY_NC,
        CC_BY_NC_SA,
        CC_BY_ND,
        CC_BY_NC_ND,
        PUBLIC_DOMAIN_US_GOV,
        ALL_RIGHTS_RESERVED,
        UNKNOWN,
    )
}

_CC_CODES: dict[str, License] = {
    "cc0": CC0,
    "cc-by": CC_BY,
    "cc-by-sa": CC_BY_SA,
    "cc-by-nc": CC_BY_NC,
    "cc-by-nc-sa": CC_BY_NC_SA,
    "cc-by-nd": CC_BY_ND,
    "cc-by-nc-nd": CC_BY_NC_ND,
}

_GBIF_ENUMS: dict[str, License] = {
    "CC0_1_0": CC0,
    "CC_BY_4_0": CC_BY,
    "CC_BY_NC_4_0": CC_BY_NC,
}

_CC_URL = re.compile(r"creativecommons\.org/licenses/([a-z-]+)/")


def parse_license(value: str | None, *, missing: License = ALL_RIGHTS_RESERVED) -> License:
    """Parse license strings used by common sources.

    Handles SPDX-like ids, iNaturalist codes (``cc-by-nc``), GBIF enums (``CC_BY_NC_4_0``) and
    Creative Commons URLs. ``None``/empty returns ``missing`` (iNaturalist uses a blank license for
    all-rights-reserved). Anything unrecognized is ``UNKNOWN`` (treated as restricted).
    """
    if value is None or not str(value).strip():
        return missing
    v = str(value).strip()
    if v in KNOWN_LICENSES:
        return KNOWN_LICENSES[v]
    low = v.lower()
    if low in _CC_CODES:
        return _CC_CODES[low]
    if v.upper() in _GBIF_ENUMS:
        return _GBIF_ENUMS[v.upper()]
    if "creativecommons.org/publicdomain/zero" in low:
        return CC0
    if (m := _CC_URL.search(low)) is not None:
        return _CC_CODES.get(f"cc-{m.group(1)}", UNKNOWN)
    if low in {"public domain", "public-domain", "pd"}:
        return CC0
    if low in {"pd-usgov", "us government work"}:
        return PUBLIC_DOMAIN_US_GOV
    return UNKNOWN


class UsageConstraints(BaseModel):
    """Combined constraints of all inputs to a derived product."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    license_ids: frozenset[str]
    attribution_required: bool
    noncommercial: bool
    share_alike: bool
    no_derivatives: bool
    restricted: bool

    @property
    def fully_open(self) -> bool:
        """Only CC0 / CC BY / public-domain inputs: reusable by anyone, for any purpose."""
        return not (
            self.noncommercial or self.share_alike or self.no_derivatives or self.restricted
        )

    @property
    def publishable_noncommercially(self) -> bool:
        """Whether a derived product may be published by a non-commercial project."""
        return not (self.restricted or self.no_derivatives)


def combine(licenses: Iterable[License]) -> UsageConstraints:
    """Most-restrictive combination of input licenses (no inputs → fully open)."""
    lics = list(licenses)
    return UsageConstraints(
        license_ids=frozenset(lic.id for lic in lics),
        attribution_required=any(lic.attribution for lic in lics),
        noncommercial=any(lic.noncommercial for lic in lics),
        share_alike=any(lic.share_alike for lic in lics),
        no_derivatives=any(lic.no_derivatives for lic in lics),
        restricted=any(lic.restricted for lic in lics),
    )
