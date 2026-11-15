"""Lake retention: what the shared layers no longer need (docs/design/ingestion.md §6).

- **Coverage snapshots:** the newest ``KEEP_SNAPSHOTS`` complete snapshots of each coverage
  area are kept (the current one, and the previous one that ``delta.json`` compares with).
  Unfinished builds are left alone.
- **Live log:** a day folder is dropped once it is past the live window (plus a margin) *and*
  older than the newest complete snapshot, which holds those records by then. Cursors and the
  ``deleted/`` lists are kept.

``prune`` deletes locally and, given a store, the same keys remotely.
"""

from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from wildlife_scanner.pipeline import coverage, livelog

KEEP_SNAPSHOTS = 2
LIVE_MARGIN_DAYS = 7


def _complete_snapshots(lake: Path) -> dict[str, list[str]]:
    """Coverage id → complete snapshot dates, oldest first."""
    root = lake / "norm" / "observations" / "source=gbif"
    out: dict[str, list[str]] = {}
    for marker in sorted(root.glob(f"snapshot=*/coverage=*/{coverage.SUCCESS}")):
        cov = marker.parent.name.removeprefix("coverage=")
        out.setdefault(cov, []).append(marker.parent.parent.name.removeprefix("snapshot="))
    return {k: sorted(v) for k, v in out.items()}


def plan(lake: Path, now: datetime, keep: int = KEEP_SNAPSHOTS) -> dict[str, list[str]]:
    """Folders (relative to the lake) that retention would delete, by kind."""
    snapshots = _complete_snapshots(lake)
    old_snapshots = [
        coverage.snapshot_dir(lake, cov, d).relative_to(lake).as_posix()
        for cov, dates in snapshots.items()
        for d in dates[:-keep]
    ]
    cutoff = (now - timedelta(days=livelog.WINDOW_DAYS + LIVE_MARGIN_DAYS)).date()
    old_days: list[str] = []
    for cov, dates in snapshots.items():
        newest = date.fromisoformat(dates[-1])
        folder = livelog.log_dir(lake, cov)
        for day in sorted(folder.glob("day=*")):
            d = date.fromisoformat(day.name.removeprefix("day="))
            if d < cutoff and d < newest:
                old_days.append(day.relative_to(lake).as_posix())
    return {"snapshots": old_snapshots, "live_days": old_days}


def prune(lake: Path, now: datetime, store=None, dry_run: bool = False) -> dict:
    """Delete what ``plan`` lists, here and (with ``store``) in object storage."""
    todo = plan(lake, now)
    out: dict = {**todo, "remote_deleted": 0}
    if dry_run:
        return out
    for rel in todo["snapshots"] + todo["live_days"]:
        if store is not None:
            keys = store.list(f"{rel}/")
            if keys:
                store.delete(keys)
                out["remote_deleted"] += len(keys)
        shutil.rmtree(lake / rel, ignore_errors=True)
    return out
