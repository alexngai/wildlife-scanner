import json
import warnings
from datetime import UTC, datetime

import duckdb
import pytest

from wildlife_radar.baseline import build_baseline
from wildlife_radar.pipeline.publish import (
    CURRENT,
    PublishBlocked,
    current_bundle,
    publish_bundle,
)
from wildlife_radar.policy import ConservationStatus
from wildlife_radar.policy.statuses import StaticStatusProvider, StatusLookup, build_tier_table
from wildlife_radar.regions import load_region
from wildlife_radar.storage import ObservationStore
from wildlife_radar.synthetic import DEFAULT_SPECIES, SyntheticSpecies, SyntheticWorld

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from wildlife_radar.api import create_app  # noqa: E402

SECRET = SyntheticSpecies(name="Secretus maximus", centers=((32.86, -117.25, 6.0),), base=0.3)
NOW = datetime(2026, 1, 20, tzinfo=UTC)  # recent records exist before this date


@pytest.fixture()
def store():
    region = load_region("socal")
    world = SyntheticWorld(species=(*DEFAULT_SPECIES, SECRET))
    st = ObservationStore()
    st.add(world.generate())
    build_baseline(st.conn, region_id="socal", bbox=region.bbox)
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
    build_tier_table(st.conn, region_id="socal", scopes=region.scopes, providers=[provider])
    return st, region


def test_bundle_is_policy_filtered(store, tmp_path):
    st, region = store
    result = publish_bundle(st.conn, region, tmp_path, now=NOW)
    bundle = current_bundle(tmp_path / "region=socal")
    assert bundle == result.path / "serving.duckdb"
    conn = duckdb.connect(str(bundle), read_only=True)
    tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    assert "observations" not in tables and "status_cache" not in tables
    assert {"prior_hits", "tiers", "recent_effort", "recent_detections"} <= tables
    # Withheld: absent everywhere.
    for table in ("prior_taxa", "prior_hits", "tiers", "prior_mask"):
        n = conn.execute(
            f"SELECT count(*) FROM {table} WHERE taxon_id = 'secretus-maximus'"
        ).fetchone()[0]
        assert n == 0, table
    # COARSE: only context-level and regional statistics.
    levels = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT level FROM prior_hits WHERE taxon_id = 'raritas-orientalis'"
        ).fetchall()
    }
    assert levels and levels <= {2, 9}
    # OPEN keeps cell-level statistics.
    assert conn.execute(
        "SELECT count(*) FROM prior_hits WHERE taxon_id = 'vernalis-litoralis' AND level = 0"
    ).fetchone()[0]
    # Recent detections: OPEN taxa only, and nothing within the 24 h delay.
    recent = {
        r[0] for r in conn.execute("SELECT DISTINCT taxon_id FROM recent_detections").fetchall()
    }
    assert "raritas-orientalis" not in recent and "secretus-maximus" not in recent
    manifest = json.loads((result.path / "manifest.json").read_text())
    assert manifest["status"] == "complete" and manifest["rows"]["prior_hits"] > 0
    conn.close()


def test_audit_gate_blocks_and_records_overrides(store, tmp_path):
    st, region = store
    st.conn.execute(
        "CREATE TABLE taxon_identity (query_name VARCHAR PRIMARY KEY, taxon_id VARCHAR, "
        "record JSON, fetched_at TIMESTAMP)"
    )
    st.conn.execute(
        "INSERT INTO taxon_identity VALUES ('Vernalis litoralis', 'vernalis-litoralis', ?, NULL)",
        [json.dumps({"iucn_category": "CR", "synonyms": []})],
    )
    with pytest.raises(PublishBlocked):
        publish_bundle(st.conn, region, tmp_path, now=NOW)
    assert not (tmp_path / "region=socal" / CURRENT).exists()
    result = publish_bundle(st.conn, region, tmp_path, now=NOW, allow_findings=True)
    manifest = json.loads((result.path / "manifest.json").read_text())
    assert manifest["audit_overridden"] is True and manifest["audit"]["high"] == 1


def test_api_serves_bundles_and_follows_current(store, tmp_path):
    st, region = store
    publish_bundle(st.conn, region, tmp_path, now=NOW)
    client = TestClient(create_app(bundle_dir=tmp_path, region_id="socal", now=NOW))
    taxa = {t["taxon_id"] for t in client.get("/taxa").json()}
    assert "vernalis-litoralis" in taxa and "secretus-maximus" not in taxa
    first = client.app.state.services().db_path
    publish_bundle(st.conn, region, tmp_path, now=datetime(2026, 1, 21, tzinfo=UTC))
    assert client.get("/health").status_code == 200
    assert client.app.state.services().db_path != first  # switched to the new version
    r = client.get(
        "/species/vernalis-litoralis/forecast",
        params={"lat": 32.85, "lon": -117.27, "date": "2026-01-19"},
    )
    assert r.status_code == 200 and r.json()["level"] == 0
