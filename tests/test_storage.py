from datetime import UTC, datetime

import duckdb
import h3

from wildlife_scanner.connectors.gbif_snapshot import SnapshotReport, snapshot_observations
from wildlife_scanner.core import (
    Observation,
    Outcome,
    TaxonRef,
    TaxonScheme,
    TimeWindow,
    parse_license,
)
from wildlife_scanner.core.ids import hash_identifier
from wildlife_scanner.core.taxa import species_id_from_name, target_group
from wildlife_scanner.core.time import Precision
from wildlife_scanner.storage import ObservationStore, observation_row
from wildlife_scanner.storage.observations import COLUMNS, dedupe_key


def make_obs(obs_id="src:1", lat=32.85, lon=-117.27, uncertainty=20.0, **kw):
    base = dict(
        obs_id=obs_id,
        source_id=obs_id.split(":")[0],
        source_record_id=obs_id.split(":")[1],
        taxon=TaxonRef(scheme=TaxonScheme.NAME, id="x", name="Toxostoma redivivum", rank="species"),
        footprint={"kind": "point", "lat": lat, "lon": lon, "uncertainty_m": uncertainty},
        time=TimeWindow.instant(datetime(2025, 5, 14, 17, 0, tzinfo=UTC), Precision.MINUTE),
        outcome=Outcome.PRESENCE_ONLY,
        license=parse_license("cc-by"),
        extras={"group": "birds", "observer_hash": "abc"},
    )
    base.update(kw)
    return Observation(**base)


def row_dict(obs):
    return dict(zip(COLUMNS, observation_row(obs), strict=True))


def test_row_cells_are_nested_parents():
    row = row_dict(make_obs())
    finest = row["cell_r8"]
    for r in (3, 4, 5, 6, 7):
        assert row[f"cell_r{r}"] == h3.cell_to_parent(finest, r)


def test_imprecise_records_only_get_coarse_cells():
    row = row_dict(make_obs(uncertainty=30_000))
    assert row["cell_r3"] is not None
    assert all(row[f"cell_r{r}"] is None for r in (4, 5, 6, 7, 8))
    assert row["visit_key"] is None  # too imprecise to define a visit


def test_row_time_fields_and_visit_key():
    row = row_dict(make_obs())
    assert str(row["local_date"]) == "2025-05-14"
    assert row["week"] == 20
    assert row["visit_key"] == f"abc|2025-05-14|{row['cell_r7']}"
    assert row["taxon_id"] == "toxostoma-redivivum"
    assert row["group_id"] == "birds"


def test_month_precision_has_no_week():
    month = TimeWindow(
        start=datetime(2025, 5, 1, 8, tzinfo=UTC),
        end=datetime(2025, 6, 1, 8, tzinfo=UTC),
        precision=Precision.MONTH,
    )
    row = row_dict(make_obs(time=month))
    assert row["week"] is None and row["visit_key"] is None


def test_dedupe_key_links_gbif_copies_of_inat_records():
    inat = make_obs("inaturalist:101")
    gbif = make_obs(
        "gbif:4000",
        extras={"occurrence_id": "https://www.inaturalist.org/observations/101", "group": "birds"},
    )
    assert dedupe_key(inat) == dedupe_key(gbif) == "inat:101"
    store = ObservationStore()
    assert store.add([inat, gbif]) == 1
    assert store.count() == 1
    store.add([make_obs("other:1"), make_obs("other:1")])
    assert store.count() == 2


def test_species_resolution_and_groups():
    assert species_id_from_name("Puma concolor couguar", "subspecies") == "puma-concolor"
    assert species_id_from_name("Puma", "genus") is None
    assert species_id_from_name("Puma concolor", None) == "puma-concolor"
    assert species_id_from_name("sp.", "species") is None
    assert target_group("Animalia", "Chordata", "Aves") == "birds"
    assert target_group("Animalia", "Chordata", "Elasmobranchii") == "fishes"
    assert target_group(inat_iconic="Mollusca") == "mollusks"
    assert target_group(inat_iconic="Animalia") == "other_animals"
    assert target_group("Plantae") == "plants"


def test_hash_identifier(monkeypatch):
    a = hash_identifier(["Jane Doe", "John Roe"])
    assert a == hash_identifier(["John Roe", "Jane Doe"])  # order independent
    assert hash_identifier("") is None and hash_identifier([]) is None
    monkeypatch.setenv("WILDLIFE_SCANNER_HASH_SALT", "deployment-2")
    assert hash_identifier(["Jane Doe", "John Roe"]) != a


def _write_snapshot(path):
    """A tiny Parquet file with the real snapshot column names/types and synthetic values."""
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                ('1', 'ds-1', 'occ-1', 'Animalia', 'Chordata', 'Aves', 'Toxostoma redivivum',
                 'SPECIES', 'Toxostoma redivivum (Gambel, 1845)', 'PRESENT', 1::INTEGER,
                 32.85::DOUBLE, -117.27::DOUBLE, 30.0::DOUBLE,
                 TIMESTAMP '2021-03-03 00:00:00', 3::INTEGER, 3::INTEGER, 2021::INTEGER,
                 '100', '100', 'HUMAN_OBSERVATION', 'CC_BY_4_0', ['obsr1'], ['StillImage'],
                 ['COORDINATE_ROUNDED']),
                ('2', 'ds-1', 'occ-2', 'Animalia', 'Chordata', 'Aves', NULL,
                 'GENUS', 'Toxostoma', 'PRESENT', NULL,
                 32.90::DOUBLE, -117.20::DOUBLE, NULL,
                 TIMESTAMP '1953-07-01 00:00:00', NULL, 7::INTEGER, 1953::INTEGER,
                 '200', NULL, 'PRESERVED_SPECIMEN', 'CC0_1_0', [], [], []),
                ('3', 'ds-2', 'occ-3', 'Animalia', 'Chordata', 'Aves', 'Sayornis saya',
                 'SPECIES', 'Sayornis saya', 'PRESENT', NULL,
                 45.0::DOUBLE, -100.0::DOUBLE, NULL,
                 TIMESTAMP '2021-10-04 00:00:00', 4::INTEGER, 10::INTEGER, 2021::INTEGER,
                 '300', '300', 'HUMAN_OBSERVATION', 'CC_BY_4_0', ['obsr2'], [], [])
            ) t(gbifid, datasetkey, occurrenceid, kingdom, phylum, class, species, taxonrank,
                scientificname, occurrencestatus, individualcount, decimallatitude,
                decimallongitude, coordinateuncertaintyinmeters, eventdate, day, month, year,
                taxonkey, specieskey, basisofrecord, license, recordedby, mediatype, issue)
        ) TO '{path}' (FORMAT parquet)
        """
    )


def test_snapshot_ingestion(tmp_path):
    path = tmp_path / "part.parquet"
    _write_snapshot(path)
    report = SnapshotReport()
    obs = list(snapshot_observations(str(path), (-121.0, 32.4, -114.1, 35.8), report))
    assert report.rows_read == 2 and report.parsed == 2  # out-of-bbox row filtered in DuckDB
    by_id = {o.source_record_id: o for o in obs}
    first, second = by_id["1"], by_id["2"]
    assert first.time.precision is Precision.DAY
    assert first.evidence_grade.value == "C1"  # has media
    assert first.extras["observer_hash"] == hash_identifier(["obsr1"])
    assert first.extras["group"] == "birds"
    assert first.extras["issues"] == ["COORDINATE_ROUNDED"]
    assert second.time.precision is Precision.MONTH  # day missing → month window, not "July 1"
    store = ObservationStore()
    store.add(obs)
    taxa = store.conn.execute("SELECT taxon_id FROM observations ORDER BY obs_id").fetchall()
    assert taxa == [("toxostoma-redivivum",), (None,)]  # genus-level record: effort only
