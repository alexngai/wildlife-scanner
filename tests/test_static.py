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
    coarse = json.loads((region_dir / index["maps"]["raritas-orientalis"]).read_text())
    assert coarse["format"] == 2 and len(coarse["segments"]) == 1
    seg = coarse["segments"][0]
    assert (
        seg["tier"] == 2 and seg["granularity"] == "month" and seg["periods"] == list(range(1, 13))
    )
    finest = rule_for(2).h3_res
    assert all(h3.get_resolution(c) <= finest for c in seg["cells"])
    assert seg["ref"]["resolution"] is None and set(seg["ref"]["p"]) == {"region"}
    # OPEN: weekly maps; integer probabilities, one confidence code per week.
    open_map = json.loads((region_dir / index["maps"]["vernalis-litoralis"]).read_text())
    seg = open_map["segments"][0]
    assert seg["granularity"] == "week" and seg["periods"] == list(range(1, 53))
    assert len(seg["p"]) == len(seg["cells"]) and all(len(row) == 52 for row in seg["p"])
    assert all(isinstance(v, int) for row in seg["p"] for v in row if v is not None)
    assert all(len(c) == 52 and set(c) <= set("ilmh-") for c in seg["confidence"])
    # Lift and seasonal index are derivable: p / reference p, and p / the row's mean.
    parent = h3.cell_to_parent(seg["cells"][0], seg["ref"]["resolution"])
    assert parent in seg["ref"]["p"]
    # Places from the region pack, weekly lists without life-list items.
    place = index["places"]["la-jolla-cove"]
    doc = json.loads((region_dir / place["file"]).read_text())
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


def test_matrix_maps_equal_the_policy_filtered_maps(store):  # noqa: F811
    """The vectorized matrices carry exactly what species_maps (EgressFilter) returns."""
    from wildlife_radar.policy.statuses import TierService
    from wildlife_radar.serving.queries import BaselineQueries

    st, region = store
    q = BaselineQueries(st.conn, region, TierService(st.conn, "socal"))
    codes = {"insufficient": "i", "low": "l", "medium": "m", "high": "h"}
    for taxon_id in ("vernalis-litoralis", "raritas-orientalis"):
        segments = q.species_matrix(taxon_id, 2026)
        assert len(segments) == 1
        seg = segments[0]
        maps = q.species_maps(taxon_id, 2026)
        assert len(maps) == len(seg.periods)
        assert seg.granularity == ("month" if taxon_id == "raritas-orientalis" else "week")
        for m in maps:
            label = m.date.month if seg.granularity == "month" else m.date.isocalendar().week
            i = seg.periods.index(label)
            got = {
                c: (seg.p[j][i], seg.confidence[j][i])
                for j, c in enumerate(seg.cells)
                if seg.p[j][i] is not None
            }
            want = {c.cell: (c.p, codes[c.confidence.value]) for c in m.cells}
            assert got.keys() == want.keys()
            for c, (p, conf) in want.items():
                assert abs(got[c][0] - p) < 2e-6 and got[c][1] == conf
            assert all(h3.get_resolution(c) == seg.resolution for c in seg.cells)
    assert q.species_matrix("secretus-maximus", 2026) == []  # withheld: nothing at all
