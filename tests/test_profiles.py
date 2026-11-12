from datetime import UTC, date, datetime

import pytest

from wildlife_radar.policy import PolicyTier
from wildlife_radar.profiles import ProfileError, ProfileLibrary, SpeciesProfile, deep_merge
from wildlife_radar.regions import load_region

NOW = datetime(2026, 11, 11, tzinfo=UTC)
VALIDATION_SPECIES = {
    "atractoscion-nobilis",
    "triakis-semifasciata",
    "limosa-fedoa",
    "puma-concolor",
    "canis-lupus",
    "stereolepis-gigas",
}


@pytest.fixture(scope="module")
def lib():
    return ProfileLibrary()


def test_all_bundled_profiles_resolve(lib):
    assert set(lib.ids(kind="species")) == VALIDATION_SPECIES
    for pid in lib.ids():
        lib.resolve(pid)


def test_inheritance(lib):
    wsb = lib.resolve("atractoscion-nobilis")
    assert {"kelp_canopy", "sst_anomaly", "water_clarity", "sst"} <= set(wsb.signals)
    assert wsb.nowcast.half_life_days == (2, 7)
    assert {"gbif", "inaturalist", "cpfv_counts"} <= set(wsb.sources)
    assert "collared_individual" in wsb.policy.always_suppress
    assert wsb.guilds == ["marine-nearshore-fish", "kelp-forest-pelagic-predator"]
    assert wsb.hypotheses() == ["squid_light_index", "lunar_illumination"]
    assert wsb.signals["hours_after_sunset"].params == {"at": 1}

    puma = lib.resolve("puma-concolor")
    assert puma.methods.headline == "sign_survey"
    assert puma.nowcast.enabled is False
    assert puma.policy.default_tier is PolicyTier.COARSE
    assert {"collared_individual", "disperser"} <= set(puma.policy.always_suppress)
    assert puma.sources["inaturalist"].lookalikes  # species override merged into inherited source
    assert puma.sources["inaturalist"].bias == ["observer_density", "access", "media_spikes"]


def test_templates_do_not_leak_identity(lib):
    merged = lib.merged("limosa-fedoa")
    assert merged["id"] == "limosa-fedoa"
    assert merged["kind"] == "species"
    assert merged["extends"] == ["guild/shorebird"]


def test_white_seabass_spawning_window(lib):
    wsb = lib.resolve("atractoscion-nobilis")
    spring = wsb.effective_tier(PolicyTier.OPEN, region="socal", on=date(2026, 5, 1), now=NOW)
    summer = wsb.effective_tier(PolicyTier.OPEN, region="socal", on=date(2026, 8, 1), now=NOW)
    assert spring.tier is PolicyTier.GENERALIZED
    assert summer.tier is PolicyTier.OPEN


def test_unapproved_regional_downgrade_is_ignored(lib):
    puma = lib.resolve("puma-concolor")
    eff = puma.effective_tier(
        PolicyTier.OPEN, region="torres-del-paine", on=date(2026, 5, 1), now=NOW
    )
    assert eff.tier is PolicyTier.COARSE
    assert any("torres-del-paine" in msg for msg in eff.ignored)


def test_schema_validation():
    with pytest.raises(ValueError, match="scientific_name"):
        SpeciesProfile(id="x", methods=["scuba_dive"])
    with pytest.raises(ValueError, match="unknown encounter methods"):
        SpeciesProfile(id="x", scientific_name="X y", methods=["teleport"])
    p = SpeciesProfile(
        id="x", scientific_name="X y", methods=["scuba_dive"], signals={"ocean.sst_c": {}}
    )
    assert p.signals["ocean.sst_c"].signal == "ocean.sst_c"


def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text)


def test_cycles_and_duplicates(tmp_path):
    _write(tmp_path, "a.yaml", "id: a\nkind: template\nextends: [b]\n")
    _write(tmp_path, "b.yaml", "id: b\nkind: template\nextends: [a]\n")
    with pytest.raises(ProfileError, match="cycle"):
        ProfileLibrary(tmp_path).resolve("a")
    _write(tmp_path, "c.yaml", "id: a\nkind: template\n")
    with pytest.raises(ProfileError, match="duplicate"):
        ProfileLibrary(tmp_path)


def test_deep_merge():
    base = {"a": {"x": 1, "y": [1]}, "always_suppress": ["nest"], "guilds": ["g1"]}
    over = {"a": {"y": [2]}, "always_suppress": ["den", "nest"], "guilds": ["g2"]}
    assert deep_merge(base, over) == {
        "a": {"x": 1, "y": [2]},
        "always_suppress": ["nest", "den"],
        "guilds": ["g1", "g2"],
    }
    assert base["a"]["y"] == [1]  # inputs untouched


def test_socal_region():
    region = load_region("socal")
    assert region.contains(32.85, -117.27)
    assert not region.contains(37.77, -122.42)
    assert "ca-southern-central-coast" in region.scopes
    cove = region.place("la-jolla-cove")
    assert len(cove.cells(9)) >= 1


def test_giant_sea_bass_is_coarse_without_any_listing(lib):
    gsb = lib.resolve("stereolepis-gigas")
    eff = gsb.effective_tier(PolicyTier.OPEN, region="socal", on=date(2026, 7, 1), now=NOW)
    assert eff.tier is PolicyTier.COARSE
