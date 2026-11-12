"""Monthly GBIF snapshot ingest: listing, range-request extraction, and the snapshot job."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from test_storage import _write_snapshot

from wildlife_radar.connectors import gbif_snapshot_remote as remote
from wildlife_radar.pipeline import runner
from wildlife_radar.pipeline.runner import Job, JobContext, latest, run
from wildlife_radar.regions import load_region
from wildlife_radar.storage import ObservationStore
from wildlife_radar.synthetic import SyntheticWorld

SOCAL = (-121.0, 32.4, -114.1, 35.8)


def _listing(keys=(), prefixes=()) -> str:
    body = "".join(f"<Contents><Key>{k}</Key><Size>{s}</Size></Contents>" for k, s in keys)
    body += "".join(f"<CommonPrefixes><Prefix>{p}</Prefix></CommonPrefixes>" for p in prefixes)
    return f"<ListBucketResult>{body}</ListBucketResult>"


def _bucket(files: dict[str, bytes], dates: list[str], complete: set[str]):
    """A fake S3 bucket: listings and byte-range reads of ``files``."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.lstrip("/")
        if key:
            data = files[key]
            spec = request.headers["Range"].removeprefix("bytes=")
            start, end = spec.split("-")
            # A suffix range ("-N") asks for the last N bytes.
            part = data[-int(end) :] if not start else data[int(start) : int(end) + 1]
            return httpx.Response(206, content=part)
        prefix = request.url.params["prefix"]
        if prefix == "occurrence/":
            return httpx.Response(200, text=_listing(prefixes=[f"occurrence/{d}/" for d in dates]))
        date = prefix.split("/")[1]
        if prefix.endswith("occurrence.parquet/"):
            keys = [(k, len(v)) for k, v in files.items() if k.startswith(prefix)]
            return httpx.Response(200, text=_listing(keys=keys))
        keys = [(f"occurrence/{date}/citation.txt", 10)] if date in complete else []
        return httpx.Response(
            200, text=_listing(keys=keys, prefixes=[f"occurrence/{date}/occurrence.parquet/"])
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def bucket(tmp_path, monkeypatch):
    path = tmp_path / "part.parquet"
    _write_snapshot(path)
    files = {
        "occurrence/2026-10-01/occurrence.parquet/000000": path.read_bytes(),
        "occurrence/2026-11-01/occurrence.parquet/000000": path.read_bytes(),
    }
    state = {"dates": ["2026-10-01", "2026-11-01"], "complete": {"2026-10-01"}}

    def client(timeout: float = 30.0):
        return httpx.Client(transport=_bucket(files, state["dates"], state["complete"]))

    monkeypatch.setattr(remote, "make_client", client)
    return state


def test_latest_snapshot_skips_incomplete_uploads(bucket):
    assert remote.latest_snapshot() == "2026-10-01"  # 2026-11-01 has no citation.txt yet
    bucket["complete"].add("2026-11-01")
    assert remote.latest_snapshot() == "2026-11-01"


def test_extract_then_ingest_matches_local_read(bucket, tmp_path):
    parts = remote.list_parts("2026-11-01")
    assert len(parts) == 1
    staging = tmp_path / "staging"
    stats = remote.extract_region(parts, staging, tmp_path / "work", SOCAL, 2, log=lambda _m: None)
    assert stats["rows"] == 2 and stats["matched"] == 1  # out-of-bbox row left behind
    # Resumable: a second pass skips finished parts.
    again = remote.extract_region(parts, staging, tmp_path / "work", SOCAL, 2, log=lambda _m: None)
    assert again["skipped_done"] == 1 and again["bytes"] == 0
    out = remote.ingest_staged(tmp_path / "s.duckdb", staging, SOCAL, 1, log=lambda _m: None)
    assert out["total"] == 2
    with ObservationStore(tmp_path / "s.duckdb") as store:
        taxa = sorted(
            r[0] or "" for r in store.conn.execute("SELECT taxon_id FROM observations").fetchall()
        )
    assert taxa == ["", "toxostoma-redivivum"]


def _ctx(tmp_path, **params) -> JobContext:
    return JobContext(
        region=load_region("socal"),
        region_path=None,
        db=tmp_path / "store.duckdb",
        lake=tmp_path / "lake",
        now=datetime(2026, 11, 12, tzinfo=UTC),
        log=lambda _m: None,
        params=params,
    )


def test_snapshot_job_ingests_only_newer_snapshots(bucket, tmp_path):
    calls: list[str] = []
    jobs = {
        "snapshot": runner.JOBS["snapshot"],
        "down": Job("down", ("snapshot",), lambda _c: calls.append("down") or {}),
    }
    c = _ctx(tmp_path, ingest_snapshots=True, snapshot_workers=2)
    first = {r["job"]: r for r in run("down", c, jobs=jobs)}
    assert first["snapshot"]["outcome"]["snapshot_date"] == "2026-10-01"
    assert first["snapshot"]["outcome"]["observations"] == 2
    assert not (c.lake / "raw").exists() or not any((c.lake / "raw").rglob("*.parquet"))
    version = latest(c.lake, "socal", "snapshot")["version"]
    # Live records arrive; no new snapshot: the check keeps the version, nothing downstream runs.
    with ObservationStore(c.db) as store:
        store.add(SyntheticWorld(observers=2, visits_per_observer=2).generate()[:3])
    run("down", c, jobs=jobs, force=("snapshot",))
    m = latest(c.lake, "socal", "snapshot")
    assert m["outputs"].get("unchanged") and m["version"] == version and m["run"] != version
    assert calls == ["down"]
    # A newer complete snapshot is ingested and downstream jobs rerun.
    bucket["complete"].add("2026-11-01")
    run("down", c, jobs=jobs, force=("snapshot",))
    m = latest(c.lake, "socal", "snapshot")
    assert m["outputs"]["snapshot_date"] == "2026-11-01" and m["version"] != version
    assert calls == ["down", "down"]


def test_snapshot_job_without_ingest_registers_store(tmp_path):
    c = _ctx(tmp_path)
    jobs = {"snapshot": runner.JOBS["snapshot"]}
    assert "no observations" in run("snapshot", c, jobs=jobs)[0]["outcome"]
    with ObservationStore(c.db) as store:
        store.add(SyntheticWorld(observers=2, visits_per_observer=2).generate()[:3])
    assert run("snapshot", c, jobs=jobs)[0]["outcome"]["observations"] == 3
