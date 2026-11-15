"""Priors computed from occurrence data (framework.md §4.3 step 4).

- **Seasonality** from the Level-0 baseline: the region-wide weekly detection rate per unit of
  effort, so a species seen in summer only because observers go out in summer isn't called
  "summer-only".
- **Diel pattern** from records with precise times: the share of records at night, in twilight
  and by day, relative to the same group's records. Observers are mostly out by day, so this is
  flagged as observer-biased and used only for sanity checks against trait values.

These are measurements of the data the platform uses; they carry its licenses.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import duckdb

from wildlife_scanner.baseline.builder import LEVEL_REGION
from wildlife_scanner.baseline.effort import SURVEY_CLASSES
from wildlife_scanner.profilegen.candidates import Candidate, Rank
from wildlife_scanner.profiles.schema import Provenance

PRECISE = ("instant", "minute")


def _licenses(conn: duckdb.DuckDBPyConnection, region_id: str, group_id: str) -> str:
    rows = conn.execute(
        "SELECT license_id FROM prior_licenses WHERE region_id = ? AND group_id = ? "
        "GROUP BY 1 ORDER BY sum(n) DESC",
        [region_id, group_id],
    ).fetchall()
    return ", ".join(r[0] for r in rows if r[0]) or "unknown"


def weekly_rates(
    conn: duckdb.DuckDBPyConnection, region_id: str, taxon_id: str, group_id: str
) -> dict[int, float]:
    rows = conn.execute(
        f"""
        SELECT e.week, coalesce(h.k, 0) / e.n FROM prior_effort e
        LEFT JOIN prior_hits h ON h.region_id = e.region_id AND h.level = e.level
            AND h.group_id = e.group_id AND h.cell IS NOT DISTINCT FROM e.cell
            AND h.week = e.week AND h.taxon_id = ?
        WHERE e.region_id = ? AND e.level = {LEVEL_REGION} AND e.group_id = ?
          AND (e.taxon_id IS NULL OR e.taxon_id = ?) AND e.n > 0
        """,
        [taxon_id, region_id, group_id, taxon_id],
    ).fetchall()
    return {int(w): float(r) for w, r in rows}


def seasonality(rates: dict[int, float]) -> dict | None:
    """Summarize 52 weekly rates: pattern, peak weeks and amplitude (max / mean)."""
    if len(rates) < 26:
        return None
    values = [rates.get(w, 0.0) for w in range(1, 53)]
    mean = sum(values) / 52
    if mean <= 0:
        return None
    top = max(values)
    amplitude = top / mean
    trough = min(values) / mean
    if amplitude < 1.5:
        pattern = "year_round"
    elif trough < 0.1:
        pattern = "seasonal_visitor"
    else:
        pattern = "seasonal_peak"
    peaks = [w for w, v in zip(range(1, 53), values, strict=True) if v >= 0.75 * top]
    return {
        "pattern": pattern,
        "peak_weeks": peaks if pattern != "year_round" else [],
        "amplitude": round(amplitude, 2),
    }


def seasonality_candidates(
    conn: duckdb.DuckDBPyConnection, region_id: str, taxon_ids: str | list[str]
) -> list[Candidate]:
    """Seasonality in the taxon's best-sampled shared-effort group (surveys have no season).

    ``taxon_ids`` may list aliases of one concept; the best-sampled one is used.
    """
    ids = [taxon_ids] if isinstance(taxon_ids, str) else list(taxon_ids)
    surveys = ", ".join(f"'{c}'" for c in SURVEY_CLASSES)
    row = conn.execute(
        f"""
        SELECT taxon_id, group_id, n_visits FROM prior_taxa
        WHERE region_id = ? AND taxon_id IN (SELECT unnest(?)) AND effort_class NOT IN ({surveys})
        ORDER BY n_visits DESC LIMIT 1
        """,
        [region_id, ids],
    ).fetchone()
    if row is None:
        return []
    taxon_id, group_id, n = row
    summary = seasonality(weekly_rates(conn, region_id, taxon_id, group_id))
    if summary is None:
        return []
    built = conn.execute(
        "SELECT built_at FROM prior_builds WHERE region_id = ?", [region_id]
    ).fetchone()
    return [
        Candidate(
            field="traits.observed_seasonality",
            value={**summary, "region": region_id, "effort_group": group_id, "detections": n},
            rank=Rank.COMPUTED,
            provenance=Provenance(
                source=f"baseline:{region_id}",
                method="computed",
                confidence=round(min(0.9, 0.3 + 0.1 * math.log10(max(n, 1))), 2),
                license=_licenses(conn, region_id, group_id),
                evidence=(
                    f"Level-0 baseline built {built[0]:%Y-%m-%d} as {taxon_id}"
                    if built
                    else f"Level-0 baseline as {taxon_id}"
                ),
            ),
        )
    ]


def solar_elevation(lat: float, lon: float, when: datetime) -> float:
    """Approximate solar elevation in degrees (NOAA equations; ~0.5° accuracy)."""
    when = when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)
    day = when.timetuple().tm_yday
    hours = when.hour + when.minute / 60 + when.second / 3600
    g = 2 * math.pi / 365 * (day - 1 + (hours - 12) / 24)
    decl = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )
    solar_minutes = hours * 60 + eqtime + 4 * lon
    hour_angle = math.radians(solar_minutes / 4 - 180)
    phi = math.radians(lat)
    cos_zenith = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(
        hour_angle
    )
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cos_zenith))))


def light_period(elevation: float) -> str:
    if elevation < -6:
        return "night"
    if elevation < 6:
        return "twilight"
    return "day"


def diel_shares(rows: list[tuple[float, float, datetime]]) -> dict[str, float]:
    counts = {"night": 0, "twilight": 0, "day": 0}
    for lat, lon, when in rows:
        counts[light_period(solar_elevation(lat, lon, when))] += 1
    total = sum(counts.values()) or 1
    return {k: v / total for k, v in counts.items()}


def diel_candidates(
    conn: duckdb.DuckDBPyConnection,
    taxon_ids: str | list[str],
    bbox: tuple[float, float, float, float] | None = None,
    *,
    min_records: int = 30,
    sample: int = 5000,
) -> list[Candidate]:
    lon_min, lat_min, lon_max, lat_max = bbox or (-180, -90, 180, 90)
    where = (
        f"time_precision IN {PRECISE} AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? "
        "AND outcome IN ('detected', 'presence_only')"
    )
    params = [lat_min, lat_max, lon_min, lon_max]
    ids = [taxon_ids] if isinstance(taxon_ids, str) else list(taxon_ids)
    group = conn.execute(
        "SELECT mode(group_id) FROM observations WHERE taxon_id IN (SELECT unnest(?))", [ids]
    ).fetchone()[0]
    if group is None:
        return []

    def fetch(extra: str, extra_params: list) -> list[tuple[float, float, datetime]]:
        return conn.execute(
            f"SELECT lat, lon, time_start FROM observations WHERE {where} AND {extra} "
            f"USING SAMPLE {sample} ROWS",
            params + extra_params,
        ).fetchall()

    own = fetch("taxon_id IN (SELECT unnest(?))", [ids])
    if len(own) < min_records:
        return []
    background = fetch("group_id = ?", [group])
    s, b = diel_shares(own), diel_shares(background)
    ratio = {k: round(s[k] / b[k], 2) if b[k] > 0 else None for k in s}
    if s["night"] >= 0.25 and (ratio["night"] or 0) >= 2:
        pattern = "nocturnal"
    elif s["twilight"] >= 0.15 and (ratio["twilight"] or 0) >= 1.5:
        pattern = "crepuscular"
    elif s["day"] >= 0.8 and (ratio["night"] or 0) <= 1:
        pattern = "diurnal"
    else:
        pattern = "cathemeral"
    return [
        Candidate(
            field="traits.observed_diel",
            value={
                "pattern": pattern,
                "shares": {k: round(v, 3) for k, v in s.items()},
                "ratio_to_group": ratio,
                "records": len(own),
                "observer_biased": True,
            },
            rank=Rank.COMPUTED,
            provenance=Provenance(
                source="observations",
                method="computed",
                confidence=0.4,
                evidence=f"{len(own)} timed records vs {len(background)} {group} records",
            ),
        )
    ]
