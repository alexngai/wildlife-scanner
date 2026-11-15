"""Monthly GBIF snapshot ingest: listing, range-request extraction, and the snapshot job."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from test_storage import _write_snapshot

from wildlife_scanner.connectors import gbif_snapshot_remote as remote
from wildlife_scanner.pipeline import runner
from wildlife_scanner.pipeline.runner import Job, JobContext, latest, run
from wildlife_scanner.regions import load_region
from wildlife_scanner.storage import ObservationStore
from wildlife_scanner.synthetic import SyntheticWorld

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
    # Re-ingesting the same date is possible on request.
    c.params["reingest_snapshot"] = True
    run("down", c, jobs=jobs, force=("snapshot",))
    assert latest(c.lake, "socal", "snapshot")["outputs"]["snapshot_date"] == "2026-11-01"
    assert calls == ["down", "down", "down"]


def test_snapshot_job_without_ingest_registers_store(tmp_path):
    c = _ctx(tmp_path)
    jobs = {"snapshot": runner.JOBS["snapshot"]}
    assert "no observations" in run("snapshot", c, jobs=jobs)[0]["outcome"]
    with ObservationStore(c.db) as store:
        store.add(SyntheticWorld(observers=2, visits_per_observer=2).generate()[:3])
    assert run("snapshot", c, jobs=jobs)[0]["outcome"]["observations"] == 3


def test_coverage_snapshot_tiles_delta_and_reconciliation(tmp_path, monkeypatch):
    import duckdb

    from wildlife_scanner.pipeline import coverage

    oct_file, nov_file = tmp_path / "oct.parquet", tmp_path / "nov.parquet"
    _write_snapshot(oct_file)
    duckdb.connect().execute(
        f"COPY (SELECT * FROM read_parquet('{oct_file}') WHERE gbifid <> '2') "
        f"TO '{nov_file}' (FORMAT parquet)"
    )
    files = {
        "occurrence/2026-10-01/occurrence.parquet/000000": oct_file.read_bytes(),
        "occurrence/2026-11-01/occurrence.parquet/000000": nov_file.read_bytes(),
    }
    monkeypatch.setattr(
        remote,
        "make_client",
        lambda timeout=30.0: httpx.Client(
            transport=_bucket(files, ["2026-10-01", "2026-11-01"], {"2026-10-01", "2026-11-01"})
        ),
    )
    california = load_region("california")
    lake = tmp_path / "lake"
    quiet = {"log": lambda _m: None}
    built = coverage.build(california, "2026-10-01", lake, workers=2, **quiet)
    assert built["rows"] == 2 and built["tiles"] == {"32_-118": 2}  # the Dakota row is outside
    assert coverage.build(california, "2026-10-01", lake, **quiet)["reused"]
    region = load_region("sandiego")
    assert region.coverage == "california"
    db = tmp_path / "sd.duckdb"
    first = coverage.ingest_region(region, db, lake, "california", "2026-10-01", workers=1, **quiet)
    assert first["total"] == 2
    # Live-dataset rows: one pulled before the next snapshot was taken, one after.
    with ObservationStore(db) as store:
        for key, when in (("live-old", "2026-10-15"), ("live-new", "2026-11-05")):
            store.conn.execute(
                "INSERT INTO observations (dedupe_key, obs_id, source_id, dataset_key, lat, lon, "
                "ingested_at) VALUES (?, ?, 'gbif', 'whale-feed', 32.8, -117.3, ?)",
                [key, key, when],
            )
        # A live copy of snapshot record 1, pulled after the next snapshot was taken.
        (key,) = store.conn.execute(
            "SELECT dedupe_key FROM observations WHERE source_record_id = '1'"
        ).fetchone()
        store.conn.execute(
            "UPDATE observations SET source_id = 'inaturalist', ingested_at = '2026-11-06' "
            "WHERE dedupe_key = ?",
            [key],
        )
    nov = coverage.build(california, "2026-11-01", lake, workers=2, **quiet)
    assert nov["delta"]["totals"]["removed"] == 1
    assert nov["delta"]["datasets"]["ds-1"]["removed"] == 1
    second = coverage.ingest_region(
        region, db, lake, "california", "2026-11-01", workers=1, live_keys=["whale-feed"], **quiet
    )
    with ObservationStore(db) as store:
        keys = {k for (k,) in store.conn.execute("SELECT dedupe_key FROM observations").fetchall()}
    assert second["removed"] == 2  # record 2 (gone from GBIF) and the old live-dataset row
    assert "live-new" in keys and "live-old" not in keys and len(keys) == 2
    with ObservationStore(db) as store:
        kept = store.conn.execute(
            "SELECT source_id FROM observations WHERE dedupe_key = ?", [key]
        ).fetchone()
    assert kept == ("inaturalist",)  # the newer live row wins over the snapshot's copy


def test_big_files_are_cut_into_row_ranges(tmp_path):
    path = tmp_path / "tile.parquet"
    _write_snapshot(path)
    whole = remote._segments([str(path)])
    assert len(whole) == 1 and whole[0][0][1] == 0
    cut = remote._segments([str(path)], rows_per_chunk=1)
    n_rows = whole[0][-1][2]
    assert len(cut) == n_rows and all(len(c) == 1 for c in cut)
    parsed = [
        remote._parse_chunk((str(tmp_path / f"c{i}.parquet"), segs, SOCAL))[1]
        for i, segs in enumerate(cut)
    ]
    assert sum(parsed) == remote._parse_chunk((str(tmp_path / "w.parquet"), whole[0], SOCAL))[1]
    assert sum(parsed) == 2
