import json

from wildlife_scanner.baseline import build_baseline
from wildlife_scanner.policy.audit import audit_tiers, summarize
from wildlife_scanner.policy.statuses import StaticStatusProvider, StatusLookup, build_tier_table
from wildlife_scanner.storage import ObservationStore
from wildlife_scanner.synthetic import SyntheticWorld


def store_with_tiers():
    world = SyntheticWorld()
    store = ObservationStore()
    store.add(world.generate())
    build_baseline(store.conn, region_id="socal", bbox=world.bbox)
    build_tier_table(
        store.conn, region_id="socal", scopes=["global"], providers=[StaticStatusProvider()]
    )
    return store


def test_clean_store_has_no_high_findings():
    store = store_with_tiers()
    findings = audit_tiers(store.conn, "socal")
    assert not [f for f in findings if f.severity == "high"]


def test_audit_flags_under_protected_taxa():
    store = store_with_tiers()
    conn = store.conn
    # Wikidata says Raritas orientalis is endangered, but its tier is OPEN.
    conn.execute(
        "CREATE TABLE taxon_identity (query_name VARCHAR PRIMARY KEY, taxon_id VARCHAR, "
        "record JSON, fetched_at TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO taxon_identity VALUES ('Raritas orientalis', 'raritas-orientalis', ?, NULL)",
        [json.dumps({"taxon_id": "raritas-orientalis", "iucn_category": "EN", "synonyms": []})],
    )
    # iNaturalist reported an in-scope status without an IUCN equivalent, plus a status elsewhere.
    lookup = StatusLookup(
        source="inaturalist",
        unmapped=("State list: Endangered (us-ca)", "Local list: Watch (us-ca)"),
        ignored=("Oregon: Endangered @ place 10",),
    )
    conn.execute(
        "INSERT INTO status_cache VALUES ('inaturalist', 'commonus-ubiquitus', ?, now())",
        [lookup.model_dump_json()],
    )
    findings = audit_tiers(
        conn, "socal", curated_taxon_ids=["oldgenus-litoralis", "absentus-species"]
    )
    by_check = {(f.check, f.taxon_id): f.severity for f in findings}
    assert by_check[("open_but_threatened_on_wikidata", "raritas-orientalis")] == "high"
    unmapped = sorted(f.severity for f in findings if f.check == "open_with_unmapped_status")
    assert unmapped == ["high", "medium"]  # threat words make it high
    assert by_check[("threatened_elsewhere", "commonus-ubiquitus")] == "medium"
    # A curated entry under an old genus that matches nothing, while vernalis-litoralis exists.
    assert by_check[("curated_status_unmatched", "oldgenus-litoralis")] == "high"
    assert by_check[("curated_status_absent", "absentus-species")] == "info"
    assert findings[0].severity == "high"
    assert summarize(findings)["counts"]["high"] == 3


def test_curated_status_reaches_a_renamed_taxon_through_its_resolved_name(tmp_path):
    """A curated status keyed by an older name (Euphydryas → Occidryas) applies once that name
    is resolved; a resolved name with no synonym in the region is merely absent."""
    from wildlife_scanner.policy.statuses import RegionStatusFile

    store = store_with_tiers()
    conn = store.conn
    conn.execute(
        "CREATE TABLE taxon_identity (query_name VARCHAR PRIMARY KEY, taxon_id VARCHAR, "
        "record JSON, fetched_at TIMESTAMP)"
    )
    resolved = {
        # The curated name, resolved, lists the region's name as a synonym.
        "Oldgenus litoralis": {
            "taxon_id": "oldgenus-litoralis",
            "accepted_name": "Oldgenus litoralis",
            "synonyms": ["Vernalis litoralis"],
        },
        # A curated taxon that lives elsewhere: resolved, but nothing of it here.
        "Faraway species": {"taxon_id": "faraway-species", "synonyms": []},
    }
    for name, rec in resolved.items():
        conn.execute(
            "INSERT INTO taxon_identity VALUES (?, ?, ?, NULL)",
            [name, rec["taxon_id"], json.dumps(rec)],
        )
    path = tmp_path / "statuses.yaml"
    path.write_text(
        "statuses:\n  - {taxon_id: oldgenus-litoralis, authority: ESA, code: E, scope: global}\n",
        encoding="utf-8",
    )
    curated = RegionStatusFile(path)
    decisions = build_tier_table(
        conn,
        region_id="socal",
        scopes=["global"],
        providers=[StaticStatusProvider(), curated],
    )
    assert decisions["vernalis-litoralis"].tier.name == "COARSE"  # the status reached it
    findings = audit_tiers(
        conn, "socal", curated_taxon_ids=["oldgenus-litoralis", "faraway-species"]
    )
    by_check = {(f.check, f.taxon_id): f.severity for f in findings}
    assert ("curated_status_unmatched", "oldgenus-litoralis") not in by_check
    assert by_check[("curated_status_absent", "faraway-species")] == "info"
