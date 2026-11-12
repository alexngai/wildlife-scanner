"""Time-of-day and tide-stage indices from timed records (iNaturalist hourly counts).

The GBIF snapshot has dates only, so intra-day hypotheses (a fish that bites an hour after
sunset, shorebirds that gather on the rising tide) can't be fitted from it. iNaturalist keeps
observation times; its histogram endpoint gives counts per UTC hour without downloading
records (connectors/inat_histogram.py).

For a taxon and an intra-day signal with categories ``c`` (diel phase, hours after sunset,
tide stage, tide height band), the **index** is::

    index(c) = (taxon records in c / all taxon records) / (group records in c / all group records)

where the group (e.g. all fishes) stands in for observing effort: when people are out looking
and recording that kind of animal. ``index > 1`` means the taxon is recorded relatively more
often in ``c`` than its group. A 90% interval comes from resampling days (block bootstrap).

Caveat: this mixes activity with detectability and observer behavior (e.g. night dives are
rarer but target different species). It is an *availability prior*, not a behavioral claim.

Signals are computed per hour (at its midpoint) from:

- the sun, per local day (Astronomy Engine): diel phase and hours since sunset;
- tide high/low predictions at the region's primary station (NOAA CO-OPS): stage, and a
  cosine-interpolated height between consecutive extremes.
"""

from __future__ import annotations

import bisect
import json
import math
import random
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import duckdb

from wildlife_radar.connectors.astronomy import daily_events

TIMED_SCHEMA = """
CREATE TABLE IF NOT EXISTS timed_index (
    region_id VARCHAR, taxon_id VARCHAR, signal VARCHAR, category VARCHAR,
    n_taxon BIGINT, n_effort BIGINT, idx DOUBLE, ci_lo DOUBLE, ci_hi DOUBLE,
    evaluated_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS timed_scorecard (
    region_id VARCHAR, taxon_id VARCHAR, term VARCHAR, signal VARCHAR, expected VARCHAR,
    peak VARCHAR, verdict VARCHAR, review VARCHAR, n_taxon BIGINT, evaluated_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tide_hilo (
    station_id VARCHAR, t TIMESTAMP, kind VARCHAR, height_m DOUBLE,
    PRIMARY KEY (station_id, t)
);
"""

DIEL = ("night", "dawn", "day", "dusk")
TIDE_STAGE = ("low", "rising", "high", "falling")
SUNSET_BINS = ((0, 1), (1, 2), (2, 4), (4, 24))
HEIGHT_BANDS = 5

#: Intra-day signals this module computes (profile signal id → categories, in order).
TIMED_SIGNALS: dict[str, tuple[str, ...]] = {
    "astro.diel_phase": DIEL,
    "astro.sun_altitude_deg": DIEL,  # profiles state diel activity as sun altitude
    "astro.hours_since_sunset": (*(f"{a}-{b}h" for a, b in SUNSET_BINS), "daylight"),
    "tide.stage": TIDE_STAGE,
    "tide.height_m": tuple(f"q{i + 1}" for i in range(HEIGHT_BANDS)),
}

#: Diel phase a trait value predicts as the peak.
ACTIVITY_PEAK = {"diurnal": ("day",), "nocturnal": ("night",), "crepuscular": ("dawn", "dusk")}


@dataclass
class HourSignals:
    """Intra-day signal values for UTC hours at one place (cached per local day)."""

    lat: float
    lon: float
    hilo: list[tuple[datetime, str, float]] = field(default_factory=list)
    """Tide extremes ``(time, "H" | "L", height)``, sorted by time."""
    _days: dict[date, tuple] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.hilo.sort()
        self._times = [t for t, _, _ in self.hilo]
        self.offset = round(self.lon / 15)

    def _sun(self, day: date):
        if day not in self._days:
            ev = daily_events(self.lat, self.lon, day, self.offset)
            self._days[day] = (ev.civil_dawn, ev.sunrise, ev.sunset, ev.civil_dusk)
        return self._days[day]

    def diel(self, t: datetime) -> str | None:
        local = (t + timedelta(hours=self.offset)).date()
        dawn, rise, set_, dusk = self._sun(local)
        if None in (dawn, rise, set_, dusk):
            return None
        if dawn <= t < rise + timedelta(hours=1):
            return "dawn"
        if set_ - timedelta(hours=1) <= t < dusk:
            return "dusk"
        if rise + timedelta(hours=1) <= t < set_ - timedelta(hours=1):
            return "day"
        return "night"

    def hours_since_sunset(self, t: datetime) -> float | None:
        local = (t + timedelta(hours=self.offset)).date()
        for day in (local, local - timedelta(days=1)):
            _, rise, set_, _ = self._sun(day)
            if set_ is not None and set_ <= t:
                next_rise = self._sun(day + timedelta(days=1))[1]
                if next_rise is not None and t >= next_rise:
                    return None  # daylight
                return (t - set_).total_seconds() / 3600
        return None

    def _bracket(self, t: datetime):
        i = bisect.bisect_right(self._times, t)
        if i == 0 or i >= len(self.hilo):
            return None
        return self.hilo[i - 1], self.hilo[i]

    def tide(self, t: datetime) -> tuple[str, float] | None:
        """``(stage, height_m)``: within an hour of an extreme it is "high"/"low"."""
        pair = self._bracket(t)
        if pair is None:
            return None
        (t1, k1, h1), (t2, _k2, h2) = pair
        span = (t2 - t1).total_seconds()
        if span <= 0 or span > 10 * 3600:
            return None  # gap in predictions
        x = (t - t1).total_seconds() / span
        height = (h1 + h2) / 2 + (h1 - h2) / 2 * math.cos(math.pi * x)
        if (t - t1) <= timedelta(hours=1):
            stage = "high" if k1 == "H" else "low"
        elif (t2 - t) <= timedelta(hours=1):
            stage = "low" if k1 == "H" else "high"
        else:
            stage = "falling" if k1 == "H" else "rising"
        return stage, height

    def category(self, signal: str, t: datetime, height_edges: list[float]) -> str | None:
        mid = t + timedelta(minutes=30)
        if signal in ("astro.diel_phase", "astro.sun_altitude_deg"):
            return self.diel(mid)
        if signal == "astro.hours_since_sunset":
            h = self.hours_since_sunset(mid)
            if h is None:
                return "daylight"
            for a, b in SUNSET_BINS:
                if a <= h < b:
                    return f"{a}-{b}h"
            return None
        tide = self.tide(mid)
        if tide is None:
            return None
        if signal == "tide.stage":
            return tide[0]
        if signal == "tide.height_m":
            return f"q{bisect.bisect_right(height_edges, tide[1]) + 1}"
        raise KeyError(signal)

    def height_edges(self) -> list[float]:
        """Band edges for tide height: quantiles of the cosine-interpolated hourly heights."""
        if len(self.hilo) < 2:
            return []
        start, end = self.hilo[0][0], self.hilo[-1][0]
        heights, t = [], start
        while t < end:
            tide = self.tide(t)
            if tide:
                heights.append(tide[1])
            t += timedelta(hours=1)
        heights.sort()
        if not heights:
            return []
        return [heights[len(heights) * i // HEIGHT_BANDS] for i in range(1, HEIGHT_BANDS)]


@dataclass
class CategoryIndex:
    category: str
    n_taxon: int
    n_effort: int
    index: float | None
    ci: tuple[float, float] | None


def category_index(
    taxon: dict[datetime, int],
    effort: dict[datetime, int],
    categorize: Callable[[datetime], str | None],
    categories: tuple[str, ...],
    offset_hours: int,
    reps: int = 200,
    seed: int = 7,
) -> list[CategoryIndex]:
    """Index per category with a day-block bootstrap interval (see module docstring)."""
    # Per local day: counts per category, for taxon and effort.
    per_day: dict[date, list[list[int]]] = defaultdict(
        lambda: [[0] * len(categories), [0] * len(categories)]
    )
    pos = {c: i for i, c in enumerate(categories)}
    cache: dict[datetime, str | None] = {}
    for which, counts in ((0, taxon), (1, effort)):
        for t, n in counts.items():
            if t not in cache:
                cache[t] = categorize(t)
            c = cache[t]
            if c in pos:
                per_day[(t + timedelta(hours=offset_hours)).date()][which][pos[c]] += n
    days = list(per_day.values())

    def indices(sample) -> list[float | None]:
        tx = [sum(d[0][i] for d in sample) for i in range(len(categories))]
        ef = [sum(d[1][i] for d in sample) for i in range(len(categories))]
        st, se = sum(tx), sum(ef)
        out = []
        for a, b in zip(tx, ef, strict=True):
            out.append((a / st) / (b / se) if st and se and b else None)
        return out

    point = indices(days)
    rng = random.Random(seed)
    boots: list[list[float]] = [[] for _ in categories]
    if days:
        for _ in range(reps):
            sample = [days[rng.randrange(len(days))] for _ in days]
            for i, v in enumerate(indices(sample)):
                if v is not None:
                    boots[i].append(v)
    out = []
    for i, c in enumerate(categories):
        b = sorted(boots[i])
        ci = (b[int(0.05 * (len(b) - 1))], b[int(0.95 * (len(b) - 1))]) if len(b) >= 20 else None
        out.append(
            CategoryIndex(
                category=c,
                n_taxon=sum(d[0][i] for d in days),
                n_effort=sum(d[1][i] for d in days),
                index=point[i],
                ci=ci,
            )
        )
    return out


@dataclass
class TimedVerdict:
    term: str
    signal: str
    expected: str | None
    peak: str | None
    verdict: str
    review: str | None


def judge(term: str, spec, signal: str, rows: list[CategoryIndex], trait=None) -> TimedVerdict:
    """Compare a profile's intra-day claim with the indices.

    - ``supported``: some category differs from the group (interval excludes 1) and, if the
      profile names a peak (``at`` for hours after sunset, or a diel trait), the highest
      index is there;
    - ``contradicted``: a clear pattern, but it peaks elsewhere (flagged for review);
    - ``inconclusive``: no category differs from the group.
    """
    sig = [r for r in rows if r.ci is not None and (r.ci[0] > 1 or r.ci[1] < 1)]
    ranked = [r for r in rows if r.index is not None and r.ci is not None]
    peak = max(ranked, key=lambda r: r.index).category if ranked else None
    expected: tuple[str, ...] | None = None
    params = getattr(spec, "params", {}) or {}
    if signal == "astro.hours_since_sunset" and "at" in params:
        at = float(params["at"])
        expected = tuple(f"{a}-{b}h" for a, b in SUNSET_BINS if a - 1 <= at < b + 1)
    elif signal in ("astro.sun_altitude_deg", "astro.diel_phase") and trait in ACTIVITY_PEAK:
        expected = ACTIVITY_PEAK[trait]
    if not sig:
        verdict, review = "inconclusive", None
    elif expected is None or peak in expected:
        verdict, review = "supported", None
    else:
        verdict = "contradicted"
        review = f"records peak at {peak}, not {'/'.join(expected)} as the profile states"
    return TimedVerdict(
        term=term,
        signal=signal,
        expected="/".join(expected) if expected else None,
        peak=peak,
        verdict=verdict,
        review=review,
    )


def store_hilo(conn: duckdb.DuckDBPyConnection, station_id: str, rows) -> None:
    conn.execute(TIMED_SCHEMA)
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO tide_hilo VALUES (?, ?, ?, ?)",
            [(station_id, t.replace(tzinfo=None), k, h) for t, k, h in rows],
        )


def load_hilo(conn: duckdb.DuckDBPyConnection, station_id: str) -> list[tuple]:
    conn.execute(TIMED_SCHEMA)
    return [
        (t.replace(tzinfo=UTC), k, h)
        for t, k, h in conn.execute(
            "SELECT t, kind, height_m FROM tide_hilo WHERE station_id = ? ORDER BY t",
            [station_id],
        ).fetchall()
    ]


def persist(
    conn: duckdb.DuckDBPyConnection,
    region_id: str,
    taxon_id: str,
    indices: dict[str, list[CategoryIndex]],
    verdicts: list[TimedVerdict],
    n_taxon: int,
    now: datetime,
) -> None:
    conn.execute(TIMED_SCHEMA)
    now_n = now.replace(tzinfo=None)
    for table in ("timed_index", "timed_scorecard"):
        conn.execute(
            f"DELETE FROM {table} WHERE region_id = ? AND taxon_id = ?", [region_id, taxon_id]
        )
    rows = [
        (
            region_id,
            taxon_id,
            signal,
            r.category,
            r.n_taxon,
            r.n_effort,
            r.index,
            r.ci[0] if r.ci else None,
            r.ci[1] if r.ci else None,
            now_n,
        )
        for signal, rs in indices.items()
        for r in rs
    ]
    if rows:
        conn.executemany("INSERT INTO timed_index VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    if verdicts:
        conn.executemany(
            "INSERT INTO timed_scorecard VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    region_id,
                    taxon_id,
                    v.term,
                    v.signal,
                    v.expected,
                    v.peak,
                    v.verdict,
                    v.review,
                    n_taxon,
                    now_n,
                )
                for v in verdicts
            ],
        )


def summary(rows: list[CategoryIndex]) -> str:
    return json.dumps({r.category: None if r.index is None else round(r.index, 2) for r in rows})
