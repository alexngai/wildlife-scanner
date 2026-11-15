import warnings
from datetime import UTC, datetime

import h3
import pytest

from wildlife_scanner.baseline import backtest_baseline, build_baseline
from wildlife_scanner.policy import ConservationStatus
from wildlife_scanner.policy.statuses import StaticStatusProvider, StatusLookup, build_tier_table
from wildlife_scanner.regions import load_region
from wildlife_scanner.storage import ObservationStore
from wildlife_scanner.synthetic import DEFAULT_SPECIES, SyntheticSpecies, SyntheticWorld

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from wildlife_scanner.api import create_app  # noqa: E402

SECRET = SyntheticSpecies(name="Secretus maximus", centers=((32.86, -117.25, 6.0),), base=0.3)
LA_JOLLA = {"lat": 32.85, "lon": -117.27}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db = tmp_path_factory.mktemp("api") / "test.duckdb"
    region = load_region("socal")
    world = SyntheticWorld(species=(*DEFAULT_SPECIES, SECRET))
    with ObservationStore(db) as store:
        store.add(world.generate())
        build_baseline(store.conn, region_id="socal", bbox=region.bbox)
        backtest_baseline(
            store.conn,
            region_id="socal",
            bbox=region.bbox,
            split=datetime(2025, 1, 1, tzinfo=UTC),
        )
        provider = StaticStatusProvider(
            {
                "raritas-orientalis": StatusLookup(
                    statuses=(ConservationStatus(authority="IUCN", code="EN"),), source="t"
                ),
                "secretus-maximus": StatusLookup(
                    statuses=(ConservationStatus(authority="CITES", code="I"),), source="t"
                ),
            }
        )
        build_tier_table(store.conn, region_id="socal", scopes=region.scopes, providers=[provider])
    return TestClient(create_app(db, now=datetime(2026, 11, 11, tzinfo=UTC)))


def test_health_and_source_link(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.headers["x-source-code"].startswith("https://")
    assert client.get("/source").json()["license"] == "AGPL-3.0-only"
    assert {s["source_id"] for s in client.get("/sources").json()} >= {"gbif", "inaturalist"}


def test_taxa_hide_withheld(client):
    taxa = {t["taxon_id"]: t for t in client.get("/taxa").json()}
    assert "secretus-maximus" not in taxa
    assert taxa["raritas-orientalis"]["mode"] == "awareness"
    assert taxa["vernalis-litoralis"]["mode"] == "forecast"
    assert taxa["vernalis-litoralis"]["gate"]["passes"] is True


def test_withheld_is_indistinguishable_from_unknown(client):
    a = client.get("/species/secretus-maximus/map")
    b = client.get("/species/no-such-taxon/map")
    assert a.status_code == b.status_code == 404
    assert a.json() == b.json()


def test_open_species_map(client):
    m = client.get("/species/vernalis-litoralis/map", params={"date": "2026-05-15"}).json()
    assert m["time_window"]["precision"] == "week"
    assert {c["resolution"] for c in m["cells"]} == {6}
    top = m["cells"][0]
    assert top["p"] > 0.3 and top["seasonal_index"] > 2
    assert m["license"]["noncommercial"] is True
    assert m["maturity_level"] == 0


def test_coarse_species_map(client):
    m = client.get("/species/raritas-orientalis/map", params={"date": "2026-05-15"}).json()
    assert m["time_window"]["precision"] == "month"
    assert {c["resolution"] for c in m["cells"]} == {3}


def test_calendars(client):
    cal = client.get(
        "/species/vernalis-litoralis/calendar", params={**LA_JOLLA, "year": 2026}
    ).json()
    assert cal["granularity"] == "week" and len(cal["entries"]) == 52
    peak = max(cal["entries"], key=lambda e: e["p"])
    assert "2026-04-20" <= peak["start"] <= "2026-06-01"
    coarse = client.get(
        "/species/raritas-orientalis/calendar", params={"lat": 33.05, "lon": -116.9, "year": 2026}
    ).json()
    assert coarse["granularity"] == "month" and len(coarse["entries"]) == 12
    assert h3.get_resolution(coarse["cell"]) == 3


def test_place_lists_respect_policy(client):
    r = client.get(
        "/nearby", params={**LA_JOLLA, "date": "2026-05-15", "life_list": "commonus-ubiquitus"}
    ).json()
    assert [g["group"] for g in r["groups"]] == ["birds:casual"]
    birds = r["groups"][0]
    assert birds["taxon_group"] == "birds" and birds["method"] == "observer_visit"
    ranked = {
        i["taxon_id"] for k in ("most_likely", "special_here", "peaking_now") for i in birds[k]
    }
    assert "raritas-orientalis" not in ranked
    assert "secretus-maximus" not in ranked
    assert [a["taxon_id"] for a in r["awareness"]] == ["raritas-orientalis"]
    assert all(i["lift"] >= 1.25 for i in birds["special_here"])
    assert birds["peaking_now"][0]["taxon_id"] == "vernalis-litoralis"
    assert "commonus-ubiquitus" not in {i["taxon_id"] for i in birds["new_for_you"]}
    assert "secretus" not in str(r)
    fishes = client.get(
        "/nearby", params={**LA_JOLLA, "date": "2026-05-15", "group": "fishes"}
    ).json()
    assert fishes["groups"] == [] and fishes["awareness"] == []


def test_place_endpoint_and_errors(client):
    assert client.get("/places").status_code == 200
    assert (
        client.get("/places/la-jolla-cove/lists", params={"date": "2026-05-15"}).status_code == 200
    )
    assert client.get("/places/nowhere/lists").status_code == 404
    assert client.get("/nearby", params={"lat": 40, "lon": -100}).status_code == 400
    assert client.get("/species/vernalis-litoralis/map", params={"date": "bad"}).status_code == 400
    assert client.get("/species/vernalis-litoralis/calendar").status_code == 400
