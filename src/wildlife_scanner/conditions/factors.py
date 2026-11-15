"""Environmental factors that can shape encounters, at two time scales (one registry).

- **Daily factors** (water temperature and its anomaly, the day's low tide and range, moon
  illumination and phase, air temperature, wind) vary from day to day. They enter the daily
  forecast as Level-1 terms (conditions/levels.py), fitted from dated records.
- **Hourly factors** (diel phase, hours since sunset, moonlight, tide stage and height) vary
  within a day. Dated records can't see them; they are fitted from iNaturalist's hourly
  counts (conditions/hourly.py) and spread the daily forecast across the hours of a day.

Which factors a taxon is tested for comes from its profile (signals it declares) plus
defaults for its taxon group (``GROUP_DEFAULTS``), so species without a profile are covered
too. Every factor must pass a held-out gate before it changes a forecast: candidates are
cheap, claims are not.
"""

from __future__ import annotations

from dataclasses import dataclass

from wildlife_scanner.conditions.daily import DAILY_SIGNALS
from wildlife_scanner.conditions.model import TermSpec

DIEL = ("day", "dawn", "dusk", "night")
"""Day first: the reference level of the categorical term."""
TIDE_STAGE = ("rising", "high", "falling", "low")
MOONLIGHT = ("day", "dark", "moonlit")
SUNSET_BINS = ((0, 1), (1, 2), (2, 4), (4, 24))
SINCE_SUNSET = ("daylight", *(f"{a}-{b}h" for a, b in SUNSET_BINS))


@dataclass(frozen=True)
class Factor:
    id: str
    scale: str
    """``day`` (Level-1 terms) or ``hour`` (hourly availability)."""
    shape: str
    """Default shape: ``categorical``, ``linear``, ``optimum`` or ``cyclic``."""
    categories: tuple[str, ...] = ()
    description: str = ""


_DAILY_SHAPES = {"astro.moon_phase": "cyclic"}

FACTORS: dict[str, Factor] = {
    **{
        sid: Factor(sid, "day", _DAILY_SHAPES.get(sid, "linear"), description=s.description)
        for sid, s in DAILY_SIGNALS.items()
    },
    "astro.diel_phase": Factor(
        "astro.diel_phase",
        "hour",
        "categorical",
        DIEL,
        "day, dawn (civil dawn to an hour after sunrise), dusk (an hour before sunset to "
        "civil dusk), night",
    ),
    "astro.hours_since_sunset": Factor(
        "astro.hours_since_sunset", "hour", "categorical", SINCE_SUNSET, "hours after sunset"
    ),
    "astro.moonlight": Factor(
        "astro.moonlight",
        "hour",
        "categorical",
        MOONLIGHT,
        "night with the moon up and at least a quarter lit (moonlit), other nights (dark)",
    ),
    "tide.stage": Factor(
        "tide.stage",
        "hour",
        "categorical",
        TIDE_STAGE,
        "within an hour of a high or low, else rising or falling (NOAA predictions)",
    ),
    "tide.height_m": Factor(
        "tide.height_m", "hour", "optimum", description="predicted tide height (m MLLW)"
    ),
}

#: Profile signal ids that name an hourly factor differently.
ALIASES = {"astro.sun_altitude_deg": "astro.diel_phase"}

#: Hourly factors every taxon of a group is tested for (the gate keeps what helps).
GROUP_DEFAULTS: dict[str, tuple[str, ...]] = {
    "fishes": ("astro.diel_phase", "astro.moonlight", "tide.stage"),
    "birds": ("astro.diel_phase", "tide.stage"),
    "mammals": ("astro.diel_phase", "astro.moonlight"),
    "herps": ("astro.diel_phase",),
    "insects": ("astro.diel_phase",),
    "mollusks": ("astro.diel_phase", "tide.stage"),
}
TIDAL = {"tide.stage", "tide.height_m"}


def hourly_terms(group: str | None, profile=None, *, tides: bool = True) -> list[TermSpec]:
    """Candidate hourly terms for a taxon: its group's defaults plus the hourly signals its
    profile declares (with the profile's shape, strength and expectations). Tide terms are
    dropped where the region has no tide station."""
    chosen: dict[str, TermSpec] = {}
    for fid in GROUP_DEFAULTS.get(group or "", ("astro.diel_phase",)):
        f = FACTORS[fid]
        chosen[fid] = TermSpec(
            name=fid.split(".", 1)[1],
            signal=fid,
            shape=f.shape,
            strength="moderate",
            role="availability",
            categories=f.categories,
        )
    for name, spec in profile.signals.items() if profile else ():
        fid = ALIASES.get(spec.signal or name, spec.signal or name)
        f = FACTORS.get(fid)
        if f is None or f.scale != "hour":
            continue
        shape = f.shape if f.shape == "categorical" else (spec.shape or f.shape)
        chosen[fid] = TermSpec(
            name=name,
            signal=fid,
            shape=shape if shape in ("categorical", "linear", "optimum", "peak") else f.shape,
            strength=spec.strength or "moderate",
            hypothesis=spec.hypothesis,
            role=spec.role,
            direction=spec.direction,
            categories=f.categories if shape == "categorical" else (),
        )
    return [t for fid, t in chosen.items() if tides or fid not in TIDAL]
