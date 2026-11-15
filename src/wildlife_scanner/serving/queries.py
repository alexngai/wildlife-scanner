"""Species-first and place-first queries over the Level-0 baseline, with policy enforcement.

Estimates exist per *effort group* (taxon group × effort class, e.g. ``birds:checklist`` or
``fishes:dive_survey``). Probabilities are only comparable within one effort group, so place
lists are grouped by it, and species queries use one effort group — the one matching the
requested method, or the taxon's best-sampled one.

Each taxon is answered at the finest baseline level its effective tier allows — fine cells for
open taxa, parent cells for generalized ones, context cells for coarse ones — and predictions
pass through the shared ``EgressFilter``. Place-first lists never rank tier ≥ COARSE taxa; those
appear only in an *awareness* list, without numbers. Withheld taxa are indistinguishable from
unknown ones.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import duckdb
import h3
from pydantic import BaseModel, Field

from wildlife_scanner.baseline.effort import METHOD_FOR_CLASS, label_for, method_for, split_egroup
from wildlife_scanner.baseline.estimate import Estimate, Level, estimate
from wildlife_scanner.connectors import ALL_SOURCES
from wildlife_scanner.core import spatial
from wildlife_scanner.core.licenses import KNOWN_LICENSES, UNKNOWN, combine
from wildlife_scanner.core.predictions import Confidence, Prediction
from wildlife_scanner.core.time import Granularity, Precision, TimeWindow
from wildlife_scanner.models.additive import PRIOR, logit
from wildlife_scanner.policy.egress import EgressFilter, allowed_in_place_first_special
from wildlife_scanner.policy.statuses import TierService
from wildlife_scanner.policy.tiers import PolicyTier, rule_for
from wildlife_scanner.regions import Region
from wildlife_scanner.storage.aliases import alias_map
from wildlife_scanner.storage.observations import week_of

LEVEL0_LABEL = (
    "Level 0 baseline: how often this species is recorded here at this time of year, per unit "
    "of effort for the stated method (an outing for checklists and casual sightings, a survey "
    "unit for structured surveys). Based on historical records corrected for where observers "
    "go; not adjusted for current conditions or recent sightings."
)
_CONFIDENCE_ORDER = [Confidence.INSUFFICIENT, Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH]
_LEVELS: tuple[Level, ...] = ("cell", "parent", "context")
AWARENESS_MESSAGE = (
    "Present in this wider area. Shown for awareness only: no location or timing details are "
    "given for sensitive species."
)


class NotAvailable(LookupError):
    """Unknown taxon, withheld taxon, or no data — deliberately indistinguishable."""


def week_window(year: int, week: int) -> TimeWindow:
    start = datetime.combine(date.fromisocalendar(year, week, 1), time(0), tzinfo=UTC)
    return TimeWindow(start=start, end=start + timedelta(days=7), precision=Precision.WEEK)


def month_window(d: date) -> TimeWindow:
    first = d.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return TimeWindow(
        start=datetime.combine(first, time(0), tzinfo=UTC),
        end=datetime.combine(nxt, time(0), tzinfo=UTC),
        precision=Precision.MONTH,
    )


def week_thursday(year: int, week: int) -> date:
    """ISO convention: a week belongs to the month containing its Thursday."""
    return date.fromisocalendar(year, week, 4)


def confidence_for(n_eff: float, n_region: float) -> Confidence:
    if n_region < 5:
        return Confidence.INSUFFICIENT
    if n_eff >= 20:
        return Confidence.HIGH
    if n_eff >= 5:
        return Confidence.MEDIUM
    return Confidence.LOW


def _cap(conf: Confidence, cap: Confidence) -> Confidence:
    return min(conf, cap, key=_CONFIDENCE_ORDER.index)


def distinctiveness(p: float, ratio: float | None) -> float:
    """``p · ln(ratio)``: high only when a taxon is both likely and distinctive.

    Ranking by the ratio alone favors rarely recorded taxa whose tiny probabilities produce huge
    ratios; weighting by ``p`` (the expected excess, as in an information-gain term) does not.
    """
    if not ratio or ratio <= 1:
        return 0.0
    return p * math.log(ratio)


class LicenseInfo(BaseModel):
    license_ids: list[str]
    noncommercial: bool
    share_alike: bool
    fully_open: bool
    attribution: list[str]


class EffortGroupSummary(BaseModel):
    group_id: str
    label: str
    method: str
    records: int
    gate: dict | None = None


class TaxonSummary(BaseModel):
    taxon_id: str
    scientific_name: str | None
    common_name: str | None = None
    group: str | None
    """Taxon group (birds, fishes, …)."""
    records_visits: int
    tier: int
    mode: str
    """``forecast`` (tiers 0–1) or ``awareness`` (tier 2)."""
    gate: dict | None = None
    """Backtest gate of the primary (best-sampled) effort group."""
    effort_groups: list[EffortGroupSummary] = Field(default_factory=list)


class MapCell(BaseModel):
    cell: str
    resolution: int
    p: float
    lift: float | None
    seasonal_index: float | None
    confidence: Confidence


class SpeciesMap(BaseModel):
    taxon: TaxonSummary
    date: date
    time_window: TimeWindow
    resolution_km: float
    effort_group: str
    method: str
    cells: list[MapCell]
    maturity_level: int = 0
    label: str = LEVEL0_LABEL
    license: LicenseInfo


class CalendarEntry(BaseModel):
    start: date
    end: date
    p: float
    seasonal_index: float | None
    confidence: Confidence


class Calendar(BaseModel):
    taxon: TaxonSummary
    cell: str
    resolution_km: float
    granularity: str
    effort_group: str
    method: str
    entries: list[CalendarEntry]
    area_fallback: bool = False
    label: str = LEVEL0_LABEL
    license: LicenseInfo


class PlaceItem(BaseModel):
    taxon_id: str
    scientific_name: str | None
    common_name: str | None
    group: str | None
    p: float
    lift: float | None
    seasonal_index: float | None
    confidence: Confidence
    resolution_km: float


class AwarenessItem(BaseModel):
    taxon_id: str
    scientific_name: str | None
    common_name: str | None
    group: str | None
    message: str


class GroupLists(BaseModel):
    """Lists for one effort group; probabilities are comparable only within it."""

    group: str
    """Effort group id, e.g. ``birds:checklist``."""
    taxon_group: str
    effort_class: str
    label: str
    method: str
    most_likely: list[PlaceItem] = Field(default_factory=list)
    special_here: list[PlaceItem] = Field(default_factory=list)
    peaking_now: list[PlaceItem] = Field(default_factory=list)
    new_for_you: list[PlaceItem] = Field(default_factory=list)
    license: LicenseInfo | None = None


class PlaceLists(BaseModel):
    date: date
    week: int
    groups: list[GroupLists] = Field(default_factory=list)
    awareness: list[AwarenessItem] = Field(default_factory=list)
    area_fallback: list[str] = Field(default_factory=list)
    label: str = LEVEL0_LABEL

    def group(self, name: str) -> GroupLists | None:
        return next((g for g in self.groups if g.group == name), None)


#: One-character confidence codes, worst first (static map files).
_CONF_CODES = "ilmh"
_CONF_RANK = {
    Confidence.INSUFFICIENT: 0,
    Confidence.LOW: 1,
    Confidence.MEDIUM: 2,
    Confidence.HIGH: 3,
}


@dataclass
class MapSegment:
    """Weeks of a year sharing one tier, as a cells × periods matrix (static products)."""

    tier: int
    granularity: str
    """``week`` (periods are ISO weeks) or ``month`` (periods are months)."""
    resolution: int
    resolution_km: float
    periods: list[int]
    cells: list[str]
    p: list[list[float | None]]
    """``p[cell][period]``; ``None`` where the cell has no estimate in that period."""
    confidence: list[str]
    """Per cell, one character per period: i(nsufficient), l(ow), m(edium), h(igh), - none."""
    ref_resolution: int | None
    """Lift reference: the parent cell at this resolution, or the region when ``None``."""
    ref_p: dict[str, list[float | None]]
    region_p: list[float | None]


@dataclass(frozen=True)
class _TaxonInfo:
    name: str | None
    taxon_group: str
    records: int
    egroups: tuple[tuple[str, str, int], ...]
    """(group_id, effort_class, records), best-sampled first."""


def _matches(group_id: str, selector: str | None) -> bool:
    """A selector is a taxon group (``fishes``), effort group, effort class or method id."""
    if selector is None:
        return True
    taxon_group, effort_class = split_egroup(group_id)
    return selector in {
        group_id,
        taxon_group,
        effort_class,
        METHOD_FOR_CLASS.get(effort_class, ""),
    }


class BaselineQueries:
    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        region: Region,
        tiers: TierService,
        profiles=None,
    ) -> None:
        self._conn = conn
        self.region = region
        self.tiers = tiers
        self.profiles = profiles
        build = conn.execute(
            "SELECT model_version, built_at, res, parent_res, context_res, shrinkage "
            "FROM prior_builds WHERE region_id = ?",
            [region.id],
        ).fetchone()
        if build is None:
            raise LookupError(f"no baseline has been built for region {region.id!r}")
        self.model_version, built_at, res, parent_res, context_res, self.shrinkage = build
        self.level_res = {"cell": res, "parent": parent_res, "context": context_res}
        self.as_of = built_at.replace(tzinfo=UTC)
        rows = conn.execute(
            "SELECT taxon_id, group_id, taxon_group, effort_class, scientific_name, n_visits "
            "FROM prior_taxa WHERE region_id = ? ORDER BY n_visits DESC",
            [region.id],
        ).fetchall()
        grouped: dict[str, list[tuple]] = defaultdict(list)
        for row in rows:
            grouped[row[0]].append(row)
        self._taxa: dict[str, _TaxonInfo] = {
            t: _TaxonInfo(
                name=rs[0][4],
                taxon_group=rs[0][2],
                records=sum(r[5] for r in rs),
                egroups=tuple((r[1], r[3], int(r[5])) for r in rs),
            )
            for t, rs in grouped.items()
        }
        self._species_profiles = set(profiles.ids(kind="species")) if profiles else set()
        self._gates: dict[tuple[str, str], dict] = {}
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "baseline_gates" in tables:
            for taxon_id, group_id, n_pos, bss, passes in conn.execute(
                "SELECT taxon_id, group_id, n_pos, bss, passes FROM baseline_gates "
                "WHERE region_id = ?",
                [region.id],
            ).fetchall():
                self._gates[(taxon_id, group_id)] = {
                    "n_pos": n_pos,
                    "bss": bss,
                    "passes": passes,
                }
        self._licenses = self._load_licenses(conn)
        self._aliases = alias_map(conn)
        # Display names from the identity crosswalk (published bundles carry taxon_names).
        self._names: dict[str, str] = {}
        if "taxon_names" in tables:
            self._names = dict(
                conn.execute(
                    "SELECT taxon_id, common_name FROM taxon_names WHERE common_name IS NOT NULL"
                ).fetchall()
            )

    # ------------------------------------------------------------------ helpers
    def _load_licenses(self, conn: duckdb.DuckDBPyConnection) -> dict[str, LicenseInfo]:
        by_group: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for group, source, lic in conn.execute(
            "SELECT DISTINCT group_id, source_id, license_id FROM prior_licenses "
            "WHERE region_id = ?",
            [self.region.id],
        ).fetchall():
            by_group[group].append((source, lic))
        out = {}
        for group, pairs in by_group.items():
            constraints = combine(KNOWN_LICENSES.get(lic, UNKNOWN) for _, lic in pairs)
            out[group] = LicenseInfo(
                license_ids=sorted(constraints.license_ids),
                noncommercial=constraints.noncommercial,
                share_alike=constraints.share_alike,
                fully_open=constraints.fully_open,
                attribution=[
                    ALL_SOURCES[s].attribution if s in ALL_SOURCES else f"Data source: {s}"
                    for s in sorted({s for s, _ in pairs})
                ],
            )
        return out

    def _estimate(self, level: Level, **filters) -> list[Estimate]:
        return estimate(self._conn.cursor(), self.region.id, level, self.shrinkage, **filters)

    def common_name(self, taxon_id: str) -> str | None:
        from wildlife_scanner.core.names import display_common_name

        if taxon_id in self._species_profiles:
            name = self.profiles.resolve(taxon_id).common_name
            if name:
                return display_common_name(name)
        return display_common_name(self._names.get(taxon_id))

    def license_for(self, groups: list[str | None]) -> LicenseInfo:
        infos = [self._licenses[g] for g in groups if g in self._licenses]
        return LicenseInfo(
            license_ids=sorted({lic for i in infos for lic in i.license_ids}),
            noncommercial=any(i.noncommercial for i in infos),
            share_alike=any(i.share_alike for i in infos),
            fully_open=all(i.fully_open for i in infos),
            attribution=sorted({a for i in infos for a in i.attribution}),
        )

    def _canon(self, taxon_id: str) -> str:
        """Another name of a merged concept resolves to its canonical id."""
        return self._aliases.get(taxon_id, taxon_id)

    def _tier(self, taxon_id: str, on: date) -> PolicyTier:
        if taxon_id not in self._taxa:
            raise NotAvailable(taxon_id)
        tier = self.tiers.get(taxon_id, on)
        if tier >= PolicyTier.WITHHELD:
            raise NotAvailable(taxon_id)
        return tier

    def _level_for(self, tier: PolicyTier) -> Level:
        """Finest baseline level whose resolution the tier allows."""
        rule_res = rule_for(tier).h3_res
        for level in _LEVELS:
            if rule_res is not None and self.level_res[level] <= rule_res:
                return level
        raise NotAvailable("no permissible resolution")

    @staticmethod
    def _coarser(level: Level) -> list[Level]:
        return list(_LEVELS[_LEVELS.index(level) :])

    def _choose_group(self, taxon_id: str, method: str | None) -> str:
        for group_id, _, _ in self._taxa[taxon_id].egroups:
            if _matches(group_id, method):
                return group_id
        raise NotAvailable(taxon_id)

    def taxon_summary(self, taxon_id: str, on: date) -> TaxonSummary:
        taxon_id = self._canon(taxon_id)
        tier = self._tier(taxon_id, on)
        info = self._taxa[taxon_id]
        primary = info.egroups[0][0]
        return TaxonSummary(
            taxon_id=taxon_id,
            scientific_name=info.name,
            common_name=self.common_name(taxon_id),
            group=info.taxon_group,
            records_visits=info.records,
            tier=int(tier),
            mode="awareness" if tier >= PolicyTier.COARSE else "forecast",
            gate=self._gates.get((taxon_id, primary)),
            effort_groups=[
                EffortGroupSummary(
                    group_id=g,
                    label=label_for(g),
                    method=method_for(g),
                    records=n,
                    gate=self._gates.get((taxon_id, g)),
                )
                for g, _, n in info.egroups
            ],
        )

    def _prediction(
        self, e: Estimate, year: int, monthly: bool, cap: Confidence | None = None
    ) -> Prediction:
        conf = confidence_for(e.n_eff, e.n_region)
        window = month_window(week_thursday(year, e.week)) if monthly else week_window(year, e.week)
        return Prediction(
            taxon_id=e.taxon_id,
            cell=e.cell,
            time=window,
            method_id=method_for(e.group_id),
            as_of=self.as_of,
            p=min(max(e.p, 0.0), 1.0),
            lift_regional=e.lift,
            seasonal_index=e.seasonal_index,
            confidence=_cap(conf, cap) if cap else conf,
            contributions={PRIOR: logit(e.p)},
            maturity_level=0,
            model_version=self.model_version,
        )

    # ------------------------------------------------------------------ species-first
    def list_taxa(
        self, on: date, q: str | None = None, group: str | None = None, limit: int = 50
    ) -> list[TaxonSummary]:
        out = []
        for taxon_id, info in sorted(self._taxa.items(), key=lambda kv: -kv[1].records):
            if group and not any(_matches(g, group) for g, _, _ in info.egroups):
                continue
            if q and q.lower() not in f"{taxon_id} {info.name or ''}".lower():
                continue
            try:
                out.append(self.taxon_summary(taxon_id, on))
            except NotAvailable:
                continue
            if len(out) >= limit:
                break
        return out

    def species_map(self, taxon_id: str, on: date, method: str | None = None) -> SpeciesMap:
        taxon_id = self._canon(taxon_id)
        summary = self.taxon_summary(taxon_id, on)
        group_id = self._choose_group(taxon_id, method)
        tier = PolicyTier(summary.tier)
        year, weeks, monthly = self._map_period(tier, on)
        estimates = self._estimate(
            self._level_for(tier), taxon_ids=[taxon_id], groups=[group_id], weeks=weeks
        )
        return self._build_map(summary, group_id, tier, on, year, weeks, monthly, estimates)

    def species_maps(self, taxon_id: str, year: int, method: str | None = None) -> list[SpeciesMap]:
        """Every map of ``year``: what ``species_map`` returns for each week's Thursday, one map
        per month for monthly tiers, skipping withheld weeks. Tiers are evaluated per week
        (profiles can raise them seasonally); the estimates take one query per tier."""
        taxon_id = self._canon(taxon_id)
        group_id = self._choose_group(taxon_id, method)
        periods: dict[tuple, date] = {}
        for w in range(1, 53):
            on = week_thursday(year, w)
            try:
                tier = self._tier(taxon_id, on)
            except NotAvailable:
                continue
            yr, weeks, _ = self._map_period(tier, on)
            periods.setdefault((tier, yr, tuple(weeks)), on)
        by_tier: dict[PolicyTier, set[int]] = defaultdict(set)
        for tier, _, weeks in periods:
            by_tier[tier].update(weeks)
        estimates: dict[tuple[PolicyTier, int], list[Estimate]] = defaultdict(list)
        for tier, weeks in by_tier.items():
            for e in self._estimate(
                self._level_for(tier), taxon_ids=[taxon_id], groups=[group_id], weeks=sorted(weeks)
            ):
                estimates[(tier, e.week)].append(e)
        out = []
        for (tier, yr, weeks), on in periods.items():
            found = [e for w in weeks for e in estimates[(tier, w)]]
            summary = self.taxon_summary(taxon_id, on)
            monthly = rule_for(tier).time_granularity is Granularity.MONTH
            out.append(
                self._build_map(summary, group_id, tier, on, yr, list(weeks), monthly, found)
            )
        return out

    def species_matrix(
        self, taxon_id: str, year: int, method: str | None = None
    ) -> list[MapSegment]:
        """A year of maps as compact matrices, with the same policy as ``species_maps``.

        Weeks are grouped into **segments** sharing a tier (usually one). In each segment, a
        cell has one value per period (ISO week, or month for monthly tiers): the mean
        weekly ``p`` over the period's weeks and the lowest confidence among them, as
        ``EgressFilter`` aggregates predictions. Withheld weeks are absent. Built from one
        estimate query per tier with no per-cell objects, so a region's maps build in
        minutes (``species_maps`` stays the reference; tests check they agree).
        """
        taxon_id = self._canon(taxon_id)
        group_id = self._choose_group(taxon_id, method)
        # Periods, as species_maps forms them: a monthly tier covers every week of its month.
        periods: dict[tuple[PolicyTier, int, tuple[int, ...]], int] = {}
        for w in range(1, 53):
            on = week_thursday(year, w)
            try:
                tier = self._tier(taxon_id, on)
            except NotAvailable:
                continue
            yr, weeks, monthly = self._map_period(tier, on)
            periods.setdefault((tier, yr, tuple(weeks)), on.month if monthly else w)
        by_tier: dict[PolicyTier, dict[int, tuple[int, ...]]] = defaultdict(dict)
        for (tier, _yr, weeks), label in periods.items():
            by_tier[tier][label] = weeks
        segments = []
        for tier, labelled in sorted(by_tier.items()):
            level = self._level_for(tier)
            monthly = rule_for(tier).time_granularity is Granularity.MONTH
            wanted = sorted({w for weeks in labelled.values() for w in weeks})
            rows = self._estimate(level, taxon_ids=[taxon_id], groups=[group_id], weeks=wanted)
            by_week: dict[int, list[Estimate]] = defaultdict(list)
            for e in rows:
                by_week[e.week].append(e)
            labels = sorted(labelled)
            n = len(labels)
            p_sum: dict[str, list[float]] = defaultdict(lambda n=n: [0.0] * n)
            p_n: dict[str, list[int]] = defaultdict(lambda n=n: [0] * n)
            conf: dict[str, list[int]] = defaultdict(lambda n=n: [len(_CONF_CODES)] * n)
            ref_res = self.level_res["context"] if level != "context" else None
            ref_sum: dict[str, list[float]] = defaultdict(lambda n=n: [0.0] * n)
            ref_n: dict[str, list[int]] = defaultdict(lambda n=n: [0] * n)
            region = [0.0] * len(labels)
            region_n = [0] * len(labels)
            for i, label in enumerate(labels):
                for w in labelled[label]:
                    for e in by_week.get(w, ()):
                        p = min(max(e.p, 0.0), 1.0)
                        p_sum[e.cell][i] += p
                        p_n[e.cell][i] += 1
                        c = _CONF_RANK[confidence_for(e.n_eff, e.n_region)]
                        conf[e.cell][i] = min(conf[e.cell][i], c)
                        ref_key = h3.cell_to_parent(e.cell, ref_res) if ref_res else "region"
                        ref = e.p_context if ref_res else e.p_region
                        if ref is not None:
                            ref_sum[ref_key][i] += ref
                            ref_n[ref_key][i] += 1
                        region[i] += e.p_region
                        region_n[i] += 1
            cells = sorted(p_sum)
            segments.append(
                MapSegment(
                    tier=int(tier),
                    granularity="month" if monthly else "week",
                    resolution=self.level_res[level],
                    resolution_km=spatial.edge_km(self.level_res[level]),
                    periods=labels,
                    cells=cells,
                    p=[
                        [
                            round(p_sum[c][i] / p_n[c][i], 6) if p_n[c][i] else None
                            for i in range(len(labels))
                        ]
                        for c in cells
                    ],
                    confidence=[
                        "".join(_CONF_CODES[k] if k < len(_CONF_CODES) else "-" for k in conf[c])
                        for c in cells
                    ],
                    ref_resolution=ref_res,
                    ref_p={
                        k: [
                            round(ref_sum[k][i] / ref_n[k][i], 6) if ref_n[k][i] else None
                            for i in range(len(labels))
                        ]
                        for k in sorted(ref_sum)
                    },
                    region_p=[
                        round(region[i] / region_n[i], 6) if region_n[i] else None
                        for i in range(len(labels))
                    ],
                )
            )
        return segments

    @staticmethod
    def _map_period(tier: PolicyTier, on: date) -> tuple[int, list[int], bool]:
        """``(year, weeks, monthly)`` a map on ``on`` covers at the tier's time granularity."""
        if rule_for(tier).time_granularity is Granularity.MONTH:
            weeks = [w for w in range(1, 53) if week_thursday(on.year, w).month == on.month]
            return on.year, weeks, True
        return on.isocalendar().year, [week_of(on)], False

    def _build_map(
        self,
        summary: TaxonSummary,
        group_id: str,
        tier: PolicyTier,
        on: date,
        year: int,
        weeks: list[int],
        monthly: bool,
        estimates: list[Estimate],
    ) -> SpeciesMap:
        level = self._level_for(tier)
        preds = [self._prediction(e, year, monthly) for e in estimates]
        public, _ = EgressFilter(lambda _t: tier).filter_predictions(preds)
        if public:
            window = public[0].time
        else:
            window = month_window(on) if monthly else week_window(year, weeks[0])
        return SpeciesMap(
            taxon=summary,
            date=on,
            time_window=window,
            resolution_km=spatial.edge_km(self.level_res[level]),
            effort_group=group_id,
            method=method_for(group_id),
            cells=[
                MapCell(
                    cell=pr.cell,
                    resolution=h3.get_resolution(pr.cell),
                    p=round(pr.p, 6),
                    lift=round(pr.lift_regional, 4) if pr.lift_regional is not None else None,
                    seasonal_index=(
                        round(pr.seasonal_index, 4) if pr.seasonal_index is not None else None
                    ),
                    confidence=pr.confidence,
                )
                for pr in sorted(public, key=lambda x: -x.p)
            ],
            license=self.license_for([group_id]),
        )

    def calendar(
        self, taxon_id: str, lat: float, lon: float, year: int, method: str | None = None
    ) -> Calendar:
        taxon_id = self._canon(taxon_id)
        if not self.region.contains(lat, lon):
            raise ValueError("location is outside the region")
        summary = self.taxon_summary(taxon_id, date(year, 7, 1))
        group_id = self._choose_group(taxon_id, method)
        tier = PolicyTier(summary.tier)
        monthly = rule_for(tier).time_granularity is Granularity.MONTH
        level0 = self._level_for(tier)
        estimates: list[Estimate] = []
        used = level0
        for level in self._coarser(level0):
            target = spatial.cell_for_point(lat, lon, self.level_res[level])
            estimates = self._estimate(
                level, taxon_ids=[taxon_id], groups=[group_id], cells=[target]
            )
            if estimates:
                used = level
                break
        if not estimates:
            raise NotAvailable(taxon_id)
        fallback = used != level0
        cap = Confidence.LOW if fallback else None
        preds = [self._prediction(e, year, monthly, cap) for e in estimates]
        public, _ = EgressFilter(lambda _t: tier).filter_predictions(preds)
        public.sort(key=lambda pr: pr.time.start)
        mean_p = sum(pr.p for pr in public) / len(public)
        return Calendar(
            taxon=summary,
            cell=public[0].cell,
            resolution_km=spatial.edge_km(self.level_res[used]),
            granularity="month" if monthly else "week",
            effort_group=group_id,
            method=method_for(group_id),
            entries=[
                CalendarEntry(
                    start=pr.time.start.date(),
                    end=(pr.time.end - timedelta(seconds=1)).date(),
                    p=round(pr.p, 6),
                    seasonal_index=round(pr.p / mean_p, 4) if mean_p else None,
                    confidence=pr.confidence,
                )
                for pr in public
            ],
            area_fallback=fallback,
            license=self.license_for([group_id]),
        )

    # ------------------------------------------------------------------ place-first
    def place_lists(
        self,
        lat: float,
        lon: float,
        on: date,
        life_list: set[str] | None = None,
        limit: int = 20,
        min_p: float = 0.01,
        min_peak: float = 1.2,
        min_lift: float = 1.25,
        awareness_min_p: float = 0.002,
        group: str | None = None,
    ) -> PlaceLists:
        """Lists per effort group. ``group`` selects a taxon group, effort group/class or
        method id (e.g. ``fishes``, ``dive_survey`` or ``scuba_dive``)."""
        if not self.region.contains(lat, lon):
            raise ValueError("location is outside the region")
        week = week_of(on)
        result = PlaceLists(date=on, week=week)
        ctx = spatial.cell_for_point(lat, lon, self.level_res["context"])
        candidates = [
            row[0]
            for row in self._conn.cursor()
            .execute(
                "SELECT DISTINCT taxon_id FROM prior_mask WHERE region_id = ? AND context_cell = ?",
                [self.region.id, ctx],
            )
            .fetchall()
        ]
        by_level: dict[Level, list[str]] = defaultdict(list)
        aware: list[str] = []
        tiers: dict[str, PolicyTier] = {}
        for taxon_id in candidates:
            try:
                tiers[taxon_id] = self._tier(taxon_id, on)
            except NotAvailable:
                continue
            if not any(_matches(g, group) for g, _, _ in self._taxa[taxon_id].egroups):
                continue
            if tiers[taxon_id] >= PolicyTier.COARSE:
                aware.append(taxon_id)
            else:
                by_level[self._level_for(tiers[taxon_id])].append(taxon_id)

        # Awareness: context-level presence only, never numbers.
        if aware:
            seen: set[str] = set()
            for e in self._estimate("context", taxon_ids=aware, cells=[ctx], weeks=[week]):
                if e.p >= awareness_min_p and e.taxon_id not in seen:
                    seen.add(e.taxon_id)
                    info = self._taxa[e.taxon_id]
                    result.awareness.append(
                        AwarenessItem(
                            taxon_id=e.taxon_id,
                            scientific_name=info.name,
                            common_name=self.common_name(e.taxon_id),
                            group=info.taxon_group,
                            message=AWARENESS_MESSAGE,
                        )
                    )

        items: dict[str, list[tuple[PlaceItem, PolicyTier]]] = defaultdict(list)
        for level0, taxa in by_level.items():
            pending = {
                (t, g) for t in taxa for g, _, _ in self._taxa[t].egroups if _matches(g, group)
            }
            for level in self._coarser(level0):
                if not pending:
                    break
                target = spatial.cell_for_point(lat, lon, self.level_res[level])
                found = self._estimate(
                    level,
                    taxon_ids=sorted({t for t, _ in pending}),
                    cells=[target],
                    weeks=[week],
                )
                for e in found:
                    if (e.taxon_id, e.group_id) not in pending:
                        continue
                    pending.discard((e.taxon_id, e.group_id))
                    fallback = level != level0
                    if fallback and e.taxon_id not in result.area_fallback:
                        result.area_fallback.append(e.taxon_id)
                    conf = confidence_for(e.n_eff, e.n_region)
                    info = self._taxa[e.taxon_id]
                    items[e.group_id].append(
                        (
                            PlaceItem(
                                taxon_id=e.taxon_id,
                                scientific_name=info.name,
                                common_name=self.common_name(e.taxon_id),
                                group=info.taxon_group,
                                p=round(e.p, 6),
                                lift=round(e.lift, 4) if e.lift is not None else None,
                                seasonal_index=(
                                    round(e.seasonal_index, 4)
                                    if e.seasonal_index is not None
                                    else None
                                ),
                                confidence=_cap(conf, Confidence.LOW) if fallback else conf,
                                resolution_km=spatial.edge_km(self.level_res[level]),
                            ),
                            tiers[e.taxon_id],
                        )
                    )

        for group_id, members in sorted(items.items(), key=lambda kv: -len(kv[1])):
            taxon_group, effort_class = split_egroup(group_id)
            ranked = sorted(members, key=lambda it: -it[0].p)
            special = [
                i
                for i, t in members
                if allowed_in_place_first_special(t)
                and i.p >= min_p
                and (i.lift or 0) >= min_lift
                and i.confidence is not Confidence.INSUFFICIENT
                and i.taxon_id not in result.area_fallback
            ]
            peaking = [
                i
                for i, t in members
                if allowed_in_place_first_special(t)
                and i.p >= min_p
                and (i.seasonal_index or 0) >= min_peak
            ]
            result.groups.append(
                GroupLists(
                    group=group_id,
                    taxon_group=taxon_group,
                    effort_class=effort_class,
                    label=label_for(group_id),
                    method=method_for(group_id),
                    most_likely=[i for i, _ in ranked[:limit]],
                    special_here=sorted(special, key=lambda i: -distinctiveness(i.p, i.lift))[
                        :limit
                    ],
                    peaking_now=sorted(
                        peaking, key=lambda i: -distinctiveness(i.p, i.seasonal_index)
                    )[:limit],
                    new_for_you=(
                        [i for i, _ in ranked if i.taxon_id not in life_list][:limit]
                        if life_list
                        else []
                    ),
                    license=self.license_for([group_id]),
                )
            )
        result.awareness.sort(key=lambda a: a.scientific_name or a.taxon_id)
        return result
