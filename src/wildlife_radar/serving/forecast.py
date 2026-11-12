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
from datetime import date, timedelta

import numpy as np
from pydantic import BaseModel, Field

from wildlife_radar.baseline.builder import BaselineConfig, create_training_view
from wildlife_radar.baseline.effort import DatasetRegistry, method_for
from wildlife_radar.conditions.levels import SignalLookup, stations_in_store
from wildlife_radar.conditions.model import OffsetLogit, TermSpec
from wildlife_radar.core import spatial
from wildlife_radar.policy.tiers import PolicyTier
from wildlife_radar.serving.queries import BaselineQueries, NotAvailable, TaxonSummary
from wildlife_radar.storage.observations import week_of

PERSIST_DAYS = 7


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


def _model(raw: str) -> OffsetLogit:
    d = json.loads(raw)
    model = OffsetLogit([TermSpec(**t) for t in d["terms"]])
    model.coef = np.array(d["coef"])
    model.intercept = d["intercept"]
    model.means = np.array(d["means"])
    model.sds = np.array(d["sds"])
    model.converged = d["converged"]
    return model


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
        tables = {r[0] for r in self.conn.execute("SHOW TABLES").fetchall()}
        if {"conditions_gates", "conditions_models"} <= tables:
            # Highest level whose gate passed, per taxon and effort group. Level 2 builds on
            # Level 1, so it is used only if Level 1 passed too.
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
                ok = (t, g, lv) in passed and (lv == 1 or (t, g, 1) in passed)
                if ok and lv > self._models.get((t, g), (0, None))[0]:
                    self._models[(t, g)] = (lv, _model(raw))

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

    def _signals(self, model: OffsetLogit, cell: str, on: date, notes: list[str]) -> dict:
        terms = [t for t in model.terms if not t.signal.startswith("nowcast.")]
        lookup = SignalLookup(
            self.conn,
            stations_in_store(self.conn, self.stations),
            sorted({t.signal for t in terms}),
            normals_before=None,
        )
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
            FROM _fc WHERE egroup = ? AND c1 = ?
            """,
            [taxon_id, group_id, c1],
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


def _dt(d: date):
    from datetime import UTC, datetime

    return datetime(d.year, d.month, d.day, tzinfo=UTC)
