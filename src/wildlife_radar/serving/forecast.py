"""Daily forecasts: Level 0 adjusted by gated Level 1 (conditions) and Level 2 (nowcast) terms.

A forecast is shown at the highest level whose backtest gate passed for that taxon and effort
group, and is labeled with that level (framework.md §5.4). Each condition term reports its
contribution to the log-odds and the signal value it used: the "why".

Policy: day-level forecasts are finer than the week granularity of non-OPEN tiers, so only
OPEN taxa get Level 1–2; other tiers get their Level-0 estimate, at the tier's resolution, with
a note. Withheld taxa raise ``NotAvailable`` like unknown ones.

Signals for a day without an observation (e.g. today's water temperature not yet reported)
persist the latest value from the previous few days; predictable signals (tides, moon) are
available ahead.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

import numpy as np
from pydantic import BaseModel, Field

from wildlife_radar.baseline.builder import BaselineConfig, create_training_view
from wildlife_radar.baseline.effort import DatasetRegistry, method_for, split_egroup
from wildlife_radar.conditions.levels import SignalLookup, stations_in_store
from wildlife_radar.conditions.model import OffsetLogit, model_from_dict
from wildlife_radar.core import spatial
from wildlife_radar.policy.tiers import PolicyTier
from wildlife_radar.serving.queries import BaselineQueries, NotAvailable, TaxonSummary
from wildlife_radar.storage.observations import week_of

PERSIST_DAYS = 7
TIDE_REACH_KM = 40
"""Hourly tide factors use the nearest station within this distance."""


class Driver(BaseModel):
    term: str
    signal: str
    value: float | None
    contribution: float
    """Change in log-odds from this term (positive raises the probability)."""
    hypothesis: bool


class Forecast(BaseModel):
    taxon: TaxonSummary
    day: date
    cell: str
    resolution_km: float
    effort_group: str
    method: str
    level: int
    """0 = baseline, 1 = conditions, 2 = conditions + recent sightings."""
    p: float
    p_level0: float
    drivers: list[Driver] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CellForecast(BaseModel):
    cell: str
    p: float
    p_level0: float
    drivers: list[Driver] = Field(default_factory=list)


class MapForecast(BaseModel):
    """A day's forecast for every cell of a species' weekly map (or the cells asked for)."""

    taxon: TaxonSummary
    day: date
    resolution_km: float
    effort_group: str
    method: str
    level: int
    """0 = baseline, 1 = conditions, 2 = conditions + recent sightings (same for every cell)."""
    cells: list[CellForecast] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RecentItem(BaseModel):
    taxon_id: str
    scientific_name: str | None
    common_name: str | None
    effort_group: str
    method: str
    recent_detections: int
    """Outings with live-source records (iNaturalist) of the taxon in the ~10 km cell."""
    recent_outings: int
    """Live-source outings recording the taxon's group in the cell during the window."""
    p_usual: float
    """Baseline (Level 0) chance per outing at this place and week."""
    p_now: float
    level: int
    odds_boost: float | None = None
    """Factor by which recent sightings change the odds (Level-2 models only)."""
    drivers: list[Driver] = Field(default_factory=list)


class RecentActivity(BaseModel):
    day: date
    cell: str
    resolution_km: float
    window_days: int
    data_through: date
    """Recent records are published with a delay (24 h for openly mapped species)."""
    picking_up: list[RecentItem] = Field(default_factory=list)
    """Species whose recent sightings raise today's chance, by a gated Level-2 model."""
    reported_recently: list[RecentItem] = Field(default_factory=list)
    """Openly mapped species reported nearby during the window, most reported first."""
    notes: list[str] = Field(default_factory=list)


class HourSlot(BaseModel):
    start: datetime
    """Local start of the hour (region time zone)."""
    p: float
    multiplier: float
    """Odds relative to a typical hour of the day (1 = typical)."""
    factors: dict[str, str] = Field(default_factory=dict)
    """The hour's level of each factor the model uses (e.g. diel phase, tide stage)."""


class HourlyForecast(BaseModel):
    taxon: TaxonSummary
    day: date
    timezone: str
    p_day: float
    """The daily forecast (per outing), which the hours redistribute."""
    level: int
    hours: list[HourSlot] = Field(default_factory=list)
    best: list[datetime] = Field(default_factory=list)
    """Starts of the three best hours."""
    factors: dict[str, dict[str, float]] = Field(default_factory=dict)
    """Per factor, each level's odds multiplier relative to its reference level."""
    notes: list[str] = Field(default_factory=list)


def _model(raw: str) -> OffsetLogit:
    return model_from_dict(json.loads(raw))


class ForecastService:
    def __init__(
        self,
        queries: BaselineQueries,
        station_coords: dict[str, tuple[float, float]],
        *,
        registry: DatasetRegistry | None = None,
        config: BaselineConfig | None = None,
        nowcast_days: int = 14,
    ) -> None:
        self.q = queries
        self.conn = queries._conn
        self.registry = registry
        self.config = config or BaselineConfig()
        self.nowcast_days = nowcast_days
        self.stations = station_coords
        self._models: dict[tuple[str, str], tuple[int, OffsetLogit]] = {}
        # A service reads one immutable store (the API builds a new service when a new bundle
        # is published), so signal lookups are loaded once per set of signals and reused.
        self._lookups: dict[tuple[str, ...], SignalLookup] = {}
        self._store_stations = None
        tables = {r[0] for r in self.conn.execute("SHOW TABLES").fetchall()}
        self._tables = tables
        if {"conditions_gates", "conditions_models"} <= tables:
            # Highest level whose gate passed, per taxon and effort group. A Level-2 model
            # already includes Level 1's terms when (and only when) Level 1 passed.
            passed = {
                (t, g, lv)
                for t, g, lv in self.conn.execute(
                    "SELECT taxon_id, group_id, level FROM conditions_gates "
                    "WHERE region_id = ? AND passes",
                    [queries.region.id],
                ).fetchall()
            }
            for t, g, lv, raw in self.conn.execute(
                "SELECT taxon_id, group_id, level, model FROM conditions_models "
                "WHERE region_id = ?",
                [queries.region.id],
            ).fetchall():
                ok = (t, g, lv) in passed
                if ok and lv > self._models.get((t, g), (0, None))[0]:
                    self._models[(t, g)] = (lv, _model(raw))
        self._hourly: dict[str, tuple[OffsetLogit, float]] = {}
        if "hourly_models" in tables:
            for t, raw, log_norm in self.conn.execute(
                "SELECT taxon_id, model, log_norm FROM hourly_models WHERE region_id = ? "
                "AND passes AND model IS NOT NULL",
                [queries.region.id],
            ).fetchall():
                self._hourly[t] = (_model(raw), log_norm)
        self._hilo: dict[str, list] = defaultdict(list)
        if "tide_hilo" in tables:
            for sid, t, kind, h in self.conn.execute(
                "SELECT station_id, t, kind, height_m FROM tide_hilo ORDER BY t"
            ).fetchall():
                self._hilo[sid].append((t.replace(tzinfo=UTC), kind, h))

    def _level0(self, taxon_id: str, group_id: str, lat: float, lon: float, on: date, tier):
        level0 = self.q._level_for(tier)
        for level in self.q._coarser(level0):
            cell = spatial.cell_for_point(lat, lon, self.q.level_res[level])
            est = self.q._estimate(
                level, taxon_ids=[taxon_id], groups=[group_id], cells=[cell], weeks=[week_of(on)]
            )
            if est:
                return est[0].p, cell, level, level != level0
        raise NotAvailable(taxon_id)

    def _lookup(self, signals: tuple[str, ...]) -> SignalLookup:
        if signals not in self._lookups:
            if self._store_stations is None:
                self._store_stations = stations_in_store(self.conn, self.stations)
            self._lookups[signals] = SignalLookup(
                self.conn, self._store_stations, list(signals), normals_before=None
            )
        return self._lookups[signals]

    def _signals(self, model: OffsetLogit, cell: str, on: date, notes: list[str]) -> dict:
        terms = [t for t in model.terms if not t.signal.startswith("nowcast.")]
        lookup = self._lookup(tuple(sorted({t.signal for t in terms})))
        values = {}
        for t in terms:
            value = lookup.value(cell, on, t.signal)
            for back in range(1, PERSIST_DAYS + 1):
                if math.isfinite(value):
                    break
                value = lookup.value(cell, on - timedelta(days=back), t.signal)
                if math.isfinite(value):
                    notes.append(f"{t.signal}: latest value from {on - timedelta(days=back)}")
            values[t.signal] = value
        return values

    def _nowcast(self, taxon_id: str, group_id: str, c1: str, on: date) -> tuple[float, float]:
        start = on - timedelta(days=self.nowcast_days)
        if "recent_effort" in self._tables:
            # Published bundles carry aggregates (no raw records), already delayed by policy.
            k = self.conn.execute(
                "SELECT coalesce(sum(k), 0) FROM recent_detections WHERE taxon_id = ? "
                "AND c1 = ? AND day >= ? AND day < ?",
                [taxon_id, c1, start, on],
            ).fetchone()[0]
            n = self.conn.execute(
                "SELECT coalesce(sum(n), 0) FROM recent_effort WHERE taxon_group = ? "
                "AND c1 = ? AND day >= ? AND day < ?",
                [split_egroup(group_id)[0], c1, start, on],
            ).fetchone()[0]
            return float(k), float(n)
        create_training_view(
            self.conn,
            self.config,
            self.q.region.bbox,
            self.registry,
            name="_fc",
            after=_dt(start),
            before=_dt(on),
        )
        k, n = self.conn.execute(
            """
            SELECT count(DISTINCT visit_key) FILTER (WHERE taxon_id = ? AND detected),
                   count(DISTINCT visit_key)
            FROM _fc WHERE live AND taxon_group = ? AND c1 = ?
            """,
            [taxon_id, split_egroup(group_id)[0], c1],
        ).fetchone()
        return float(k or 0), float(n or 0)

    def forecast(
        self, taxon_id: str, lat: float, lon: float, on: date, method: str | None = None
    ) -> Forecast:
        if not self.q.region.contains(lat, lon):
            raise ValueError("location is outside the region")
        taxon_id = self.q._canon(taxon_id)
        summary = self.q.taxon_summary(taxon_id, on)
        tier = PolicyTier(summary.tier)
        group_id = self.q._choose_group(taxon_id, method)
        p0, cell, level, fallback = self._level0(taxon_id, group_id, lat, lon, on, tier)
        out = Forecast(
            taxon=summary,
            day=on,
            cell=cell,
            resolution_km=spatial.edge_km(self.q.level_res[level]),
            effort_group=group_id,
            method=method_for(group_id),
            level=0,
            p=round(p0, 6),
            p_level0=round(p0, 6),
        )
        if fallback:
            out.notes.append("no baseline at this cell; a coarser area's estimate is shown")
        if tier != PolicyTier.OPEN:
            out.notes.append("daily conditions are shown only for openly mapped species")
            return out
        level_no, model = self._models.get((taxon_id, group_id), (0, None))
        if model is None:
            out.notes.append("no condition model has passed its backtest gate")
            return out
        notes: list[str] = []
        values = self._signals(model, cell, on, notes)
        if any(not math.isfinite(v) for v in values.values()):
            out.notes.append("condition signals unavailable here or for this date")
            return out
        if level_no == 2:
            c1 = spatial.cell_for_point(lat, lon, self.q.level_res["parent"])
            k, n = self._nowcast(taxon_id, group_id, c1, on)
            values["nowcast.log_detections"] = math.log1p(k)
            values["nowcast.log_effort"] = math.log1p(n)
        arrays = {s: np.array([v]) for s, v in values.items()}
        offset = np.log(np.array([p0]) / (1 - np.array([p0])))
        p = float(model.predict(arrays, offset)[0])
        contributions = model.contributions(arrays)
        out.level = level_no
        out.p = round(p, 6)
        out.drivers = sorted(
            (
                Driver(
                    term=t.name,
                    signal=t.signal,
                    value=round(values[t.signal], 4),
                    contribution=round(float(contributions[t.name][0]), 4),
                    hypothesis=t.hypothesis,
                )
                for t in model.terms
            ),
            key=lambda d: -abs(d.contribution),
        )
        out.notes += notes
        return out

    def forecast_map(
        self,
        taxon_id: str,
        on: date,
        cells: list[str] | None = None,
        method: str | None = None,
    ) -> MapForecast:
        """``forecast`` for many cells at once: the week's policy-filtered map (same cells,
        resolution and baseline values as ``/species/{id}/map``), with the day's condition
        model applied to every cell in one pass. ``cells`` limits it to those cells."""
        smap = self.q.species_map(taxon_id, on, method=method)
        taxon_id = smap.taxon.taxon_id
        group_id = smap.effort_group
        wanted = set(cells) if cells else None
        base = [(c.cell, c.p) for c in smap.cells if wanted is None or c.cell in wanted]
        out = MapForecast(
            taxon=smap.taxon,
            day=on,
            resolution_km=smap.resolution_km,
            effort_group=group_id,
            method=smap.method,
            level=0,
            cells=[CellForecast(cell=c, p=round(p, 6), p_level0=round(p, 6)) for c, p in base],
        )
        if wanted is not None and len(base) < len(wanted):
            out.notes.append(f"{len(wanted) - len(base)} requested cells are not on this map")
        if PolicyTier(smap.taxon.tier) != PolicyTier.OPEN:
            out.notes.append("daily conditions are shown only for openly mapped species")
            return out
        level_no, model = self._models.get((taxon_id, group_id), (0, None))
        if model is None:
            out.notes.append("no condition model has passed its backtest gate")
            return out
        if not base:
            return out
        notes: list[str] = []
        rows: list[dict] = []
        usable: list[int] = []
        nowcast: dict[str, tuple[float, float]] = {}
        for i, (cell, _p) in enumerate(base):
            values = self._signals(model, cell, on, notes)
            if any(not math.isfinite(v) for v in values.values()):
                continue
            if level_no == 2:
                c1 = spatial.coarsen_cell(cell, self.q.level_res["parent"])
                if c1 not in nowcast:
                    nowcast[c1] = self._nowcast(taxon_id, group_id, c1, on)
                k, n = nowcast[c1]
                values["nowcast.log_detections"] = math.log1p(k)
                values["nowcast.log_effort"] = math.log1p(n)
            rows.append(values)
            usable.append(i)
        if len(usable) < len(base):
            out.notes.append(
                f"condition signals unavailable for {len(base) - len(usable)} cells: "
                "their baseline is shown"
            )
        if not usable:
            return out
        arrays = {s: np.array([r[s] for r in rows]) for s in rows[0]}
        p0 = np.array([base[i][1] for i in usable])
        offset = np.log(p0 / (1 - p0))
        p = model.predict(arrays, offset)
        contributions = model.contributions(arrays)
        for j, i in enumerate(usable):
            cf = out.cells[i]
            cf.p = round(float(p[j]), 6)
            cf.drivers = sorted(
                (
                    Driver(
                        term=t.name,
                        signal=t.signal,
                        value=round(float(arrays[t.signal][j]), 4),
                        contribution=round(float(contributions[t.name][j]), 4),
                        hypothesis=t.hypothesis,
                    )
                    for t in model.terms
                ),
                key=lambda d: -abs(d.contribution),
            )
        out.level = level_no
        out.notes += sorted(set(notes))
        return out

    def hourly(
        self, taxon_id: str, lat: float, lon: float, on: date, method: str | None = None
    ) -> HourlyForecast:
        """The day's forecast spread over its local hours by the taxon's gated hourly model
        (conditions/hourly.py). Openly mapped taxa only: other tiers aren't shown by hour."""
        from zoneinfo import ZoneInfo

        from wildlife_radar.conditions.hourly import multiplier
        from wildlife_radar.conditions.timed import HourSignals
        from wildlife_radar.core.spatial import haversine_km

        day = self.forecast(taxon_id, lat, lon, on, method)
        tz_name = self.q.region.timezone or "UTC"
        tz = ZoneInfo(tz_name)
        out = HourlyForecast(
            taxon=day.taxon,
            day=on,
            timezone=tz_name,
            p_day=day.p,
            level=day.level,
            notes=list(day.notes),
        )
        if PolicyTier(day.taxon.tier) != PolicyTier.OPEN:
            out.notes.append("hourly detail is shown only for openly mapped species")
            return out
        start = datetime(on.year, on.month, on.day, tzinfo=tz)
        hours_local = []
        t = start
        while t.date() == on:
            hours_local.append(t)
            t = (t.astimezone(UTC) + timedelta(hours=1)).astimezone(tz)
        entry = self._hourly.get(day.taxon.taxon_id)
        if entry is None:
            out.notes.append("no hourly pattern has passed its backtest gate for this species")
            out.hours = [HourSlot(start=h, p=day.p, multiplier=1.0) for h in hours_local]
            return out
        model, log_norm = entry
        # Tides at the nearest station within reach (the factors were fitted the same way).
        hilo: list = []
        best = None
        for sid, (slat, slon) in self.stations.items():
            d = haversine_km(lat, lon, slat, slon)
            if sid in self._hilo and d <= TIDE_REACH_KM and (best is None or d < best[0]):
                best = (d, sid)
        if best:
            hilo = self._hilo[best[1]]
        signals = HourSignals(lat, lon, hilo)
        utc_hours = [h.astimezone(UTC) for h in hours_local]
        values = {
            term.signal: [signals.value(term.signal, h, []) for h in utc_hours]
            for term in model.terms
        }
        known = [all(values[s][i] is not None for s in values) for i in range(len(utc_hours))]
        arrays = {
            s: np.array([v if v is not None else 0.0 for v in vs]) for s, vs in values.items()
        }
        mult = multiplier(model, log_norm, arrays)
        if not all(known):
            out.notes.append("some hours lack a factor (e.g. no tide station nearby): shown flat")
        base = math.log(max(day.p, 1e-9) / max(1 - day.p, 1e-9))
        for i, h in enumerate(hours_local):
            m = float(mult[i]) if known[i] else 1.0
            p = 1 / (1 + math.exp(-(base + math.log(m))))
            levels = {}
            for term in model.terms:
                v = values[term.signal][i]
                if term.shape == "categorical" and v is not None:
                    levels[term.name] = term.categories[int(v)]
                elif v is not None:
                    levels[term.name] = f"{v:.2f}"
            out.hours.append(
                HourSlot(start=h, p=round(p, 6), multiplier=round(m, 3), factors=levels)
            )
        out.best = [h.start for h in sorted(out.hours, key=lambda x: -x.p)[:3]]
        out.factors = {
            term.name: {
                c: round(math.exp(e), 3) for c, e in model.category_effects(term.name).items()
            }
            for term in model.terms
            if term.shape == "categorical"
        }
        out.notes.append(
            "hours redistribute the daily chance: averaged over when people usually go out, "
            "they equal it"
        )
        return out


def _recent_rows(service: ForecastService, c1: str, start: date, end: date) -> list[tuple]:
    """``(taxon, group, detections, outings)`` in parent cell ``c1`` for days in [start, end)."""
    conn = service.conn
    tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    if "recent_detections" not in tables:
        return []
    return conn.execute(
        """
        WITH d AS (
            SELECT taxon_id, taxon_group, sum(k) AS k FROM recent_detections
            WHERE c1 = ? AND day >= ? AND day < ? GROUP BY ALL
        ),
        e AS (
            SELECT taxon_group, sum(n) AS n FROM recent_effort
            WHERE c1 = ? AND day >= ? AND day < ? GROUP BY ALL
        )
        SELECT d.taxon_id, d.taxon_group, d.k, coalesce(e.n, d.k)
        FROM d LEFT JOIN e USING (taxon_group)
        ORDER BY d.k DESC
        """,
        [c1, start, end, c1, start, end],
    ).fetchall()


def recent_activity(
    service: ForecastService,
    lat: float,
    lon: float,
    on: date,
    *,
    limit: int = 20,
    min_boost: float = 1.25,
) -> RecentActivity:
    """What's being reported near a place, and which species that makes more likely today."""
    from wildlife_radar.policy.tiers import rule_for

    q = service.q
    if not q.region.contains(lat, lon):
        raise ValueError("location is outside the region")
    c1 = spatial.cell_for_point(lat, lon, q.level_res["parent"])
    start = on - timedelta(days=service.nowcast_days)
    delay = rule_for(PolicyTier.OPEN).min_delay
    out = RecentActivity(
        day=on,
        cell=c1,
        resolution_km=spatial.edge_km(q.level_res["parent"]),
        window_days=service.nowcast_days,
        data_through=on - timedelta(days=max(1, delay.days)),
    )
    rows = _recent_rows(service, c1, start, on)
    if not rows:
        out.notes.append("no recent records published for this area")
        return out
    for taxon_id, _taxon_group, k, n in rows:
        # Only openly mapped taxa, re-checked for this date (profiles can raise tiers seasonally).
        if q.tiers.get(taxon_id, on) != PolicyTier.OPEN:
            continue
        try:
            # The taxon's best-sampled effort group (e.g. checklists for birds); its Level-2
            # model reads the live-source recent counts.
            fc = service.forecast(taxon_id, lat, lon, on)
        except (NotAvailable, ValueError):
            continue
        group_id = fc.effort_group
        boost = None
        if fc.level >= 2:
            nowcast = sum(d.contribution for d in fc.drivers if d.signal.startswith("nowcast."))
            boost = round(math.exp(nowcast), 3)
        item = RecentItem(
            taxon_id=taxon_id,
            scientific_name=fc.taxon.scientific_name,
            common_name=fc.taxon.common_name,
            effort_group=group_id,
            method=fc.method,
            recent_detections=int(k),
            recent_outings=int(n),
            p_usual=fc.p_level0,
            p_now=fc.p,
            level=fc.level,
            odds_boost=boost,
            drivers=fc.drivers,
        )
        out.reported_recently.append(item)
        if boost is not None and boost >= min_boost:
            out.picking_up.append(item)
    out.picking_up.sort(key=lambda i: -(i.p_now * math.log(i.odds_boost or 1)))
    out.picking_up = out.picking_up[:limit]
    out.reported_recently = out.reported_recently[:limit]
    return out


def _dt(d: date):
    from datetime import UTC, datetime

    return datetime(d.year, d.month, d.day, tzinfo=UTC)
