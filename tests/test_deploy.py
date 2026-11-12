"""Object storage, publish sync, the scheduled worker, and serving from a bucket."""

from __future__ import annotations

import warnings
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wildlife_radar.pipeline.publish import CURRENT, current_bundle, publish_bundle, set_current
from wildlife_radar.pipeline.runner import Job, JobContext, run
from wildlife_radar.pipeline.sync import prune_local, pull_current, push_publish
from wildlife_radar.pipeline.worker import tick
from wildlife_radar.regions import load_region
from wildlife_radar.storage.objects import LocalStore, S3Store, open_store

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from wildlife_radar.api import create_app  # noqa: E402


@pytest.fixture(params=["local", "s3"])
def bucket(request, tmp_path, monkeypatch):
    if request.param == "local":
        yield LocalStore(tmp_path / "bucket")
        return
    moto = pytest.importorskip("moto")
    import boto3

    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(var, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_ENDPOINT_URL_S3", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with moto.mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="publish")
        yield S3Store("publish", "lake/publish", client=client)


def test_store_round_trip(bucket, tmp_path):
    src = tmp_path / "a.json"
    src.write_text('{"x": 1}', encoding="utf-8")
    bucket.put_file("region=r/version=1/a.json", src)
    bucket.put_text("region=r/CURRENT", "1\n")
    assert bucket.get_text("region=r/CURRENT") == "1\n"
    assert bucket.get_text("region=r/missing") is None
    assert bucket.list("region=r/") == ["region=r/CURRENT", "region=r/version=1/a.json"]
    bucket.get_file("region=r/version=1/a.json", tmp_path / "out" / "a.json")
    assert (tmp_path / "out" / "a.json").read_text(encoding="utf-8") == '{"x": 1}'
    bucket.delete(["region=r/version=1/a.json"])
    assert bucket.list("region=r/version=") == []


def test_local_store_rejects_escaping_keys(tmp_path):
    with pytest.raises(ValueError):
        LocalStore(tmp_path / "b").get_text("../secret")


def test_open_store_parses_urls(tmp_path):
    assert isinstance(open_store(tmp_path), LocalStore)
    assert isinstance(open_store(f"file://{tmp_path}"), LocalStore)


def _fake_publish(root: Path, version: str, region: str = "r") -> None:
    folder = root / f"region={region}" / f"version={version}"
    (folder / "static").mkdir(parents=True)
    (folder / "serving.duckdb").write_bytes(version.encode())
    (folder / "manifest.json").write_text("{}", encoding="utf-8")
    (folder / "static" / "taxa.json").write_text("[]", encoding="utf-8")
    set_current(root / f"region={region}", version)


def test_push_pull_and_prune(bucket, tmp_path):
    publish, cache = tmp_path / "publish", tmp_path / "cache"
    for v in ("v1", "v2", "v3"):
        _fake_publish(publish, v)
        out = push_publish(publish, bucket, "r", keep=2)
        assert out["uploaded"] == 3
        assert pull_current(bucket, "r", cache) == v
    assert push_publish(publish, bucket, "r", keep=2)["uploaded"] == 0  # already there
    assert pull_current(bucket, "r", cache) is None  # already current
    assert bucket.get_text(f"region=r/{CURRENT}").strip() == "v3"
    remote = {k.split("/")[1] for k in bucket.list("region=r/version=")}
    assert remote == {"version=v2", "version=v3"}  # v1 pruned
    assert current_bundle(cache / "region=r").read_bytes() == b"v3"
    local = {p.name for p in (cache / "region=r").glob("version=*")}
    assert local == {"version=v2", "version=v3"}  # the previous version is kept for open readers
    # Rollback: point CURRENT back at a kept version.
    bucket.put_text(f"region=r/{CURRENT}", "v2\n")
    assert pull_current(bucket, "r", cache) == "v2"
    assert current_bundle(cache / "region=r").read_bytes() == b"v2"


def test_prune_local_keeps_current(tmp_path):
    for v in ("v1", "v2", "v3"):
        _fake_publish(tmp_path, v)
    set_current(tmp_path / "region=r", "v1")
    assert prune_local(tmp_path, "r", keep=1) == ["v2"]


def _ctx(tmp_path) -> JobContext:
    return JobContext(
        region=load_region("socal"),
        region_path=None,
        db=tmp_path / "store.duckdb",
        lake=tmp_path / "lake",
        now=datetime(2026, 11, 12, tzinfo=UTC),
        log=lambda _m: None,
    )


def test_worker_pushes_only_audited_versions(tmp_path):
    bucket = LocalStore(tmp_path / "bucket")
    state = {"version": 0}

    def publish(ctx):
        state["version"] += 1
        _fake_publish(ctx.lake / "publish", f"v{state['version']}", ctx.region.id)
        return {"version": f"v{state['version']}"}

    jobs = {
        "live": Job("live", (), lambda _c: {"n": 1}),
        "publish": Job("publish", ("live",), publish),
    }
    c = _ctx(tmp_path)
    out = tick(c, bucket, jobs=jobs)
    assert out["ran"] == ["live", "publish"] and out["failed"] == []
    assert out["push"]["version"] == "v1"
    assert (tmp_path / "lake" / "worker" / "region=socal.json").exists()
    # Nothing stale: nothing runs, nothing uploads.
    out = tick(c, bucket, jobs=jobs)
    assert out["ran"] == [] and out["push"]["uploaded"] == 0


def test_worker_blocked_publish_keeps_previous_remote(tmp_path):
    bucket = LocalStore(tmp_path / "bucket")
    calls = {"n": 0}

    def publish(ctx):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("tier audit has 1 high-severity findings")
        _fake_publish(ctx.lake / "publish", "v1", ctx.region.id)
        return {"version": "v1"}

    jobs = {"publish": Job("publish", (), publish)}
    c = _ctx(tmp_path)
    assert tick(c, bucket, jobs=jobs)["push"]["version"] == "v1"
    # The next publish is blocked by the audit (forced rerun via a failed manifest).
    run("publish", c, jobs=jobs, force=("publish",))
    out = tick(c, bucket, jobs=jobs)
    assert out["failed"] == ["publish"] and "audit" in out["errors"]["publish"]
    assert bucket.get_text("region=socal/CURRENT").strip() == "v1"


def test_api_serves_a_bundle_pulled_from_the_bucket(tmp_path, monkeypatch):
    from wildlife_radar.baseline import build_baseline
    from wildlife_radar.policy.statuses import StaticStatusProvider, build_tier_table
    from wildlife_radar.storage import ObservationStore
    from wildlife_radar.synthetic import SyntheticWorld

    region = load_region("socal")
    st = ObservationStore()
    st.add(SyntheticWorld().generate())
    build_baseline(st.conn, region_id="socal", bbox=region.bbox)
    build_tier_table(
        st.conn, region_id="socal", scopes=region.scopes, providers=[StaticStatusProvider()]
    )
    now = datetime(2026, 1, 20, tzinfo=UTC)
    publish_bundle(st.conn, region, tmp_path / "publish", now=now)
    bucket = LocalStore(tmp_path / "bucket")
    push_publish(tmp_path / "publish", bucket, "socal")
    assert pull_current(bucket, "socal", tmp_path / "cache")
    monkeypatch.setenv("WILDLIFE_RADAR_CORS_ORIGINS", "https://app.example.org")
    client = TestClient(create_app(bundle_dir=tmp_path / "cache", region_id="socal", now=now))
    health = client.get("/health").json()
    assert health["bundle"].startswith("version=")
    r = client.get("/taxa", headers={"Origin": "https://app.example.org"})
    assert r.json() and r.headers["access-control-allow-origin"] == "https://app.example.org"
    other = client.get("/taxa", headers={"Origin": "https://elsewhere.example"})
    assert "access-control-allow-origin" not in other.headers
