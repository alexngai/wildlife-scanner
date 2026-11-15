"""Private lake storage: the R2 REST backend, lake sync, and tile splitting."""

from __future__ import annotations

import json
from urllib.parse import unquote

import duckdb
import httpx
import pytest

from wildlife_scanner.pipeline import coverage
from wildlife_scanner.pipeline.sync import lake_files, sync_lake
from wildlife_scanner.storage import objects
from wildlife_scanner.storage.objects import LocalStore, R2RestStore, open_store

PREFIX = "/client/v4/accounts/acct/r2/buckets/lake-bucket/objects"


def fake_r2(per_page: int = 2):
    """An in-memory stand-in for Cloudflare's R2 object API (as probed on 2026-11-14)."""
    objs: dict[str, tuple[bytes, dict]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        assert path.startswith(PREFIX)
        key = unquote(path[len(PREFIX) + 1 :])
        if request.method == "PUT":
            objs[key] = (request.read(), dict(request.headers))
            return httpx.Response(200, json={"success": True, "result": {"key": key}})
        if request.method == "DELETE":
            if objs.pop(key, None) is None:
                body = {"success": False, "errors": [{"code": 10007, "message": "missing"}]}
                return httpx.Response(200, json=body)
            return httpx.Response(200, json={"success": True})
        if key:
            if key not in objs:
                return httpx.Response(404, json={"success": False, "errors": [{"code": 10007}]})
            return httpx.Response(200, content=objs[key][0])
        prefix = request.url.params.get("prefix", "")
        keys = sorted(k for k in objs if k.startswith(prefix))
        start = int(request.url.params.get("cursor") or 0)
        page = keys[start : start + per_page]
        more = start + per_page < len(keys)
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": [{"key": k, "size": len(objs[k][0])} for k in page],
                "result_info": {
                    "cursor": str(start + per_page) if more else "",
                    "is_truncated": more,
                },
            },
        )

    return objs, httpx.Client(transport=httpx.MockTransport(handler))


def test_r2_rest_store_round_trip(tmp_path, monkeypatch):
    objs, client = fake_r2()
    store = R2RestStore("acct", "lake-bucket", "lake", client=client)
    assert store.url == "r2://acct/lake-bucket/lake"
    f = tmp_path / "a b.parquet"
    f.write_bytes(b"\x00\x01binary")
    store.put_file("ref/x/a b.parquet", f)
    store.put_text("norm/c/_cursor.json", '{"x": 1}')
    for i in range(3):
        store.put_text(f"norm/p{i}", "z")
    assert "lake/ref/x/a b.parquet" in objs  # under the prefix, the space survives
    assert objs["lake/ref/x/a b.parquet"][1]["cache-control"] == objects.IMMUTABLE
    assert store.list("norm/") == ["norm/c/_cursor.json", "norm/p0", "norm/p1", "norm/p2"]
    assert store.stat("ref/") == {"ref/x/a b.parquet": 8}  # pages followed by cursor
    store.get_file("ref/x/a b.parquet", tmp_path / "back.parquet")
    assert (tmp_path / "back.parquet").read_bytes() == b"\x00\x01binary"
    assert store.get_text("norm/c/_cursor.json") == '{"x": 1}'
    assert store.get_text("nope") is None
    store.delete(["norm/p0", "norm/never-existed"])
    assert "lake/norm/p0" not in objs
    monkeypatch.setattr(objects, "R2_MAX_PUT", 4)
    with pytest.raises(ValueError, match="300 MiB"):
        store.put_file("ref/big", f)


def test_open_store_r2_url():
    store = open_store("r2://acct/lake-bucket/some/prefix")
    assert isinstance(store, R2RestStore) and store.prefix == "some/prefix"
    assert store.base.endswith("/accounts/acct/r2/buckets/lake-bucket")
    with pytest.raises(ValueError):
        open_store("r2://acct-only")


def _lake(root):
    snap = root / "norm/observations/source=gbif/snapshot=2026-11-01/coverage=california"
    (snap / "tlat=36/tlon=-122").mkdir(parents=True)
    (snap / "tlat=36/tlon=-122/part-0.parquet").write_bytes(b"tile")
    (snap / "_SUCCESS.json").write_text("{}")
    (snap / "delta.json").write_text("{}")
    partial = root / "norm/observations/source=gbif/snapshot=2026-12-01/coverage=california"
    (partial / "tlat=36/tlon=-122").mkdir(parents=True)
    (partial / "tlat=36/tlon=-122/part-0.parquet").write_bytes(b"half")
    live = root / "norm/observations/source=live/coverage=california"
    (live / "day=2026-11-13").mkdir(parents=True)
    (live / "day=2026-11-13/part-1-inat.parquet").write_bytes(b"live")
    (live / "_cursor.json").write_text('{"inaturalist": "a"}')
    (live / "day=2026-11-13/.part-2.parquet.tmp").write_bytes(b"in progress")
    (root / "ref/taxon_identity").mkdir(parents=True)
    (root / "ref/taxon_identity/part-w1.parquet").write_bytes(b"ref")
    (root / "publish").mkdir()
    (root / "publish/CURRENT").write_text("v1")  # not part of the lake sync
    return snap, live


class Recording(LocalStore):
    def __init__(self, root):
        super().__init__(root)
        self.puts: list[str] = []

    def put_file(self, key, path, cache_control=objects.IMMUTABLE):
        self.puts.append(key)
        super().put_file(key, path, cache_control)


def test_sync_lake_push_then_restore(tmp_path):
    lake = tmp_path / "lake"
    snap, live = _lake(lake)
    keys = set(lake_files(lake))
    assert not any("2026-12-01" in k or ".tmp" in k or k.startswith("publish") for k in keys)
    store = Recording(tmp_path / "bucket")
    out = sync_lake(store, lake, push=True, workers=1)
    assert out["pushed"] == len(keys) == 6
    names = [k.rsplit("/", 1)[-1] for k in store.puts]
    assert set(names[-2:]) == {"_SUCCESS.json", "delta.json"}  # markers last
    assert sync_lake(store, lake, push=True)["pushed"] == 0  # nothing new
    (live / "_cursor.json").write_text('{"inaturalist": "b"}')
    assert sync_lake(store, lake, push=True)["pushed"] == 1  # the cursor moved
    # A fresh machine: pull only the reference store and the live log, then everything.
    fresh = tmp_path / "fresh"
    part = sync_lake(
        store, fresh, push=False, pull=True, pull_prefixes=("ref", "norm/observations/source=live")
    )
    assert part["pulled"] == 3 and not (fresh / "norm/observations/source=gbif").exists()
    assert json.loads((fresh / live.relative_to(lake) / "_cursor.json").read_text()) == {
        "inaturalist": "b"
    }
    assert sync_lake(store, fresh, push=False, pull=True)["pulled"] == 3
    assert set(lake_files(fresh)) == keys
    # A tile replaced by smaller parts here: prune drops the old remote copy.
    tile = snap / "tlat=36/tlon=-122"
    (tile / "part-0.parquet").rename(tile / "part-0-s0.parquet")
    out = sync_lake(store, lake, push=True, prune=True)
    assert out["pushed"] == 1 and out["pruned"] == 1
    assert [k for k in store.list("norm/") if "tlon=-122" in k] == [
        str((tile / "part-0-s0.parquet").relative_to(lake))
    ]


def test_split_large_tiles_keeps_every_row(tmp_path):
    lake = tmp_path / "lake"
    folder = coverage.snapshot_dir(lake, "california", "2026-11-01") / "tlat=36" / "tlon=-122"
    folder.mkdir(parents=True)
    big = folder / "part-0.parquet"
    duckdb.connect().execute(
        "COPY (SELECT i AS gbifid, md5(i::VARCHAR) AS h FROM range(300000) t(i)) "
        f"TO '{big}' (FORMAT parquet, ROW_GROUP_SIZE 20000)"
    )
    small = folder / "part-1.parquet"
    duckdb.connect().execute(f"COPY (SELECT 1 AS gbifid, 'x' AS h) TO '{small}' (FORMAT parquet)")
    done = coverage.split_large(
        lake, "california", "2026-11-01", max_bytes=2_000_000, limit=5_000_000
    )
    assert done == ["tlat=36/tlon=-122/part-0.parquet"]
    # Pieces may overshoot the target a little, but stay under the limit: not split again.
    assert (
        coverage.split_large(lake, "california", "2026-11-01", max_bytes=2_000_000, limit=5_000_000)
        == []
    )
    pieces = sorted(p.name for p in folder.glob("*.parquet"))
    assert "part-0.parquet" not in pieces and "part-1.parquet" in pieces and len(pieces) > 2
    rows, ids = (
        duckdb.connect()
        .execute(
            f"SELECT count(*), count(DISTINCT gbifid) FROM read_parquet('{folder}/*.parquet', "
            "hive_partitioning = false)"
        )
        .fetchone()
    )
    assert (rows, ids) == (300001, 300000)  # every row once; the small file repeats id 1


def test_retention_keeps_two_snapshots_and_recent_live_days(tmp_path):
    from datetime import UTC, datetime

    from wildlife_scanner.pipeline import livelog, retention

    lake = tmp_path / "lake"
    for d in ("2026-08-01", "2026-09-01", "2026-10-01", "2026-11-01"):
        folder = coverage.snapshot_dir(lake, "california", d)
        (folder / "tlat=36/tlon=-122").mkdir(parents=True)
        (folder / "tlat=36/tlon=-122/part-0.parquet").write_bytes(b"x")
        (folder / coverage.SUCCESS).write_text("{}")
    unfinished = coverage.snapshot_dir(lake, "california", "2026-07-01")
    unfinished.mkdir(parents=True)  # no _SUCCESS: never touched
    log = livelog.log_dir(lake, "california")
    for d in ("2026-08-20", "2026-09-05", "2026-10-30", "2026-11-12"):
        (log / f"day={d}").mkdir(parents=True)
        (log / f"day={d}/part-1-inat.parquet").write_bytes(b"x")
    (log / "_cursor.json").write_text("{}")
    store = LocalStore(tmp_path / "bucket")
    sync_lake(store, lake, push=True)
    now = datetime(2026, 11, 14, tzinfo=UTC)
    planned = retention.plan(lake, now)
    assert [p.split("snapshot=")[1][:10] for p in planned["snapshots"]] == [
        "2026-08-01",
        "2026-09-01",
    ]
    # Past 67 days (60 + margin) and older than the newest snapshot.
    assert [p.rsplit("=", 1)[1] for p in planned["live_days"]] == ["2026-08-20", "2026-09-05"]
    out = retention.prune(lake, now, store=store)
    assert out["remote_deleted"] == 6  # 2 snapshots x (tile + marker), 2 live parts
    assert unfinished.exists() and (log / "_cursor.json").exists()
    assert set(lake_files(lake)) == set(store.list("norm/"))
    assert retention.plan(lake, now) == {"snapshots": [], "live_days": []}
