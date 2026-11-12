"""The egress filter: the single enforcement point every public output passes through.

Observations are coarsened in space and time, delayed, stripped of revealing links, or dropped.
Predictions are aggregated to the tier's resolution and granularity, and lose their nowcast term
when the tier forbids it. Unknown taxa are treated as at least ``COARSE`` (fail closed).
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from wildlife_radar.core import spatial
from wildlife_radar.core.geometry import (
    CellsFootprint,
    PointFootprint,
    footprint_cells,
    footprint_centroid,
)
from wildlife_radar.core.observations import SENSITIVE_CONTEXTS, Observation, SensitivityFlags
from wildlife_radar.core.predictions import Confidence, Prediction
from wildlife_radar.core.time import coarsen_window, ensure_utc
from wildlife_radar.models.additive import NOWCAST, recompute_p
from wildlife_radar.policy.tiers import PolicyTier, rule_for

TierLookup = Callable[[str | None], PolicyTier]

_CONFIDENCE_ORDER = [Confidence.INSUFFICIENT, Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH]


@dataclass
class EgressReport:
    """What the filter did, for audit logs."""

    kept: int = 0
    dropped: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def drop(self, reason: str) -> None:
        self.dropped[reason] += 1


def _redacted_id(obs_id: str) -> str:
    return "redacted:" + hashlib.sha256(obs_id.encode()).hexdigest()[:16]


class EgressFilter:
    def __init__(self, tier_for: TierLookup) -> None:
        self._tier_for = tier_for

    def tier(self, taxon_id: str | None) -> PolicyTier:
        tier = self._tier_for(taxon_id)
        if taxon_id is None:
            tier = max(tier, PolicyTier.COARSE)
        return PolicyTier(tier)

    # ------------------------------------------------------------------ observations
    def filter_observations(
        self, observations: Iterable[Observation], now: datetime
    ) -> tuple[list[Observation], EgressReport]:
        now = ensure_utc(now)
        report = EgressReport()
        out: list[Observation] = []
        for obs in observations:
            public = self._filter_observation(obs, now, report)
            if public is not None:
                out.append(public)
                report.kept += 1
        return out, report

    def _filter_observation(
        self, obs: Observation, now: datetime, report: EgressReport
    ) -> Observation | None:
        flags = obs.sensitivity
        if flags.contexts & SENSITIVE_CONTEXTS:
            report.drop("sensitive_context")
            return None
        if flags.individual_id is not None:
            report.drop("named_or_collared_individual")
            return None
        if flags.embargoed_until is not None and flags.embargoed_until > now:
            report.drop("embargoed")
            return None
        if (flags.geoprivacy or "").lower() == "private":
            report.drop("private_geoprivacy")
            return None

        tier = self.tier(obs.taxon_id)
        rule = rule_for(tier)
        if rule.h3_res is None:
            report.drop("tier_withheld")
            return None
        if obs.time.end > now - rule.min_delay:
            report.drop("too_recent")
            return None

        # Never output finer than the tier allows, nor finer than the record's own uncertainty.
        res = rule.h3_res
        if isinstance(obs.footprint, PointFootprint) and obs.footprint.uncertainty_m:
            res = min(res, spatial.resolution_for_min_edge_km(obs.footprint.uncertainty_m / 1000))
        if isinstance(obs.footprint, PointFootprint):
            lat, lon = footprint_centroid(obs.footprint)
            cells = frozenset({spatial.cell_for_point(lat, lon, res)})
        else:
            cells = footprint_cells(obs.footprint, res)

        time_window = obs.time
        if rule.time_granularity is not None:
            time_window = coarsen_window(obs.time, rule.time_granularity)

        update: dict = {
            "footprint": CellsFootprint(cells=cells),
            "time": time_window,
            "sensitivity": SensitivityFlags(
                obscured=True if tier > PolicyTier.OPEN else flags.obscured,
                geoprivacy=flags.geoprivacy,
                taxon_geoprivacy=flags.taxon_geoprivacy,
            ),
            "extras": {},
        }
        if rule.redact_source_links:
            update |= {
                "obs_id": _redacted_id(obs.obs_id),
                "source_record_id": None,
                "source_url": None,
            }
        return obs.model_copy(update=update)

    # ------------------------------------------------------------------ predictions
    def filter_predictions(
        self, predictions: Iterable[Prediction]
    ) -> tuple[list[Prediction], EgressReport]:
        report = EgressReport()
        groups: dict[tuple, list[Prediction]] = defaultdict(list)
        tiers: dict[tuple, PolicyTier] = {}
        for pred in predictions:
            tier = self.tier(pred.taxon_id)
            rule = rule_for(tier)
            if rule.h3_res is None:
                report.drop("tier_withheld")
                continue
            if pred.cell is None:
                if tier > PolicyTier.OPEN:
                    report.drop("place_only_prediction_for_sensitive_tier")
                    continue
                key = (pred.taxon_id, None, pred.place_id, pred.time, pred.method_id)
            else:
                cell = spatial.coarsen_cell(pred.cell, rule.h3_res)
                window = (
                    coarsen_window(pred.time, rule.time_granularity)
                    if rule.time_granularity is not None
                    else pred.time
                )
                key = (pred.taxon_id, cell, None, window, pred.method_id)
            if not rule.allow_nowcast and NOWCAST in pred.contributions:
                contributions = {k: v for k, v in pred.contributions.items() if k != NOWCAST}
                pred = pred.model_copy(
                    update={"contributions": contributions, "p": recompute_p(contributions)}
                )
            groups[key].append(pred)
            tiers[key] = tier

        out = []
        for key, members in groups.items():
            out.append(_aggregate(key, members, tiers[key]))
            report.kept += 1
        return out, report


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _aggregate(key: tuple, members: list[Prediction], tier: PolicyTier) -> Prediction:
    taxon_id, cell, place_id, window, method_id = key
    first = members[0]
    contribution_keys = {k for m in members for k in m.contributions}
    contributions = {
        k: _mean([m.contributions.get(k, 0.0) for m in members]) for k in sorted(contribution_keys)
    }
    lifts = [m.lift_regional for m in members if m.lift_regional is not None]
    anomalies = [m.anomaly_vs_norm for m in members if m.anomaly_vs_norm is not None]
    seasonal = [m.seasonal_index for m in members if m.seasonal_index is not None]
    intervals = [m.interval for m in members if m.interval is not None]
    return Prediction(
        taxon_id=taxon_id,
        cell=cell,
        place_id=place_id,
        time=window,
        method_id=method_id,
        as_of=max(m.as_of for m in members),
        p=_mean([m.p for m in members]),
        interval=(
            (_mean([i[0] for i in intervals]), _mean([i[1] for i in intervals]))
            if len(intervals) == len(members)
            else None
        ),
        lift_regional=_mean(lifts) if lifts else None,
        anomaly_vs_norm=_mean(anomalies) if anomalies else None,
        seasonal_index=_mean(seasonal) if seasonal else None,
        confidence=min((m.confidence for m in members), key=_CONFIDENCE_ORDER.index),
        contributions=contributions,
        maturity_level=min(m.maturity_level for m in members),
        model_version=first.model_version,
        policy_tier_applied=int(tier),
    )


def allowed_in_place_first_special(tier: PolicyTier) -> bool:
    """Whether a taxon may appear in place-first 'special to here' / 'unusual now' lists."""
    return rule_for(tier).allow_place_first_special
