"""Helpers for derived signals computed from stored series."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from wildlife_radar.core.signals import SignalValue
from wildlife_radar.core.time import ensure_utc


def interpolate_linear(values: Sequence[SignalValue], t: datetime) -> float | None:
    """Linear interpolation of a series (sorted by ``valid_time``) at ``t``.

    Returns ``None`` outside the series range or when a bracketing value is missing.
    """
    t = ensure_utc(t)
    pts = [(v.valid_time, v.value) for v in values if v.value is not None]
    if not pts:
        return None
    for (t0, v0), (t1, v1) in zip(pts, pts[1:], strict=False):
        if t0 <= t <= t1:
            if t1 == t0:
                return v0
            frac = (t - t0) / (t1 - t0)
            return v0 + frac * (v1 - v0)
    if pts[-1][0] == t:
        return pts[-1][1]
    return None


def tide_stage(extremes: Sequence[SignalValue], t: datetime) -> str | None:
    """``"rising"`` or ``"falling"`` from high/low events (``attrs['type']`` in ``H``/``L``)."""
    t = ensure_utc(t)
    prior = [e for e in extremes if e.valid_time <= t]
    if not prior:
        return None
    last = max(prior, key=lambda e: e.valid_time)
    kind = last.attrs.get("type")
    if kind == "L":
        return "rising"
    if kind == "H":
        return "falling"
    return None
