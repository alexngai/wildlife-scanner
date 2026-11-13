"""Repairs to stored records whose source data is known to be wrong.

``redate_from_event_ids``: some datasets stamp a placeholder ``eventDate`` while the real date
survives in ``eventID``. Records on a placeholder date get their date, week, time window and
visit key rewritten from the event id. Only records on the given placeholder dates are touched,
and only where the event id holds a valid ``YYYYMMDD`` date.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime

import duckdb

EVENT_IDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS gbif_event_ids (
    gbif_id VARCHAR PRIMARY KEY, dataset_key VARCHAR, event_id VARCHAR, fetched_at TIMESTAMP
)
"""
"""GBIF record id → eventID, fetched from the API (snapshots lack eventID). Region-independent,
so shared through the reference store: a rebuild re-applies them instead of re-fetching."""


def store_event_ids(
    conn: duckdb.DuckDBPyConnection,
    dataset_key: str,
    pairs: Iterable[tuple[str, str]],
    fetched_at: datetime,
) -> int:
    """Keep ``(gbifID, eventID)`` pairs in ``gbif_event_ids`` (the reference store's copy)."""
    conn.execute(EVENT_IDS_SCHEMA)
    rows = [(g, dataset_key, e, fetched_at.replace(tzinfo=None)) for g, e in pairs]
    if rows:
        conn.executemany("INSERT OR REPLACE INTO gbif_event_ids VALUES (?, ?, ?, ?)", rows)
    return len(rows)


def adopt_event_ids(conn: duckdb.DuckDBPyConnection, dataset_key: str, fetched_at: datetime) -> int:
    """Copy event ids already on the dataset's records (from earlier runs) into
    ``gbif_event_ids``, so they count as fetched and reach the reference store."""
    conn.execute(EVENT_IDS_SCHEMA)
    before = conn.execute("SELECT count(*) FROM gbif_event_ids").fetchone()[0]
    conn.execute(
        """
        INSERT OR IGNORE INTO gbif_event_ids
        SELECT source_record_id, dataset_key, event_id, ?
        FROM observations
        WHERE dataset_key = ? AND event_id IS NOT NULL AND source_record_id IS NOT NULL
        """,
        [fetched_at.replace(tzinfo=None), dataset_key],
    )
    return conn.execute("SELECT count(*) FROM gbif_event_ids").fetchone()[0] - before


def apply_event_ids(conn: duckdb.DuckDBPyConnection, dataset_key: str) -> int:
    """Fill missing ``event_id`` of the dataset's records from ``gbif_event_ids`` (one update)."""
    conn.execute(EVENT_IDS_SCHEMA)
    before = conn.execute(
        "SELECT count(*) FROM observations WHERE dataset_key = ? AND event_id IS NOT NULL",
        [dataset_key],
    ).fetchone()[0]
    conn.execute(
        """
        UPDATE observations SET event_id = g.event_id
        FROM gbif_event_ids g
        WHERE observations.dataset_key = ? AND g.dataset_key = ?
          AND observations.source_record_id = g.gbif_id AND observations.event_id IS NULL
        """,
        [dataset_key, dataset_key],
    )
    after = conn.execute(
        "SELECT count(*) FROM observations WHERE dataset_key = ? AND event_id IS NOT NULL",
        [dataset_key],
    ).fetchone()[0]
    return after - before


def fetched_events(conn: duckdb.DuckDBPyConnection, dataset_key: str) -> set[str]:
    """Events whose records' ids are already known (stored in whole chunks of events)."""
    conn.execute(EVENT_IDS_SCHEMA)
    return {
        e
        for (e,) in conn.execute(
            "SELECT DISTINCT event_id FROM gbif_event_ids WHERE dataset_key = ?", [dataset_key]
        ).fetchall()
    }


def set_event_ids(
    conn: duckdb.DuckDBPyConnection, dataset_key: str, pairs: Iterable[tuple[str, str]]
) -> int:
    """Fill ``event_id`` from ``(source_record_id, eventID)`` pairs for one dataset."""
    conn.execute("CREATE OR REPLACE TEMP TABLE _event_ids (record_id VARCHAR, event_id VARCHAR)")
    rows = list(pairs)
    if not rows:
        return 0
    conn.executemany("INSERT INTO _event_ids VALUES (?, ?)", rows)
    before = conn.execute(
        "SELECT count(*) FROM observations WHERE dataset_key = ? AND event_id IS NOT NULL",
        [dataset_key],
    ).fetchone()[0]
    conn.execute(
        """
        UPDATE observations SET event_id = e.event_id
        FROM _event_ids e
        WHERE observations.dataset_key = ? AND observations.source_record_id = e.record_id
          AND observations.event_id IS NULL
        """,
        [dataset_key],
    )
    after = conn.execute(
        "SELECT count(*) FROM observations WHERE dataset_key = ? AND event_id IS NOT NULL",
        [dataset_key],
    ).fetchone()[0]
    return after - before


def missing_event_ids(
    conn: duckdb.DuckDBPyConnection, dataset_key: str, dates: Sequence[date]
) -> int:
    return conn.execute(
        "SELECT count(*) FROM observations WHERE dataset_key = ? AND event_id IS NULL "
        "AND local_date IN (SELECT unnest(?))",
        [dataset_key, list(dates)],
    ).fetchone()[0]


def redate_from_event_ids(
    conn: duckdb.DuckDBPyConnection, dataset_key: str, pattern: str, dates: Sequence[date]
) -> int:
    """Re-date records on placeholder ``dates`` from the date in their event id."""
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _redate AS
        SELECT dedupe_key, d, lon, visit_key FROM (
            SELECT dedupe_key, lon, visit_key,
                try_strptime(regexp_extract(event_id, ?, 1), '%Y%m%d')::DATE AS d
            FROM observations
            WHERE dataset_key = ? AND event_id IS NOT NULL
              AND local_date IN (SELECT unnest(?))
        ) WHERE d IS NOT NULL
        """,
        [pattern, dataset_key, list(dates)],
    )
    n = conn.execute("SELECT count(*) FROM _redate").fetchone()[0]
    if n:
        # Times are stored as naive UTC; local midnight is approximated from longitude, as
        # when the records were first stored (storage/observations.py: local_date).
        conn.execute(
            """
            UPDATE observations SET
                local_date = r.d,
                week = least(weekofyear(r.d), 52),
                time_start = r.d::TIMESTAMP - to_hours(CAST(round(r.lon / 15) AS INTEGER)),
                time_end = r.d::TIMESTAMP - to_hours(CAST(round(r.lon / 15) AS INTEGER))
                    + INTERVAL 1 DAY,
                time_precision = 'day',
                visit_key = regexp_replace(
                    r.visit_key,
                    '\\|\\d{4}-\\d{2}-\\d{2}\\|',
                    '|' || strftime(r.d, '%Y-%m-%d') || '|'
                )
            FROM _redate r
            WHERE observations.dedupe_key = r.dedupe_key
            """
        )
    conn.execute("DROP TABLE IF EXISTS _redate")
    return n
