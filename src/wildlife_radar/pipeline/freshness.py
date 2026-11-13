"""How fresh each source is, per region (docs/design/ingestion.md §3).

Computed at publish time and shipped in the bundle (``freshness`` table); ``/health`` compares
each source's age with its target when asked, so a stale source shows up even if publishing
has stopped.

| source | measured by | target |
|---|---|---|
| ``inaturalist`` | last completed ``live`` run | 1 h |
| ``gbif-live`` | last GBIF pull of registry-live datasets (``live`` run) | 1 day |
| ``gbif-snapshot`` | snapshot date of the last ingest | 45 days |
| ``noaa`` | newest daily signal value | 2 days |
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

TARGETS: dict[str, timedelta] = {
    "inaturalist": timedelta(hours=1),
    "gbif-live": timedelta(days=1),
    "gbif-snapshot": timedelta(days=45),
    "noaa": timedelta(days=2),
}

FRESHNESS_SCHEMA = """
CREATE TABLE IF NOT EXISTS freshness (
    source VARCHAR, last_update TIMESTAMP, newest_record DATE, records BIGINT, detail VARCHAR
)
"""


def _manifest(lake: Path, region_id: str, job: str) -> dict | None:
    from wildlife_radar.pipeline.runner import latest

    m = latest(lake, region_id, job)
    return m if m and m.get("status") == "complete" else None


def collect(
    conn: duckdb.DuckDBPyConnection,
    region,
    lake: Path,
    live_keys: list[str],
) -> list[tuple]:
    """``(source, last_update, newest_record, records, detail)`` rows for the bundle."""
    rows: list[tuple] = []
    tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    live = _manifest(lake, region.id, "live")
    live_at = datetime.fromisoformat(live["finished_at"]) if live else None
    lon_min, lat_min, lon_max, lat_max = region.bbox
    if "observations" in tables:
        box = "lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
        params = [lat_min, lat_max, lon_min, lon_max]
        n, newest = conn.execute(
            f"SELECT count(*), max(local_date) FROM observations WHERE source_id = 'inaturalist' "
            f"AND {box}",
            params,
        ).fetchone()
        rows.append(("inaturalist", live_at, newest, n, "iNaturalist API, updated_since"))
        if live_keys:
            n, newest = conn.execute(
                f"SELECT count(*), max(local_date) FROM observations WHERE source_id = 'gbif' "
                f"AND dataset_key IN (SELECT unnest(?)) AND {box}",
                [live_keys, *params],
            ).fetchone()
            gbif_at = None
            if live and (live.get("outputs") or {}).get("gbif_cursor"):
                gbif_at = datetime.fromisoformat(live["outputs"]["gbif_cursor"])
            rows.append(("gbif-live", gbif_at, newest, n, f"{len(live_keys)} live datasets"))
    snap = _manifest(lake, region.id, "snapshot")
    if snap:
        d = (snap.get("outputs") or {}).get("snapshot_date")
        at = datetime.combine(date.fromisoformat(d), datetime.min.time(), UTC) if d else None
        rows.append(("gbif-snapshot", at, None, (snap["outputs"] or {}).get("observations"), d))
    if "signal_daily" in tables:
        stations = [s.station_id for s in region.tide_stations]
        newest = conn.execute(
            "SELECT max(day) FROM signal_daily WHERE station_id IN (SELECT unnest(?))", [stations]
        ).fetchone()[0]
        at = datetime.combine(newest, datetime.min.time(), UTC) if newest else None
        rows.append(("noaa", at, newest, None, ", ".join(stations)))
    return [(s, a.replace(tzinfo=None) if a else None, n, r, d) for s, a, n, r, d in rows]


def report(rows: list[tuple], now: datetime) -> list[dict]:
    """Rows with each source's age and whether it meets its target (for ``/health``)."""
    out = []
    for source, last, newest, records, detail in rows:
        target = TARGETS.get(source)
        age = (now - last.replace(tzinfo=UTC)) if last else None
        out.append(
            {
                "source": source,
                "last_update": last.replace(tzinfo=UTC).isoformat() if last else None,
                "newest_record": newest.isoformat() if newest else None,
                "records": records,
                "detail": detail,
                "age_hours": round(age.total_seconds() / 3600, 1) if age else None,
                "target_hours": target.total_seconds() / 3600 if target else None,
                "status": (
                    "unknown"
                    if age is None or target is None
                    else "ok"
                    if age <= target
                    else "stale"
                ),
            }
        )
    return out
