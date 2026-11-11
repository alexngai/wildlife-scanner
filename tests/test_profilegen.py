import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
import yaml

from wildlife_radar.baseline import build_baseline
from wildlife_radar.connectors.base import RateLimiter, make_client
from wildlife_radar.profilegen.candidates import Candidate, Rank
from wildlife_radar.profilegen.draft import build_draft, load_doc, promote, write_draft
from wildlife_radar.profilegen.extract import (
    EXTRACTION_FIELDS,
    ClaudeExtractor,
    RawExtraction,
    StaticExtractor,
    extraction_candidates,
    output_schema,
    verify,
)
from wildlife_radar.profilegen.identity import IdentityResolver, TaxonIdentity
from wildlife_radar.profilegen.occurrence import (
    diel_candidates,
    seasonality,
    seasonality_candidates,
    solar_elevation,
)
from wildlife_radar.profilegen.pipeline import Generator
from wildlife_radar.profilegen.reconcile import reconcile
from wildlife_radar.profilegen.traits import TetrapodTraits, activity_from
from wildlife_radar.profilegen.wikipedia import Article
from wildlife_radar.profiles import ProfileLibrary
from wildlife_radar.profiles.schema import Provenance
from wildlife_radar.storage import ObservationStore
from wildlife_radar.synthetic import SyntheticWorld

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 11, tzinfo=UTC)

# Invented text (not copied from any source) for extraction tests.
ARTICLE = Article(
    title="Example cat",
    revid=123,
    text=(
        "The example cat (Felis exemplaris) is a small wild cat.\n\n"
        "It is mostly nocturnal and   hunts rodents. Individuals hold home ranges of 2 to 9 "
        "square kilometres. It lives in oak woodland and chaparral."
    ),
)
NAMES = ["Felis exemplaris"]


def prov(source="s", method="import", confidence=0.9, license="CC-BY-4.0"):
    return Provenance(source=source, method=method, confidence=confidence, license=license)


# -- identity ---------------------------------------------------------------------------------


def mock_services(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "species/match" in url:
        assert request.url.params["name"] == "Felis antiqua"
        return httpx.Response(
            200,
            json={
                "usageKey": 11,
                "acceptedUsageKey": 10,
                "canonicalName": "Felis antiqua",
                "rank": "SPECIES",
                "status": "SYNONYM",
                "matchType": "EXACT",
                "confidence": 99,
                "kingdom": "Animalia",
                "phylum": "Chordata",
                "class": "Mammalia",
                "order": "Carnivora",
                "family": "Felidae",
                "genus": "Felis",
                "species": "Felis exemplaris",
                "speciesKey": 10,
            },
        )
    if "sparql" in url:
        query = parse_qs(request.content.decode())["query"][0]
        assert '"Felis exemplaris"' in query
        return httpx.Response(
            200,
            json={
                "results": {
                    "bindings": [
                        {
                            "key": {"value": "Felis exemplaris"},
                            "item": {"value": "http://www.wikidata.org/entity/Q1"},
                            "name": {"value": "Felis exemplaris"},
                            "gbifs": {"value": "10"},
                            "inaturalists": {"value": "500"},
                            "ncbis": {"value": "77"},
                            "statuses": {"value": "http://www.wikidata.org/entity/Q11394"},
                            "wiki": {"value": "https://en.wikipedia.org/wiki/Example_cat"},
                            "commonName": {"value": "odd sample name"},
                        }
                    ]
                }
            },
        )
    if "inaturalist" in url:
        ids = request.url.path.rsplit("/", 1)[-1]
        records = {
            "500": {
                "id": 500,
                "name": "Felis exemplaris",
                "rank": "species",
                "is_active": False,
                "current_synonymous_taxon_ids": [501],
            },
            "501": {
                "id": 501,
                "name": "Leopardus exemplaris",
                "rank": "species",
                "is_active": True,
                "preferred_common_name": "Example Cat",
                "iconic_taxon_name": "Mammalia",
            },
        }
        return httpx.Response(200, json={"results": [records[i] for i in ids.split(",")]})
    return httpx.Response(404)


def test_identity_resolution_with_crosswalk_and_taxon_moves():
    client = make_client(transport=httpx.MockTransport(mock_services))
    resolver = IdentityResolver(client=client, limiter=RateLimiter(0))
    ident = resolver.resolve("Felis antiqua")
    assert ident.taxon_id == "felis-exemplaris"
    assert ident.accepted_name == "Felis exemplaris"
    assert "Felis antiqua" in ident.synonyms  # the queried synonym
    assert ident.ids["gbif"] == "10" and ident.ids["ncbi"] == "77"
    # Wikidata pointed at an inactive iNaturalist concept: follow it to the current one.
    assert ident.ids["inaturalist"] == "501" and ident.verified["inaturalist"]
    assert "Leopardus exemplaris" in ident.synonyms
    assert ident.common_name == "Example Cat"  # iNaturalist beats Wikidata's arbitrary sample
    assert ident.iucn_category == "EN"
    assert ident.wikipedia_title == "Example cat"
    assert ident.taxon_group == "mammals"
    assert set(ident.alias_ids) >= {"felis-exemplaris", "felis-antiqua", "leopardus-exemplaris"}


def test_unmatched_names_are_reported():
    def none(request):
        return httpx.Response(200, json={"matchType": "NONE", "confidence": 100})

    resolver = IdentityResolver(
        client=make_client(transport=httpx.MockTransport(none)), limiter=RateLimiter(0)
    )
    ident = resolver.resolve("Nonexistus imaginarius")
    assert not ident.resolved and ident.notes


# -- traits -----------------------------------------------------------------------------------


def test_tetrapodtraits_candidates():
    tt = TetrapodTraits(FIXTURES / "tetrapodtraits_sample.csv")
    cat = {c.field: c for c in tt.candidates(["Felis exemplaris"])}
    assert cat["traits.activity_pattern"].value == "nocturnal"
    assert cat["traits.activity_pattern"].rank == Rank.DB_MEASURED
    assert cat["traits.body_mass_g"].value == 12000
    assert cat["traits.iucn_habitats"].value == ["forest", "shrubland"]
    assert "status" not in str([c.field for c in cat.values()])  # IUCN column never imported
    bird = {c.field: c for c in tt.candidates(["Avis imputata"])}
    assert bird["traits.activity_pattern"].value == "diurnal"
    assert bird["traits.activity_pattern"].rank == Rank.DB_IMPUTED
    assert bird["traits.body_length_mm"].provenance.measured is False
    assert bird["traits.ecosystems"].value == ["terrestrial", "freshwater", "marine"]
    assert tt.candidates(["Not present"]) == []
    assert activity_from(0.9, 0.8) == "cathemeral" and activity_from(None, 1) is None


# -- extraction -------------------------------------------------------------------------------


def test_output_schema_has_not_stated_option_and_no_status_fields():
    schema = output_schema(EXTRACTION_FIELDS)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(EXTRACTION_FIELDS)
    item = schema["properties"]["activity_pattern"]
    assert item["required"] == ["stated", "value", "evidence"]
    assert {"type": "null"} in item["properties"]["value"]["anyOf"]
    assert not any("status" in f or "policy" in f or "tier" in f for f in EXTRACTION_FIELDS)


def test_evidence_verification():
    ok = verify(
        RawExtraction(
            field="activity_pattern",
            value="nocturnal",
            evidence="It is mostly nocturnal and hunts rodents.",  # whitespace differs
        ),
        ARTICLE,
        NAMES,
    )
    assert ok.accepted and ok.start is not None and ok.end > ok.start
    invented = verify(
        RawExtraction(field="activity_pattern", value="diurnal", evidence="It is active by day."),
        ARTICLE,
        NAMES,
    )
    assert not invented.accepted and "not found" in invented.reason
    out_of_bounds = verify(
        RawExtraction(
            field="home_range_km2",
            value={"min": -2, "max": 9},
            evidence="home ranges of 2 to 9 square kilometres",
        ),
        ARTICLE,
        NAMES,
    )
    assert not out_of_bounds.accepted
    off_vocab = verify(
        RawExtraction(field="habitats", value=["mangrove"], evidence="It lives in oak woodland"),
        ARTICLE,
        NAMES,
    )
    assert not off_vocab.accepted
    rng = verify(
        RawExtraction(
            field="home_range_km2",
            value={"min": 2, "max": 9},
            evidence="home ranges of 2 to 9 square kilometres",
        ),
        ARTICLE,
        NAMES,
    )
    assert rng.accepted and rng.value == [2.0, 9.0]


def test_extraction_candidates_cite_revision_not_text():
    extractor = StaticExtractor(
        {
            "Example cat": {
                "activity_pattern": {
                    "stated": True,
                    "value": "nocturnal",
                    "evidence": "It is mostly nocturnal",
                },
                "habitats": {
                    "stated": True,
                    "value": ["oak_woodland", "chaparral"],
                    "evidence": "It lives in oak woodland and chaparral.",
                },
                "migratory": {"stated": False, "value": None, "evidence": ""},
                "depth_m": {"stated": True, "value": {"min": 0, "max": 5}, "evidence": "made up"},
            }
        }
    )
    result = extractor.extract(ARTICLE, NAMES, EXTRACTION_FIELDS)
    cands, checks = extraction_candidates(result, ARTICLE, NAMES)
    assert {c.field for c in cands} == {"traits.activity_pattern", "traits.habitats"}
    assert [c.field for c in checks if not c.accepted] == ["depth_m"]
    p = cands[0].provenance
    assert p.method == "extracted" and p.license == "CC-BY-SA-4.0"
    assert "oldid=123" in p.evidence and "chars" in p.evidence
    assert "nocturnal" not in p.evidence  # no copied sentences in profiles
    assert p.extractor.startswith("static+prompt:")
    # An article about something else yields nothing.
    other = Article(title="Unrelated", text="A page about rivers. It is mostly nocturnal.")
    cands, checks = extraction_candidates(result, other, NAMES)
    assert cands == [] and all(c.reason == "article not about taxon" for c in checks)


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def fake_client(stop_reason, text):
    response = SimpleNamespace(
        stop_reason=stop_reason,
        model="served-model",
        content=[SimpleNamespace(type="text", text=text)],
    )
    messages = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_claude_extractor_request_and_parsing(monkeypatch):
    monkeypatch.delenv("WILDLIFE_RADAR_EXTRACTION_MODEL", raising=False)
    with pytest.raises(ValueError):
        ClaudeExtractor()
    payload = {name: {"stated": False, "value": None, "evidence": ""} for name in EXTRACTION_FIELDS}
    payload["activity_pattern"] = {
        "stated": True,
        "value": "nocturnal",
        "evidence": "It is mostly nocturnal",
    }
    client, messages = fake_client("end_turn", json.dumps(payload))
    result = ClaudeExtractor(model="configured-model", client=client).extract(
        ARTICLE, NAMES, EXTRACTION_FIELDS
    )
    assert result.error is None and [e.field for e in result.extractions] == ["activity_pattern"]
    assert result.extractor.startswith("served-model+prompt:")
    call = messages.calls[0]
    assert call["model"] == "configured-model"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "Felis exemplaris" in call["messages"][0]["content"]
    refused, _ = fake_client("refusal", "")
    result = ClaudeExtractor(model="m", client=refused).extract(ARTICLE, NAMES, EXTRACTION_FIELDS)
    assert result.error and result.extractions == []


# -- reconciliation ---------------------------------------------------------------------------


def test_reconcile_precedence_conflicts_and_guards():
    cands = [
        Candidate(
            field="traits.activity_pattern",
            value="cathemeral",
            rank=Rank.DB_MEASURED,
            provenance=prov("db"),
        ),
        Candidate(
            field="traits.activity_pattern",
            value="nocturnal",
            rank=Rank.EXTRACTED,
            provenance=prov("wiki", "extracted", 0.6, "CC-BY-SA-4.0"),
        ),
        Candidate(
            field="traits.body_mass_g", value=12000, rank=Rank.DB_MEASURED, provenance=prov("db")
        ),
        Candidate(
            field="traits.body_mass_g", value=50000, rank=Rank.DB_IMPUTED, provenance=prov("db2")
        ),
        Candidate(
            field="traits.habitats",
            value=["chaparral"],
            rank=Rank.EXTRACTED,
            provenance=prov("wiki", "extracted", 0.5, "CC-BY-SA-4.0"),
        ),
        Candidate(
            field="traits.habitats",
            value=["chaparral"],
            rank=Rank.EXTRACTED,
            provenance=prov("other-wiki", "extracted", 0.5, "CC-BY-SA-4.0"),
        ),
        Candidate(
            field="policy.default_tier",
            value=0,
            rank=Rank.EXTRACTED,
            provenance=prov("wiki", "extracted"),
        ),
    ]
    rec = reconcile(cands)
    assert rec.values["traits.activity_pattern"] == "cathemeral"  # curated DB beats extraction
    assert {c.field: c.kind for c in rec.conflicts} == {
        "traits.activity_pattern": "categorical",
        "traits.body_mass_g": "numeric",
    }
    assert rec.provenance["traits.habitats"].confidence > 0.5  # two sources agree
    assert "policy.default_tier" not in rec.values
    assert any("refused policy.default_tier" in n for n in rec.notes)
    assert "CC-BY-SA-4.0" in rec.licenses and rec.open_variant is False
    assert rec.review_queue[0] == "traits.activity_pattern"  # conflicted and high impact
    locked = reconcile(cands, locked={"traits.activity_pattern": "crepuscular"})
    assert locked.values["traits.activity_pattern"] == "crepuscular"


# -- drafts, locks and promotion ----------------------------------------------------------------


def identity() -> TaxonIdentity:
    return TaxonIdentity(
        query_name="Felis exemplaris",
        taxon_id="felis-exemplaris",
        accepted_name="Felis exemplaris",
        rank="species",
        kingdom="Animalia",
        **{"class": "Mammalia"},
        ids={"gbif": "10", "inaturalist": "501"},
        verified={"gbif": True, "inaturalist": True},
        wikidata="Q1",
        common_name="Example Cat",
        iucn_category="EN",
    )


def test_draft_lock_and_promote(tmp_path):
    cands = [
        Candidate(
            field="traits.activity_pattern",
            value="nocturnal",
            rank=Rank.DB_MEASURED,
            provenance=prov("db"),
        ),
        Candidate(
            field="traits.home_range_km2",
            value=[2.0, 9.0],
            rank=Rank.EXTRACTED,
            provenance=prov("wiki", "extracted", 0.5, "CC-BY-SA-4.0"),
        ),
    ]
    doc = build_draft(identity(), reconcile(cands), now=NOW)
    assert doc["extends"] == ["group/mammals"] and doc["status"] == "draft"
    assert "policy" not in doc
    assert doc["crosswalk"] == {"gbif": "10", "inaturalist": "501", "wikidata": "Q1"}
    assert any("status hint" in n for n in doc["generation"]["notes"])
    reviewed = promote(
        doc,
        reviewer="reviewer-a",
        lock=["traits.activity_pattern"],
        reject=["traits.home_range_km2"],
        today=NOW,
    )
    assert reviewed["status"] == "reviewed"
    assert reviewed["locked"] == ["traits.activity_pattern", "traits.home_range_km2"]
    assert "home_range_km2" not in reviewed["traits"]
    assert reviewed["provenance"]["traits.activity_pattern"]["review"] == "accepted"
    with pytest.raises(ValueError):
        promote(doc, reviewer=" ", lock=[])
    with pytest.raises(ValueError):
        promote(doc, reviewer="r", lock=["traits.nonexistent"])
    # Regeneration with different evidence keeps locked values and absences.
    regenerated = build_draft(
        identity(),
        reconcile(
            [
                Candidate(
                    field="traits.activity_pattern",
                    value="diurnal",
                    rank=Rank.DB_MEASURED,
                    provenance=prov("db"),
                ),
                *cands[1:],
            ],
            locked={"traits.activity_pattern": "nocturnal", "traits.home_range_km2": None},
        ),
        existing=reviewed,
        now=NOW,
    )
    assert regenerated["traits"]["activity_pattern"] == "nocturnal"
    assert "home_range_km2" not in regenerated["traits"]
    assert regenerated["status"] == "reviewed"  # nothing unlocked changed


def test_library_loads_drafts_and_curated_profiles_win(tmp_path):
    doc = build_draft(identity(), reconcile([]), now=NOW)
    write_draft(doc, tmp_path)
    curated = build_draft(
        identity().model_copy(
            update={"taxon_id": "puma-concolor", "accepted_name": "Puma concolor"}
        ),
        reconcile([]),
        now=NOW,
    )
    write_draft(curated, tmp_path)
    lib = ProfileLibrary(extra_dirs=(tmp_path,))
    assert lib.resolve("felis-exemplaris").methods.headline == "wildlife_viewing"
    assert lib.path("puma-concolor").parent.name == "species"  # hand-curated profile wins
    assert [p.name for p in lib.shadowed] == ["puma-concolor.yaml"]


# -- occurrence-derived priors ------------------------------------------------------------------


def test_seasonality_summary():
    flat = {w: 0.2 for w in range(1, 53)}
    assert seasonality(flat)["pattern"] == "year_round"
    visitor = {w: (0.5 if 15 <= w <= 20 else 0.0) for w in range(1, 53)}
    s = seasonality(visitor)
    assert s["pattern"] == "seasonal_visitor" and s["peak_weeks"] == list(range(15, 21))
    assert seasonality({1: 0.1}) is None


def test_solar_elevation():
    noon = solar_elevation(32.85, -117.27, datetime(2026, 6, 21, 19, 50, tzinfo=UTC))
    midnight = solar_elevation(32.85, -117.27, datetime(2026, 6, 21, 7, 50, tzinfo=UTC))
    assert 75 < noon < 85 and midnight < -30


@pytest.fixture(scope="module")
def synthetic_store():
    world = SyntheticWorld()
    store = ObservationStore()
    store.add(world.generate())
    build_baseline(store.conn, region_id="socal", bbox=world.bbox)
    return world, store


def test_occurrence_priors_from_baseline(synthetic_store):
    world, store = synthetic_store
    vernal = seasonality_candidates(store.conn, "socal", ["no-such-alias", "vernalis-litoralis"])
    value = vernal[0].value
    assert value["pattern"] in ("seasonal_peak", "seasonal_visitor")
    assert 17 <= sum(value["peak_weeks"]) / len(value["peak_weeks"]) <= 23  # true peak: week 20
    assert vernal[0].provenance.method == "computed"
    common = seasonality_candidates(store.conn, "socal", "commonus-ubiquitus")
    assert common[0].value["pattern"] == "year_round"
    # Synthetic visits are all at ~9am local: diurnal, and not more nocturnal than the group.
    diel = diel_candidates(store.conn, "commonus-ubiquitus", world.bbox)
    assert diel[0].value["pattern"] == "diurnal" and diel[0].value["observer_biased"]


# -- the whole pipeline, offline ----------------------------------------------------------------


class FakeResolver(IdentityResolver):
    def __init__(self):
        pass

    def resolve_many(self, names):
        return [
            identity().model_copy(update={"wikipedia_title": "Example cat"})
            if n == "Felis exemplaris"
            else TaxonIdentity(query_name=n, notes=["no match"])
            for n in names
        ]


class FakeWiki:
    def fetch(self, title):
        assert title == "Example cat"
        return ARTICLE


def test_generator_end_to_end(tmp_path, synthetic_store):
    _, store = synthetic_store
    extractor = StaticExtractor(
        {
            "Example cat": {
                "activity_pattern": {
                    "stated": True,
                    "value": "nocturnal",
                    "evidence": "It is mostly nocturnal",
                }
            }
        }
    )
    gen = Generator(
        resolver=FakeResolver(),
        traits=TetrapodTraits(FIXTURES / "tetrapodtraits_sample.csv"),
        store=store.conn,
        region_id="socal",
        wiki=FakeWiki(),
        extractor=extractor,
        out_dir=tmp_path / "generated",
        now=NOW,
    )
    reports = gen.run(["Felis exemplaris", "Nonexistus imaginarius"])
    assert reports[1].path is None and reports[1].notes == ["no match"]
    doc = load_doc(reports[0].path)
    assert doc["traits"]["activity_pattern"] == "nocturnal"
    # Curated DB value and the verified extraction agree → higher confidence.
    assert doc["provenance"]["traits.activity_pattern"]["confidence"] > 0.9
    # License taint follows the source of each published value (here the CC BY database).
    assert doc["generation"]["licenses"] == ["CC-BY-4.0"]
    audit = json.loads((tmp_path / "extractions" / "felis-exemplaris.json").read_text())
    assert audit["checks"][0]["accepted"] is True
    assert yaml.safe_load(reports[0].path.read_text())["id"] == "felis-exemplaris"
    assert store.conn.execute("SELECT count(*) FROM taxon_identity").fetchone()[0] >= 1
