"""Hourly factors: registry, candidate terms, fitting, gating and multipliers."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
from test_publish import NOW, store  # noqa: F401  (fixture)

from wildlife_scanner.conditions import factors, hourly, timed

LA_JOLLA = (32.867, -117.257)


def _hilo(start: datetime, days: int):
    return [
        (
            start + timedelta(hours=6 * i + 0.4 * (i // 4)),
            "H" if i % 2 == 0 else "L",
            2.0 if i % 2 == 0 else 0.0,
        )
        for i in range(days * 4 + 1)
    ]


def _world(prefer: dict[str, dict[str, float]], days=500, seed=3):
    """Hourly group effort with a taxon whose share depends on diel phase and tide stage."""
    start = datetime(2023, 1, 1, tzinfo=UTC)
    s = timed.HourSignals(*LA_JOLLA, _hilo(start - timedelta(days=1), days + 2))
    rng = random.Random(seed)
    taxon, effort = {}, {}
    for h in range(days * 24):
        t = start + timedelta(hours=h)
        local = (t.hour - 8) % 24
        n = rng.randint(5, 15) if 6 <= local <= 20 else rng.randint(0, 3)
        if not n:
            continue
        effort[t] = n
        share = 0.05
        for sig, levels in prefer.items():
            share *= levels.get(s.category(sig, t, []) or "", 1.0)
        taxon[t] = sum(rng.random() < min(share, 0.9) for _ in range(n))
    return s, taxon, effort


def _value(s):
    return lambda sig, t: s.value(sig, t, [])


def test_candidate_terms_from_group_defaults_and_profile():
    names = {t.signal for t in factors.hourly_terms("fishes")}
    assert names == {"astro.diel_phase", "astro.moonlight", "tide.stage"}
    assert "tide.stage" not in {t.signal for t in factors.hourly_terms("fishes", tides=False)}
    profile = SimpleNamespace(
        signals={
            "hours_after_sunset": SimpleNamespace(
                signal="astro.hours_since_sunset",
                shape="peak",
                strength="strong",
                hypothesis=True,
                role="availability",
                direction=None,
            ),
            "diel_activity": SimpleNamespace(
                signal="astro.sun_altitude_deg",
                shape=None,
                strength="strong",
                hypothesis=False,
                role="availability",
                direction=None,
            ),
            "sst": SimpleNamespace(
                signal="ocean.sst_c",
                shape="linear",
                strength="weak",
                hypothesis=True,
                role="presence",
                direction="+",
            ),
        }
    )
    terms = {t.signal: t for t in factors.hourly_terms("mammals", profile)}
    assert set(terms) == {"astro.diel_phase", "astro.moonlight", "astro.hours_since_sunset"}
    assert terms["astro.diel_phase"].name == "diel_activity"  # the profile's term replaces it
    assert terms["astro.hours_since_sunset"].shape == "categorical"
    assert all(f.scale in ("day", "hour") for f in factors.FACTORS.values())


def test_dawn_and_low_tide_preferences_are_found_and_gated():
    s, taxon, effort = _world({"astro.diel_phase": {"dawn": 4.0}, "tide.stage": {"low": 2.5}})
    terms = factors.hourly_terms("birds")
    fit = hourly.fit_hourly(
        taxon,
        effort,
        terms,
        _value(s),
        date(2024, 1, 1),
        offset_hours=s.offset,
        expectations={"astro.diel_phase": ("dusk",)},
        reps=60,
    )
    assert fit.passes and fit.model is not None, fit
    by = {t.signal: t for t in fit.scorecard}
    assert by["astro.diel_phase"].verdict == "supported" and by["astro.diel_phase"].peak == "dawn"
    assert "not dusk" in by["astro.diel_phase"].review  # profile said dusk: flagged
    assert by["tide.stage"].verdict == "supported" and by["tide.stage"].peak == "low"
    # Multipliers: dawn at low tide is the best hour; averaged over effort they are ~1.
    hours = sorted(effort)
    signals, ok = hourly.design(hours, terms, _value(s))
    m = hourly.multiplier(fit.model, fit.log_norm, signals)
    n = np.array([effort[h] for h in hours], dtype=float)
    assert abs(np.sum(n[ok] * m[ok]) / np.sum(n[ok]) - 1) < 0.02
    cats = {
        sig: [s.category(sig, h, []) for h in hours] for sig in ("astro.diel_phase", "tide.stage")
    }
    dawn_low = [
        i
        for i in range(len(hours))
        if cats["astro.diel_phase"][i] == "dawn" and cats["tide.stage"][i] == "low"
    ]
    day_high = [
        i
        for i in range(len(hours))
        if cats["astro.diel_phase"][i] == "day" and cats["tide.stage"][i] == "high"
    ]
    assert np.mean(m[dawn_low]) > 4 * np.mean(m[day_high])


def test_no_pattern_fails_the_gate():
    s, taxon, effort = _world({})
    fit = hourly.fit_hourly(
        taxon,
        effort,
        factors.hourly_terms("birds"),
        _value(s),
        date(2024, 1, 1),
        offset_hours=s.offset,
        reps=60,
    )
    assert not fit.passes and fit.model is None
    assert all(t.verdict != "supported" for t in fit.scorecard)


def test_too_few_records_is_reported():
    s, taxon, effort = _world({})
    few = dict(list(taxon.items())[:10])
    fit = hourly.fit_hourly(few, effort, factors.hourly_terms("birds"), _value(s), date(2024, 1, 1))
    assert not fit.passes and "too few records" in fit.note


def test_hourly_forecast_end_to_end_and_policy(store, tmp_path):  # noqa: F811
    import json
    import warnings

    import duckdb

    from wildlife_scanner.pipeline.publish import current_bundle, publish_bundle

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

    from wildlife_scanner.api import create_app

    st, region = store
    # A dawn-active pattern, fitted on synthetic hours, stored for an open and a coarse taxon.
    s, taxon, effort = _world({"astro.diel_phase": {"dawn": 4.0}})
    terms = factors.hourly_terms("herps")
    fit = hourly.fit_hourly(taxon, effort, terms, _value(s), date(2024, 1, 1), reps=40)
    assert fit.passes
    for taxon_id in ("vernalis-litoralis", "raritas-orientalis"):
        hourly.persist(st.conn, "socal", taxon_id, fit, date(2024, 1, 1), NOW)
    publish_bundle(st.conn, region, tmp_path, now=NOW)
    bundle = duckdb.connect(str(current_bundle(tmp_path / "region=socal")), read_only=True)
    shipped = {r[0] for r in bundle.execute("SELECT taxon_id FROM hourly_models").fetchall()}
    bundle.close()
    assert shipped == {"vernalis-litoralis"}  # COARSE: no hourly detail
    client = TestClient(create_app(bundle_dir=tmp_path, region_id="socal", now=NOW))
    r = client.get(
        "/species/vernalis-litoralis/forecast/hourly",
        params={"lat": 32.85, "lon": -117.27, "date": "2026-01-19"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["timezone"] == "America/Los_Angeles" and len(body["hours"]) == 24
    by_phase = {}
    for h in body["hours"]:
        by_phase.setdefault(h["factors"]["diel_phase"], []).append(h["multiplier"])
    assert min(by_phase["dawn"]) > 2 * max(by_phase["day"])
    best = {h["start"]: h for h in body["hours"]}
    assert all(best[b]["factors"]["diel_phase"] == "dawn" for b in body["best"][:1])
    assert body["factors"]["diel_phase"]["dawn"] > 3
    coarse = client.get(
        "/species/raritas-orientalis/forecast/hourly",
        params={"lat": 32.85, "lon": -117.27, "date": "2026-01-19"},
    ).json()
    assert coarse["hours"] == [] and any("openly mapped" in n for n in coarse["notes"])
    assert json.dumps(body)  # serializable
    # The batch daily forecast: every cell of the week's map, Level 0 without a model.
    batch = client.get(
        "/species/vernalis-litoralis/forecast/map", params={"date": "2026-01-19"}
    ).json()
    smap = client.get("/species/vernalis-litoralis/map", params={"date": "2026-01-19"}).json()
    assert {c["cell"] for c in batch["cells"]} == {c["cell"] for c in smap["cells"]}
    assert batch["level"] == 0 and all(c["p"] == c["p_level0"] for c in batch["cells"])
    picked = smap["cells"][0]["cell"]
    one = client.get(
        "/species/vernalis-litoralis/forecast/map",
        params={"date": "2026-01-19", "cells": f"{picked},not-a-cell"},
    ).json()
    assert [c["cell"] for c in one["cells"]] == [picked]
    too_many = ",".join(["x"] * 2001)
    r = client.get("/species/vernalis-litoralis/forecast/map", params={"cells": too_many})
    assert r.status_code == 400
    coarse_map = client.get(
        "/species/raritas-orientalis/forecast/map", params={"date": "2026-01-19"}
    ).json()
    assert coarse_map["level"] == 0 and any("openly mapped" in n for n in coarse_map["notes"])
    assert client.get("/species/secretus-maximus/forecast/map").status_code == 404


def test_hourly_taxa_are_picked_across_groups():
    from wildlife_scanner.pipeline.runner import pick_timed_taxa

    info = {f"bird-{i}": ("birds", None, 1000 - i, 0) for i in range(10)}
    info |= {"fish-a": ("fishes", None, 50, 0), "fish-b": ("fishes", None, 40, 1)}
    info |= {"otter": ("mammals", None, 900, 2), "slug": ("mollusks", None, 30, 0)}
    picked = pick_timed_taxa(info, {"birds", "fishes", "mammals", "mollusks"}, 5)
    assert picked == ["bird-0", "fish-a", "slug", "bird-1", "fish-b"]  # otter: COARSE
