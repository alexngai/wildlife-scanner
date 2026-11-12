"""Static products: policy-filtered by construction, content-addressed, synced with versions."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import h3
from test_publish import NOW, store  # noqa: F401  (fixture)

from wildlife_radar.pipeline.publish import publish_bundle
from wildlife_radar.pipeline.static import before_swap, referenced
from wildlife_radar.pipeline.sync import prune_local, push_publish
from wildlife_radar.policy.tiers import rule_for
from wildlife_radar.storage.objects import LocalStore


def _publish(st, region, root, now=NOW):
    return publish_bundle(st.conn, region, root, now=now, before_swap=before_swap(region, now))


def _index(result):
    return json.loads((result.path / "static" / "index.json").read_text(encoding="utf-8"))


def test_static_products_follow_policy(store, tmp_path):  # noqa: F811
    st, region = store
    result = _publish(st, region, tmp_path)
    index = _index(result)
    region_dir = tmp_path / "region=socal"
    taxa = json.loads((result.path / "static" / "taxa.json").read_text(encoding="utf-8"))
    ids = {t["id"] for t in taxa}
    assert "vernalis-litoralis" in ids and "secretus-maximus" not in ids
    assert "secretus-maximus" not in index["maps"]
    # Withheld taxa appear in no file at all.
    files = list(region_dir.rglob("static/**/*.json"))
    assert len(files) >= 9  # index, search index, maps and place lists
    for path in files:
        assert "secretus" not in path.read_text(encoding="utf-8").lower(), path
    # COARSE (IUCN EN): monthly maps at the landscape resolution only.
    coarse = json.loads((region_dir / index["maps"]["raritas-orientalis"]["2026"]).read_text())
    assert len(coarse["periods"]) == 12
    finest = rule_for(2).h3_res
    for period in coarse["periods"]:
        assert period["tier"] == 2
        assert all(h3.get_resolution(c[0]) <= finest for c in period["cells"])
    # OPEN: weekly maps.
    open_map = json.loads((region_dir / index["maps"]["vernalis-litoralis"]["2026"]).read_text())
    assert len(open_map["periods"]) == 52 and open_map["periods"][0]["cells"]
    # Places from the region pack, weekly lists without life-list items.
    place = index["places"]["la-jolla-cove"]
    doc = json.loads((region_dir / place["files"]["2026"]).read_text())
    assert len(doc["weeks"]) == 52
    assert all("new_for_you" not in g for w in doc["weeks"] for g in w["groups"])
    # The manifest records what was built.
    manifest = json.loads((result.path / "manifest.json").read_text())
    assert manifest["static"]["taxa"] == len(taxa)


def test_unchanged_inputs_reuse_files_and_push_only_new_ones(store, tmp_path):  # noqa: F811
    st, region = store
    bucket = LocalStore(tmp_path / "bucket")
    first = _publish(st, region, tmp_path / "publish")
    pushed = push_publish(tmp_path / "publish", bucket, "socal")
    shared = len(referenced(_index(first)))
    assert pushed["uploaded"] == shared + len(list(first.path.rglob("*.*")))
    second = _publish(st, region, tmp_path / "publish", now=datetime(2026, 1, 21, tzinfo=UTC))
    stats = json.loads((second.path / "manifest.json").read_text())["static"]
    assert stats["maps"] == 0 and stats["maps_reused"] > 0 and stats["places"] == 0
    assert referenced(_index(second)) == referenced(_index(first))
    again = push_publish(tmp_path / "publish", bucket, "socal")
    assert again["uploaded"] == len(list(second.path.rglob("*.*")))  # the version only
    # Pruning to one version keeps the shared files the current version still uses.
    prune_local(tmp_path / "publish", "socal", keep=1)
    push_publish(tmp_path / "publish", bucket, "socal", keep=1)
    for rel in referenced(_index(second)):
        assert (tmp_path / "publish" / "region=socal" / rel).exists()
        assert bucket.get_text(f"region=socal/{rel}") is not None


def test_batched_maps_equal_single_maps(store):  # noqa: F811
    from wildlife_radar.policy.statuses import TierService
    from wildlife_radar.serving.queries import BaselineQueries

    st, region = store
    q = BaselineQueries(st.conn, region, TierService(st.conn, "socal"))
    for taxon_id in ("vernalis-litoralis", "raritas-orientalis"):
        maps = q.species_maps(taxon_id, 2026)
        assert maps
        for m in maps:
            one = q.species_map(taxon_id, m.date)
            assert one.time_window == m.time_window and one.taxon == m.taxon
            assert sorted(one.cells, key=lambda c: c.cell) == sorted(m.cells, key=lambda c: c.cell)
