from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from wildlife_radar.baseline import build_baseline
from wildlife_radar.connectors.base import RateLimiter, make_client
from wildlife_radar.connectors.inaturalist_taxa import (
    InatTaxonStatusProvider,
    parse_taxon_statuses,
)
from wildlife_radar.policy import ConservationStatus, PolicyTier
from wildlife_radar.policy.statuses import (
    CachedStatusProvider,
    RegionStatusFile,
    StaticStatusProvider,
    StatusLookup,
    TaxonInfo,
    TierService,
    build_tier_table,
    most_severe_geoprivacy,
)
from wildlife_radar.profiles import ProfileLibrary
from wildlife_radar.regions import load_region, region_dir
from wildlife_radar.storage import ObservationStore
from wildlife_radar.synthetic import SyntheticWorld

NOW = datetime(2026, 11, 11, tzinfo=UTC)
SCOPES = ["global", "us", "us-ca"]


@pytest.fixture(scope="module")
def store():
    world = SyntheticWorld(seed=5, observers=20, visits_per_observer=40)
    st = ObservationStore()
    st.add(world.generate())
    build_baseline(st.conn, region_id="r", bbox=world.bbox)
    return st


class Boom:
    name = "boom"
    authoritative = True

    def lookup_many(self, taxa):
        raise RuntimeError("provider down")


def tiers(store, providers):
    return {
        t: d.tier
        for t, d in build_tier_table(
            store.conn, region_id="r", scopes=SCOPES, providers=providers, now=NOW
        ).items()
    }


def test_region_file_alone_fails_closed(store, tmp_path):
    empty = tmp_path / "statuses.yaml"
    empty.write_text("statuses: []\n")
    assert set(tiers(store, [RegionStatusFile(empty)]).values()) == {PolicyTier.COARSE}


def test_authoritative_lookup_opens_and_statuses_raise(store):
    provider = StaticStatusProvider(
        {
            "raritas-orientalis": StatusLookup(
                statuses=(ConservationStatus(authority="ESA", code="E", scope="us-ca"),),
                source="t",
            )
        }
    )
    result = tiers(store, [provider])
    assert result["commonus-ubiquitus"] is PolicyTier.OPEN
    assert result["raritas-orientalis"] is PolicyTier.COARSE
    reasons = store.conn.execute(
        "SELECT reasons FROM tiers WHERE region_id = 'r' AND taxon_id = 'raritas-orientalis'"
    ).fetchone()[0]
    assert "ESA:E" in reasons


def test_provider_failure_fails_closed(store):
    result = tiers(store, [Boom(), StaticStatusProvider(authoritative=False)])
    assert set(result.values()) == {PolicyTier.COARSE}


def test_observed_geoprivacy_raises_tier(store):
    store.conn.execute(
        "UPDATE observations SET taxon_geoprivacy = 'obscured' "
        "WHERE taxon_id = 'vernalis-litoralis' AND obs_id = "
        "(SELECT min(obs_id) FROM observations WHERE taxon_id = 'vernalis-litoralis')"
    )
    try:
        assert tiers(store, [StaticStatusProvider()])["vernalis-litoralis"] is PolicyTier.COARSE
    finally:
        store.conn.execute("UPDATE observations SET taxon_geoprivacy = NULL")


def test_bundled_region_status_file():
    region = load_region("socal")
    provider = RegionStatusFile(region_dir("socal") / "statuses.yaml")
    puma = provider.lookup_many([TaxonInfo(taxon_id="puma-concolor", scientific_name="P c")])
    statuses = puma["puma-concolor"].statuses
    assert statuses and statuses[0].scope in region.scopes
    assert not provider.authoritative


INAT_TAXON = {
    "id": 42007,
    "name": "Puma concolor",
    "conservation_statuses": [
        {
            "place": None,
            "status": "LC",
            "authority": "IUCN Red List",
            "iucn": 10,
            "geoprivacy": "open",
        },
        {
            "place": {"id": 14, "name": "California"},
            "status": "threatened",
            "authority": "CDFW",
            "iucn": 30,
            "geoprivacy": "obscured",
        },
        {
            "place": {"id": 99999, "name": "Somewhere else"},
            "status": "E",
            "authority": "Other State",
            "iucn": 40,
            "geoprivacy": "private",
        },
        {
            "place": {"id": 29, "name": "Michigan", "ancestor_place_ids": [97394, 1, 29]},
            "status": "S1",
            "authority": "NatureServe",
            "iucn": 50,
            "geoprivacy": "obscured",
        },
    ],
}


def test_parse_inat_statuses():
    lookup = parse_taxon_statuses(INAT_TAXON, {"1": "us", "14": "us-ca"}, "14")
    codes = {(s.code, s.scope) for s in lookup.statuses}
    assert codes == {("LC", "global"), ("VU", "us-ca")}
    assert lookup.geoprivacy == "obscured"  # the unmapped place's "private" is ignored
    assert len(lookup.ignored) == 2  # "somewhere else" and Michigan


def test_status_scope_direction():
    from wildlife_radar.connectors.inaturalist_taxa import status_scope

    scopes = {"1": "us", "14": "us-ca"}
    michigan = {"id": 29, "ancestor_place_ids": [97394, 1, 29]}
    sd_county = {"id": 829, "ancestor_place_ids": [97394, 1, 14, 829]}
    assert status_scope(None, scopes, "14") == "global"
    assert status_scope({"id": 1}, scopes, "14") == "us"
    assert status_scope(michigan, scopes, "14") is None  # inside the US is not containing SoCal
    assert status_scope(sd_county, scopes, "14") == "us-ca"  # inside California: applies
    assert status_scope(sd_county, scopes, None) is None


def test_inat_provider_and_cache():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/v1/taxa":
            return httpx.Response(200, json={"results": [{"id": 42007, "name": "Puma concolor"}]})
        return httpx.Response(200, json={"results": [INAT_TAXON]})

    inner = InatTaxonStatusProvider(
        {"14": "us-ca"},
        innermost_place="14",
        client=make_client(transport=httpx.MockTransport(handler)),
        limiter=RateLimiter(0),
    )
    st = ObservationStore()
    cached = CachedStatusProvider(st.conn, inner, now=NOW)
    taxa = [TaxonInfo(taxon_id="puma-concolor", scientific_name="Puma concolor")]
    first = cached.lookup_many(taxa)["puma-concolor"]
    assert {s.code for s in first.statuses} == {"LC", "VU"}
    assert calls == ["/v1/taxa", "/v1/taxa/42007"]
    cached.lookup_many(taxa)
    assert len(calls) == 2  # served from cache
    stale = CachedStatusProvider(st.conn, inner, now=NOW + timedelta(days=200))
    stale.lookup_many(taxa)
    assert len(calls) == 4  # expired → refetched


def test_most_severe_geoprivacy():
    assert most_severe_geoprivacy([None, "open", "obscured"]) == "obscured"
    assert most_severe_geoprivacy(["obscured", "private"]) == "private"
    assert most_severe_geoprivacy([None]) is None


def test_tier_service_applies_profile_windows():
    st = ObservationStore()
    st.conn.execute(
        "CREATE TABLE tiers (region_id VARCHAR, taxon_id VARCHAR, tier SMALLINT, "
        "reasons VARCHAR, decided_at TIMESTAMP)"
    )
    st.conn.execute("INSERT INTO tiers VALUES ('socal', 'atractoscion-nobilis', 0, '[]', NULL)")
    svc = TierService(st.conn, "socal", profiles=ProfileLibrary(), now=NOW)
    assert svc.get("atractoscion-nobilis", date(2026, 5, 1)) is PolicyTier.GENERALIZED
    assert svc.get("atractoscion-nobilis", date(2026, 8, 1)) is PolicyTier.OPEN
    assert svc.get("unknown-taxon", date(2026, 8, 1)) is PolicyTier.COARSE
    assert svc.get(None, date(2026, 8, 1)) is PolicyTier.COARSE


def test_curated_statuses_match_crosswalk_aliases(tmp_path):
    # A curated entry keyed by an older name still applies after a rename (via the crosswalk).
    import json as _json

    from wildlife_radar.baseline import build_baseline
    from wildlife_radar.policy.statuses import RegionStatusFile, build_tier_table
    from wildlife_radar.storage import ObservationStore
    from wildlife_radar.synthetic import SyntheticWorld

    world = SyntheticWorld()
    store = ObservationStore()
    store.add(world.generate())
    build_baseline(store.conn, region_id="socal", bbox=world.bbox)
    store.conn.execute(
        "CREATE TABLE taxon_identity (query_name VARCHAR PRIMARY KEY, taxon_id VARCHAR, "
        "record JSON, fetched_at TIMESTAMP)"
    )
    record = {
        "query_name": "Raritas orientalis",
        "taxon_id": "raritas-orientalis",
        "accepted_name": "Raritas orientalis",
        "synonyms": ["Rarus antiquus"],
        "ids": {},
        "verified": {},
    }
    store.conn.execute(
        "INSERT INTO taxon_identity VALUES ('Raritas orientalis', 'raritas-orientalis', ?, NULL)",
        [_json.dumps(record)],
    )
    path = tmp_path / "statuses.yaml"
    path.write_text(
        "statuses:\n  - {taxon_id: rarus-antiquus, authority: ESA, code: E, scope: us}\n",
        encoding="utf-8",
    )
    decisions = build_tier_table(
        store.conn,
        region_id="socal",
        scopes=["global", "us"],
        providers=[RegionStatusFile(path), StaticStatusProvider()],
    )
    assert decisions["raritas-orientalis"].tier >= PolicyTier.GENERALIZED
    assert decisions["commonus-ubiquitus"].tier == PolicyTier.OPEN
