"""One API process serving several regions from their published bundles."""

from __future__ import annotations

import warnings
from datetime import UTC, datetime

import pytest

from wildlife_radar.baseline import build_baseline
from wildlife_radar.pipeline.publish import publish_bundle
from wildlife_radar.policy.statuses import StaticStatusProvider, build_tier_table
from wildlife_radar.regions import load_region
from wildlife_radar.storage import ObservationStore
from wildlife_radar.synthetic import SyntheticSpecies, SyntheticWorld

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from wildlife_radar.api import create_app  # noqa: E402

NOW = datetime(2026, 1, 20, tzinfo=UTC)
MONTEREY = (36.62, -121.90)
SAN_DIEGO = (32.85, -117.27)
OTTER = SyntheticSpecies(name="Lutrinus montereyensis", centers=((36.62, -121.90, 8.0),), base=0.4)


def _publish(region_id: str, world: SyntheticWorld, root):
    region = load_region(region_id)
    st = ObservationStore()
    st.add(world.generate())
    build_baseline(st.conn, region_id=region.id, bbox=region.bbox)
    build_tier_table(
        st.conn, region_id=region.id, scopes=region.scopes, providers=[StaticStatusProvider()]
    )
    publish_bundle(st.conn, region, root, now=NOW)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("publish")
    _publish("socal", SyntheticWorld(), root)
    monterey = SyntheticWorld(
        bbox=(-122.05, 36.45, -121.70, 36.90),
        species=(OTTER,),
        hotspots=((36.62, -121.90, 0.5, 3.0),),
        observers=40,
    )
    _publish("montereybay", monterey, root)
    # "california" is served too but has nothing published yet.
    app = create_app(bundle_dir=root, region_id=["socal", "montereybay", "california"], now=NOW)
    return TestClient(app)


def test_health_lists_each_region(client):
    health = client.get("/health").json()
    by_region = {r["region"]: r for r in health["regions"]}
    assert by_region["socal"]["status"] == by_region["montereybay"]["status"] == "ok"
    assert by_region["california"]["status"] == "not published"
    assert {r["region"] for r in client.get("/regions").json()} == set(by_region)


def test_taxon_requests_name_a_region(client):
    assert client.get("/taxa").status_code == 400
    otters = client.get("/taxa", params={"region": "montereybay"}).json()
    assert [t["taxon_id"] for t in otters] == ["lutrinus-montereyensis"]
    socal = {t["taxon_id"] for t in client.get("/taxa", params={"region": "socal"}).json()}
    assert "lutrinus-montereyensis" not in socal
    assert client.get("/taxa", params={"region": "nowhere"}).status_code == 404
    r = client.get(
        "/species/lutrinus-montereyensis/map",
        params={"region": "montereybay", "date": "2025-07-01"},
    )
    assert r.status_code == 200 and r.json()["cells"]


def test_points_and_places_route_to_their_region(client):
    def listed(params, path="/nearby"):
        r = client.get(path, params={"date": "2025-07-01", **params})
        assert r.status_code == 200, r.text
        return {i["taxon_id"] for g in r.json()["groups"] for i in g["most_likely"]}

    assert "lutrinus-montereyensis" in listed({"lat": MONTEREY[0], "lon": MONTEREY[1]})
    assert "lutrinus-montereyensis" not in listed({"lat": SAN_DIEGO[0], "lon": SAN_DIEGO[1]})
    assert "lutrinus-montereyensis" in listed({}, "/places/breakwater-monterey/lists")
    regions = {p["place_id"]: p["region"] for p in client.get("/places").json()}
    assert regions["breakwater-monterey"] == "montereybay" and regions["la-jolla-cove"] == "socal"
    # Outside every served region; inside a region with nothing published yet.
    assert client.get("/nearby", params={"lat": 45.5, "lon": -122.6}).status_code == 400
    assert client.get("/nearby", params={"lat": 38.58, "lon": -121.49}).status_code == 503


def test_two_regions_sharing_a_place_id_are_refused(tmp_path):
    with pytest.raises(ValueError, match="la-jolla-cove"):
        create_app(bundle_dir=tmp_path, region_id=["socal", "sandiego"])
