"""Static products: policy-filtered by construction, content-addressed, synced with versions."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import h3
from test_publish import NOW, store  # noqa: F401  (fixture)

from wildlife_scanner.pipeline.publish import publish_bundle
from wildlife_scanner.pipeline.static import before_swap, in_use, referenced
from wildlife_scanner.pipeline.sync import prune_local, push_publish
from wildlife_scanner.policy.tiers import rule_for
from wildlife_scanner.storage.objects import LocalStore


def _publish(st, region, root, now=NOW):
    return publish_bundle(st.conn, region, root, now=now, before_swap=before_swap(region, now))


def _index(result):
    return json.loads((result.path / "static" / "index.json").read_text(encoding="utf-8"))


def _taxa(result):
    return json.loads((result.path / "static" / "taxa.json").read_text(encoding="utf-8"))


def _used(result):
    return referenced(_index(result), _taxa(result))


def _shared_files(region_dir, used):
    shared = (p.relative_to(region_dir).as_posix() for p in (region_dir / "static").rglob("*.json"))
    return sorted(rel for rel in shared if in_use(rel, used))


def _photo(pid, license_code):
    return {
        "photo": {
            "id": pid,
            "license_code": license_code,
            "attribution": f"(c) someone {pid}",
            "url": f"https://inaturalist-open-data.s3.amazonaws.com/photos/{pid}/square.jpg",
        }
    }


def test_static_products_follow_policy(store, tmp_path):  # noqa: F811
    from wildlife_scanner.connectors.inaturalist_taxa import RECORDS_SCHEMA

    st, region = store
    st.conn.execute(RECORDS_SCHEMA)
    records = {
        # All rights reserved first, then CC BY: the open one is chosen.
        "vernalis-litoralis": [_photo(11, None), _photo(12, "cc-by"), _photo(13, "cc0")],
        "raritas-orientalis": [_photo(21, "cc-by-nd")],  # no open licence: no photo
        "secretus-maximus": [_photo(31, "cc0")],  # withheld: never published
    }
    for taxon_id, photos in records.items():
        st.conn.execute(
            "INSERT INTO inat_taxon_records VALUES (?, '1', ?, now())",
            [taxon_id, json.dumps({"id": 1, "taxon_photos": photos})],
        )
    result = _publish(st, region, tmp_path)
    index = _index(result)
    region_dir = tmp_path / "region=socal"
    taxa = _taxa(result)
    by_id = {t["id"]: t for t in taxa}
    assert "vernalis-litoralis" in by_id and "secretus-maximus" not in by_id
    assert index["format"] == 4 and "maps" not in index  # map paths are in taxa.json
    maps = {t["id"]: t["map"] for t in taxa if "map" in t}
    assert "secretus-maximus" not in maps
    # Photos: the first openly licensed one, by id; URLs from the index's templates.
    photo = by_id["vernalis-litoralis"]["photo"]
    assert photo == {"id": 12, "ext": "jpg", "license": "cc-by", "attribution": "(c) someone 12"}
    urls = index["photos"]
    fill = {"id": photo["id"], "ext": photo["ext"]}
    assert urls["image"].format(size=urls["sizes"]["thumb"], **fill) == (
        "https://inaturalist-open-data.s3.amazonaws.com/photos/12/square.jpg"
    )
    assert urls["image"].format(size=urls["sizes"]["medium"], **fill).endswith("/12/small.jpg")
    assert urls["page"].format(**fill) == "https://www.inaturalist.org/photos/12"
    assert "photo" not in by_id["raritas-orientalis"]
    # Season summary: OPEN taxa only (from the published regional values), 0–9 per week.
    seas = by_id["vernalis-litoralis"]["season"]
    assert len(seas) == 52 and max(v for v in seas if v is not None) == 9
    assert all(v is None or 0 <= v <= 9 for v in seas)
    assert "season" not in by_id["raritas-orientalis"]  # COARSE: monthly, no ribbon
    # Withheld taxa appear in no file at all.
    files = list(region_dir.rglob("static/**/*.json"))
    assert len(files) >= 9  # index, search index, maps and place lists
    for path in files:
        assert "secretus" not in path.read_text(encoding="utf-8").lower(), path
    # COARSE (IUCN EN): monthly maps at the landscape resolution only.
    coarse = json.loads((region_dir / maps["raritas-orientalis"]).read_text())
    assert coarse["format"] == 4 and len(coarse["segments"]) == 1
    seg = coarse["segments"][0]
    assert (
        seg["tier"] == 2 and seg["granularity"] == "month" and seg["periods"] == list(range(1, 13))
    )
    finest = rule_for(2).h3_res
    assert all(h3.get_resolution(c) <= finest for c in seg["cells"])
    assert seg["ref"]["resolution"] is None and set(seg["ref"]["p"]) == {"region"}
    # OPEN: weekly maps; integer probabilities, one confidence code per week.
    open_map = json.loads((region_dir / maps["vernalis-litoralis"]).read_text())
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
    assert len(doc["weeks"]) == 52 and doc["weeks"][0].endswith("/w01.json")
    weeks = [json.loads((region_dir / path).read_text()) for path in doc["weeks"]]
    assert [w["week"] for w in weeks] == list(range(1, 53)) and weeks[0]["format"] == 4
    items = [
        row
        for w in weeks
        for lists in w["groups"].values()
        for key, rows in lists.items()
        for row in rows
    ]
    assert items and all(len(r) == len(doc["item_fields"]) for r in items)
    assert all(r[0] in doc["taxa"] for r in items)  # names once, in the taxa table
    assert all(
        set(lists) <= {"most_likely", "special_here", "peaking_now"}  # no life-list items
        for w in weeks
        for lists in w["groups"].values()
    )
    assert set(doc["groups"]) >= {g for w in weeks for g in w["groups"]}
    # The manifest records what was built.
    manifest = json.loads((result.path / "manifest.json").read_text())
    assert manifest["static"]["taxa"] == len(taxa)


def test_unchanged_inputs_reuse_files_and_push_only_new_ones(store, tmp_path):  # noqa: F811
    st, region = store
    bucket = LocalStore(tmp_path / "bucket")
    first = _publish(st, region, tmp_path / "publish")
    region_dir = tmp_path / "publish" / "region=socal"
    pushed = push_publish(tmp_path / "publish", bucket, "socal")
    shared = _shared_files(region_dir, _used(first))
    assert any("/w52.json" in rel for rel in shared)  # place week files count as used
    assert pushed["uploaded"] == len(shared) + len(list(first.path.rglob("*.*")))
    second = _publish(st, region, tmp_path / "publish", now=datetime(2026, 1, 21, tzinfo=UTC))
    stats = json.loads((second.path / "manifest.json").read_text())["static"]
    assert stats["maps"] == 0 and stats["maps_reused"] > 0 and stats["places"] == 0
    assert _used(second) == _used(first)
    again = push_publish(tmp_path / "publish", bucket, "socal")
    assert again["uploaded"] == len(list(second.path.rglob("*.*")))  # the version only
    # Pruning to one version keeps the shared files the current version still uses.
    prune_local(tmp_path / "publish", "socal", keep=1)
    push_publish(tmp_path / "publish", bucket, "socal", keep=1)
    for rel in _shared_files(region_dir, _used(second)):
        assert (region_dir / rel).exists()
        assert bucket.get_text(f"region=socal/{rel}") is not None
    assert len(_shared_files(region_dir, _used(second))) == len(shared)  # nothing lost


def test_display_common_names():
    from wildlife_scanner.core.names import display_common_name as d

    assert d("coyote brush") == "Coyote Brush"
    assert d("bird's-foot trefoil") == "Bird's-foot Trefoil"
    assert d("pride of madeira") == "Pride of Madeira"
    assert d("European Searocket") == "European Searocket"  # source casing kept
    assert d("Black-crowned Night-Heron") == "Black-crowned Night-Heron"
    assert d(None) is None and d("") == ""


def test_batched_maps_equal_single_maps(store):  # noqa: F811
    from wildlife_scanner.policy.statuses import TierService
    from wildlife_scanner.serving.queries import BaselineQueries

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
    from wildlife_scanner.policy.statuses import TierService
    from wildlife_scanner.serving.queries import BaselineQueries

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


def test_compact_photo_needs_a_url_that_fits_the_template():
    from wildlife_scanner.pipeline.static import compact_photo

    base = "https://inaturalist-open-data.s3.amazonaws.com/photos/41"
    full = {
        "license": "cc0",
        "attribution": "x",
        "source_url": "https://www.inaturalist.org/photos/41",
    }
    assert compact_photo({**full, "url": f"{base}/square.JPG"})["ext"] == "JPG"
    assert compact_photo({**full, "url": f"{base}/square."})["ext"] == ""  # old uploads
    assert compact_photo({**full, "url": f"{base}/medium.jpg"}) is None
    assert compact_photo({**full, "url": "https://elsewhere.example/41/square.jpg"}) is None
    other = {**full, "source_url": "https://www.inaturalist.org/photos/42"}
    assert compact_photo({**other, "url": f"{base}/square.jpg"}) is None


def test_push_refuses_a_format_the_live_app_cant_read(store, tmp_path):  # noqa: F811
    import httpx
    import pytest

    from wildlife_scanner.connectors.base import make_client

    st, region = store
    _publish(st, region, tmp_path / "publish")
    bucket = LocalStore(tmp_path / "bucket")

    def app(formats):
        def handler(request):
            if formats is None:
                return httpx.Response(503)
            return httpx.Response(200, json={"formats": formats})

        return make_client(transport=httpx.MockTransport(handler))

    url = "https://app.example/compat.json"
    with pytest.raises(RuntimeError, match=r"reads \[3\]"):
        push_publish(tmp_path / "publish", bucket, "socal", compat_url=url, client=app([3]))
    assert bucket.get_text("region=socal/CURRENT") is None  # nothing uploaded
    with pytest.raises(httpx.HTTPStatusError):  # can't ask: fail closed
        push_publish(tmp_path / "publish", bucket, "socal", compat_url=url, client=app(None))
    assert bucket.get_text("region=socal/CURRENT") is None
    out = push_publish(tmp_path / "publish", bucket, "socal", compat_url=url, client=app([4, 5]))
    assert out["app_formats"] == [4, 5] and bucket.get_text("region=socal/CURRENT")
