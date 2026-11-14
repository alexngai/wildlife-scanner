"""The global reference store and the shared raw iNaturalist records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import duckdb

from wildlife_radar.connectors.inaturalist_taxa import InatTaxonStatusProvider, RecordCache
from wildlife_radar.policy.statuses import TaxonInfo
from wildlife_radar.profilegen.identity import IDENTITY_SCHEMA
from wildlife_radar.storage.refstore import RefStore

T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _identity(conn, name, taxon_id, when):
    conn.execute(IDENTITY_SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO taxon_identity VALUES (?, ?, ?, ?)",
        [name, taxon_id, f'{{"name": "{name}"}}', when.replace(tzinfo=None)],
    )


def test_regions_share_identities_and_newest_wins(tmp_path):
    socal, monterey = duckdb.connect(), duckdb.connect()
    ref_a = RefStore(tmp_path / "ref", "socal")
    ref_b = RefStore(tmp_path / "ref", "montereybay")
    _identity(socal, "Enhydra lutris", "enhydra-lutris", T0)
    _identity(socal, "Old name", "old", T0 - timedelta(days=400))
    assert ref_a.export_from(socal, "taxon_identity", T0) is not None  # only the new row
    assert ref_a.export_from(socal, "taxon_identity", T0 + timedelta(days=1)) is None
    assert ref_b.import_into(monterey, "taxon_identity") == 1
    assert monterey.execute("SELECT taxon_id FROM taxon_identity").fetchall() == [
        ("enhydra-lutris",)
    ]
    # Monterey re-resolves the name later; socal picks the newer row up, never the reverse.
    _identity(monterey, "Enhydra lutris", "enhydra-lutris-v2", T0 + timedelta(days=5))
    ref_b.export_from(monterey, "taxon_identity", T0 + timedelta(days=5))
    assert ref_a.import_into(socal, "taxon_identity") == 1
    assert socal.execute(
        "SELECT taxon_id FROM taxon_identity WHERE query_name = 'Enhydra lutris'"
    ).fetchone() == ("enhydra-lutris-v2",)
    assert ref_b.import_into(monterey, "taxon_identity") == 0  # nothing newer than its own
    assert {p.name.split("-")[1] for p in ref_a.parts("taxon_identity")} == {
        "socal",
        "montereybay",
    }


# A taxon listed only in Washington (iNaturalist place 46) and globally Least Concern.
RECORD = {
    "id": 4242,
    "conservation_statuses": [
        {
            "place": {"id": 46, "ancestor_place_ids": [97394, 1, 46]},
            "iucn": 40,
            "authority": "Washington Department of Fish and Wildlife",
            "status": "endangered",
        },
        {"place": None, "iucn": 10, "authority": "IUCN Red List", "status": "LC"},
    ],
}


class _Counting(InatTaxonStatusProvider):
    calls = 0

    def fetch_records(self, taxa):
        type(self).calls += 1
        return {t.taxon_id: RECORD for t in taxa}


def test_raw_records_are_shared_but_parsed_per_region():
    conn = duckdb.connect()  # stands in for the shared records (imported via the ref store)
    taxon = [TaxonInfo(taxon_id="exampleus-rarus", scientific_name="Exampleus rarus")]
    california = _Counting(
        {"1": "us", "14": "us-ca"}, innermost_place="14", records=RecordCache(conn, now=T0)
    )
    washington = _Counting(
        {"1": "us", "46": "us-wa"}, innermost_place="46", records=RecordCache(conn, now=T0)
    )
    ca = california.lookup_many(taxon)["exampleus-rarus"]
    wa = washington.lookup_many(taxon)["exampleus-rarus"]
    assert _Counting.calls == 1  # the second region reused the raw record
    assert [s.code for s in ca.statuses] == ["LC"] and ca.ignored  # Washington list ignored
    assert sorted(s.code for s in wa.statuses) == ["EN", "LC"]  # ... but it applies there
    # Stale raw records are fetched again.
    later = _Counting({"1": "us"}, records=RecordCache(conn, now=T0 + timedelta(days=91)))
    later.lookup_many(taxon)
    assert _Counting.calls == 2
