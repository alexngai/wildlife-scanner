"""One live stream per coverage area (docs/design/ingestion.md §2–3).

Recent records are pulled once for the whole coverage area (e.g. California), not once per
region, and kept as an append-only log of immutable Parquet parts::

    lake/norm/observations/source=live/coverage=<id>/day=<YYYY-MM-DD>/part-<stamp>.parquet
    …/coverage=<id>/_cursor.json            cursors of the iNaturalist and GBIF pulls
    …/coverage=<id>/deleted/part-*.parquet  record keys found deleted at the source

Parts hold rows in the store's own ``observations`` schema. A region loads the parts it
hasn't seen yet (its own cursor), filtered to its box, and applies the deletions.

**Deletions.** iNaturalist's deletions feed lists only the signed-in user's own
observations, so the log is checked instead: recent iNaturalist observations are requested
again by id (200 per request); ids that no longer come back were deleted (or made private)
and are listed in ``deleted/``. Records past the live window are covered by the monthly
snapshot (pipeline/coverage.py).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from wildlife_scanner.core.time import utcnow
from wildlife_scanner.regions import Region

WINDOW_DAYS = 60
MAX_RECORDS = 50_000
CURSOR = "_cursor.json"


def log_dir(lake: Path, coverage_id: str) -> Path:
    return lake / "norm" / "observations" / "source=live" / f"coverage={coverage_id}"


def read_cursor(lake: Path, coverage_id: str) -> dict:
    path = log_dir(lake, coverage_id) / CURSOR
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_cursor(lake: Path, coverage_id: str, cursor: dict) -> None:
    path = log_dir(lake, coverage_id) / CURSOR
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(cursor, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _write_part(lake: Path, coverage_id: str, observations, now: datetime, tag: str) -> int:
    """Rows in the store's schema, as one immutable part; returns the row count."""
    from wildlife_scanner.storage import ObservationStore

    with ObservationStore() as mem:
        n = mem.add(observations)
        if not n:
            return 0
        folder = log_dir(lake, coverage_id) / f"day={now.date().isoformat()}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"part-{now.strftime('%Y%m%dT%H%M%S%f')}-{tag}.parquet"
        tmp = folder / f".{path.name}.tmp"
        mem.conn.execute(
            f"COPY observations TO '{tmp.as_posix()}' (FORMAT parquet, COMPRESSION zstd)"
        )
        os.replace(tmp, path)
    return n


def pull(
    coverage: Region,
    lake: Path,
    now: datetime,
    *,
    live_keys: list[str] = (),  # type: ignore[assignment]
    inat=None,
    gbif=None,
) -> dict:
    """Fetch what changed since the cursors, for the whole coverage area, into new parts."""
    from wildlife_scanner.connectors.base import ObservationQuery
    from wildlife_scanner.connectors.gbif import GBIFConnector
    from wildlife_scanner.connectors.inaturalist import INaturalistConnector

    cursor = read_cursor(lake, coverage.id)
    window_start = (now - timedelta(days=WINDOW_DAYS)).date()
    started = utcnow()
    out: dict = {}
    since = (
        datetime.fromisoformat(cursor["inaturalist"])
        if cursor.get("inaturalist")
        else now - timedelta(days=3)
    )
    query = ObservationQuery(
        bbox=coverage.bbox,
        start=window_start,
        updated_since=since - timedelta(hours=1),
        limit=MAX_RECORDS,
    )
    n = _write_part(lake, coverage.id, (inat or INaturalistConnector()).fetch(query), now, "inat")
    out["inaturalist"] = n
    # When capped, keep the cursor so the next pull continues the backlog.
    cursor["inaturalist"] = (since if n >= MAX_RECORDS else started).isoformat()
    if live_keys:
        gsince = (
            datetime.fromisoformat(cursor["gbif"])
            if cursor.get("gbif")
            else now - timedelta(days=WINDOW_DAYS)
        )
        gquery = ObservationQuery(
            bbox=coverage.bbox,
            start=window_start,
            updated_since=gsince - timedelta(days=1),
            limit=MAX_RECORDS,
            dataset_keys=tuple(live_keys),
        )
        try:
            g = _write_part(lake, coverage.id, (gbif or GBIFConnector()).fetch(gquery), now, "gbif")
            out["gbif"] = g
            cursor["gbif"] = (gsince if g >= MAX_RECORDS else started).isoformat()
        except Exception as exc:  # retried next pull; doesn't block iNaturalist
            out["gbif_error"] = f"{type(exc).__name__}: {exc}"
    cursor["pulled_at"] = started.isoformat()
    _write_cursor(lake, coverage.id, cursor)
    return out


def parts(lake: Path, coverage_id: str) -> list[Path]:
    return sorted(log_dir(lake, coverage_id).glob("day=*/part-*.parquet"), key=lambda p: p.name)


def load_region(
    conn: duckdb.DuckDBPyConnection,
    region: Region,
    lake: Path,
    coverage_id: str,
    after: str | None,
) -> dict:
    """Load parts newer than ``after`` (a part name) into the region's store, filtered to its
    box, and apply known deletions. Returns counts and the new ``after``."""
    new = [p for p in parts(lake, coverage_id) if after is None or p.name > after]
    loaded = 0
    if new:
        files = "[" + ", ".join(f"'{p.as_posix()}'" for p in new) + "]"
        lon_min, lat_min, lon_max, lat_max = region.bbox
        before = conn.execute("SELECT count(*) FROM observations").fetchone()[0]
        conn.execute(
            f"""
            INSERT OR REPLACE INTO observations BY NAME
            SELECT * FROM read_parquet({files}, union_by_name = true, hive_partitioning = false)
            WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            QUALIFY row_number() OVER (PARTITION BY dedupe_key ORDER BY ingested_at DESC) = 1
            """,
            [lat_min, lat_max, lon_min, lon_max],
        )
        loaded = conn.execute("SELECT count(*) FROM observations").fetchone()[0] - before
        after = new[-1].name
    removed = apply_deletions(conn, lake, coverage_id)
    return {"parts": len(new), "rows_added": loaded, "removed": removed, "after": after}


# -- Deletions ---------------------------------------------------------------------------------


def check_existence(
    lake: Path,
    coverage_id: str,
    now: datetime,
    *,
    days: int = 7,
    client=None,
    limiter=None,
) -> dict:
    """Ask iNaturalist again for logged observations from the last ``days``; list the ones
    that no longer come back (deleted or made private) in ``deleted/``."""
    from wildlife_scanner.connectors.base import RateLimiter, get_json, make_client

    files = parts(lake, coverage_id)
    if not files:
        return {"checked": 0, "deleted": 0}
    src = "[" + ", ".join(f"'{p.as_posix()}'" for p in files) + "]"
    since = (now - timedelta(days=days)).replace(tzinfo=None)
    ids = [
        r[0]
        for r in duckdb.connect()
        .execute(
            f"SELECT DISTINCT source_record_id FROM read_parquet({src}, union_by_name = true, "
            "hive_partitioning = false) "
            "WHERE source_id = 'inaturalist' AND source_record_id IS NOT NULL "
            "AND time_start >= ?",
            [since],
        )
        .fetchall()
    ]
    client = client or make_client(timeout=60)
    limiter = limiter or RateLimiter(1.0)
    gone: list[str] = []
    for i in range(0, len(ids), 200):
        batch = ids[i : i + 200]
        payload = get_json(
            client,
            "https://api.inaturalist.org/v1/observations",
            {"id": ",".join(batch), "per_page": 200, "only_id": "true"},
            limiter,
            retries=4,
        )
        found = {str(r.get("id")) for r in payload.get("results") or []}
        gone += [x for x in batch if x not in found]
    if gone:
        folder = log_dir(lake, coverage_id) / "deleted"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"part-{now.strftime('%Y%m%dT%H%M%S')}.parquet"
        con = duckdb.connect()
        con.execute("CREATE TABLE d (dedupe_key VARCHAR, found_at TIMESTAMP)")
        con.executemany(
            "INSERT INTO d VALUES (?, ?)", [(f"inat:{x}", now.replace(tzinfo=None)) for x in gone]
        )
        con.execute(f"COPY d TO '{path.as_posix()}' (FORMAT parquet)")
    return {"checked": len(ids), "deleted": len(gone)}


def apply_deletions(conn: duckdb.DuckDBPyConnection, lake: Path, coverage_id: str) -> int:
    files = sorted((log_dir(lake, coverage_id) / "deleted").glob("part-*.parquet"))
    if not files:
        return 0
    src = "[" + ", ".join(f"'{p.as_posix()}'" for p in files) + "]"
    before = conn.execute("SELECT count(*) FROM observations").fetchone()[0]
    conn.execute(
        "DELETE FROM observations WHERE dedupe_key IN "
        f"(SELECT dedupe_key FROM read_parquet({src}, hive_partitioning = false))"
    )
    return before - conn.execute("SELECT count(*) FROM observations").fetchone()[0]


def check_due(cursor: dict, now: datetime, every: timedelta = timedelta(days=1)) -> bool:
    last = cursor.get("checked_at")
    return last is None or now - datetime.fromisoformat(last) >= every


def mark_checked(lake: Path, coverage_id: str, now: datetime) -> None:
    cursor = read_cursor(lake, coverage_id)
    cursor["checked_at"] = now.astimezone(UTC).isoformat()
    _write_cursor(lake, coverage_id, cursor)
