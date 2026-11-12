"""Phase 3: daily condition signals, Level 1 (conditions) and Level 2 (nowcast) models,
gates against the lower level, and the hypothesis scorecard."""

from __future__ import annotations

from wildlife_radar.conditions.daily import DAILY_SIGNALS
from wildlife_radar.conditions.model import TermSpec

#: Profile shapes → model shapes (categorical day-of-year terms are already in Level 0).
SHAPES = {
    "optimum": "optimum",
    "peak": "optimum",
    "linear": "linear",
    "monotone": "linear",
    None: "linear",
}


def terms_from_profile(profile) -> tuple[list[TermSpec], list[str]]:
    """Condition terms a profile declares that daily signals can support, plus notes on the
    rest (intra-day signals need timed records; others have no data source yet)."""
    terms, notes = [], []
    for name, spec in profile.signals.items():
        signal = spec.signal or name
        if signal not in DAILY_SIGNALS:
            notes.append(f"{name}: no daily data for {signal!r}")
            continue
        shape = "cyclic" if signal == "astro.moon_phase" else SHAPES.get(spec.shape)
        if shape is None:
            notes.append(f"{name}: shape {spec.shape!r} not supported for daily signals")
            continue
        terms.append(
            TermSpec(
                name=name,
                signal=signal,
                shape=shape,
                strength=spec.strength,
                hypothesis=spec.hypothesis,
                role=spec.role,
                direction=spec.direction,
            )
        )
    return terms, notes


__all__ = ["DAILY_SIGNALS", "TermSpec", "terms_from_profile"]
