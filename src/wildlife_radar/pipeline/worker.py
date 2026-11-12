"""The scheduled worker: bring ``publish`` up to date on a fixed tick, then push it.

Cadences live on the jobs themselves (``Job.max_age``): each tick runs only what is stale, so
one loop gives live records every tick (30 min), signals daily, a snapshot check weekly with a
full rebuild when GBIF publishes a new monthly snapshot, and model refits monthly. Publishing
stays gated on the tier audit: a blocked publish fails the job, and the bucket keeps serving
the previous version.

The worker owns the region's work store (one DuckDB writer); the API never touches it.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from wildlife_radar.core.time import utcnow
from wildlife_radar.pipeline.runner import Job, JobContext, run
from wildlife_radar.pipeline.sync import KEEP_VERSIONS, prune_local, push_publish
from wildlife_radar.storage.objects import ObjectStore


def failed(results: list[dict]) -> list[str]:
    return [
        r["job"]
        for r in results
        if isinstance(r.get("outcome"), str) or r["reason"].startswith("blocked")
    ]


def tick(
    ctx: JobContext,
    store: ObjectStore | None = None,
    *,
    keep: int = KEEP_VERSIONS,
    jobs: dict[str, Job] | None = None,
) -> dict:
    """One scheduled pass: run stale jobs up to ``publish``, push, prune. Never raises for a
    job failure (the next tick retries it); push errors are reported the same way."""
    started = utcnow()
    results = run("publish", ctx, jobs=jobs)
    out: dict = {
        "started": started.isoformat(),
        "ran": [r["job"] for r in results if "outcome" in r],
        "failed": failed(results),
    }
    publish_root = ctx.lake / "publish"
    if store is not None and (publish_root / f"region={ctx.region.id}").exists():
        try:
            out["push"] = push_publish(publish_root, store, ctx.region.id, keep)
        except Exception as exc:  # network errors: retry next tick
            out["push_error"] = f"{type(exc).__name__}: {exc}"
    out["pruned_local"] = prune_local(publish_root, ctx.region.id, keep)
    out["seconds"] = round((utcnow() - started).total_seconds(), 1)
    errors = {r["job"]: r["outcome"] for r in results if isinstance(r.get("outcome"), str)}
    if errors:
        out["errors"] = errors
    _status(ctx.lake, ctx.region.id, out)
    return out


def _status(lake: Path, region_id: str, out: dict) -> None:
    """The last tick's summary, for health checks and debugging."""
    path = lake / "worker" / f"region={region_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")


def loop(
    make_context: Callable[[], JobContext],
    every: timedelta,
    store: ObjectStore | None = None,
    *,
    ticks: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> None:
    """Tick every ``every`` (measured start to start; a long tick starts the next at once)."""
    n = 0
    while ticks is None or n < ticks:
        start = time.monotonic()
        ctx = make_context()  # fresh ``now`` for staleness checks
        out = tick(ctx, store)
        log(json.dumps({k: out[k] for k in ("started", "ran", "failed", "seconds")}))
        n += 1
        if ticks is not None and n >= ticks:
            return
        sleep(max(0.0, every.total_seconds() - (time.monotonic() - start)))
