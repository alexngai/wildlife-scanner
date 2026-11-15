from datetime import UTC, date, datetime, timedelta

import pytest

from wildlife_scanner.policy import (
    ConservationStatus,
    PolicyTier,
    SensitivityInputs,
    TierOverride,
    TierTable,
    TierWindow,
    assign_tier,
    resolve_tier,
)

NOW = datetime(2026, 11, 11, tzinfo=UTC)


def inputs(*statuses, **kw):
    base = dict(taxon_resolved=True, statuses=tuple(statuses))
    base.update(kw)
    return SensitivityInputs(**base)


def st(authority, code, **kw):
    return ConservationStatus(authority=authority, code=code, **kw)


def test_open_when_nothing_triggers():
    d = assign_tier(inputs())
    assert d.tier is PolicyTier.OPEN
    assert d.reasons


@pytest.mark.parametrize(
    "kw",
    [
        {"taxon_resolved": False},
        {"statuses": None},
        {"lookups_failed": ("natureserve",)},
        {"stale_sources": ("cdfw",)},
    ],
)
def test_fail_closed(kw):
    assert assign_tier(inputs(**kw)).tier is PolicyTier.COARSE


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (st("IUCN", "LC"), PolicyTier.OPEN),
        (st("IUCN", "NT"), PolicyTier.GENERALIZED),
        (st("IUCN", "DD"), PolicyTier.GENERALIZED),
        (st("IUCN", "EN"), PolicyTier.COARSE),
        (st("IUCN", "VU", threats=frozenset({"hunting"})), PolicyTier.WITHHELD),
        (st("ESA", "T"), PolicyTier.COARSE),
        (st("ESA", "C"), PolicyTier.GENERALIZED),
        (st("CESA", "C"), PolicyTier.COARSE),
        (st("NatureServe", "G2G3"), PolicyTier.COARSE),
        (st("NatureServe", "S3"), PolicyTier.GENERALIZED),
        (st("NatureServe", "G5"), PolicyTier.OPEN),
        (st("CITES", "I"), PolicyTier.WITHHELD),
        (st("CITES", "II"), PolicyTier.COARSE),
        (st("CA-SSC", "SSC"), PolicyTier.GENERALIZED),
        (st("Mystery", "X"), PolicyTier.GENERALIZED),
    ],
)
def test_status_triggers(status, expected):
    assert assign_tier(inputs(status)).tier is expected


def test_scoped_statuses_only_apply_in_scope():
    cesa = st("CESA", "T", scope="ca-southern-central-coast")
    assert assign_tier(inputs(cesa)).tier is PolicyTier.OPEN
    in_scope = assign_tier(inputs(cesa), scopes=["global", "ca-southern-central-coast"])
    assert in_scope.tier is PolicyTier.COARSE


def test_other_triggers_and_max():
    assert assign_tier(inputs(inat_geoprivacy="private")).tier is PolicyTier.WITHHELD
    assert assign_tier(inputs(inat_geoprivacy="obscured")).tier is PolicyTier.COARSE
    assert assign_tier(inputs(ebird_sensitive=True)).tier is PolicyTier.COARSE
    assert assign_tier(inputs(poaching_target=True)).tier is PolicyTier.WITHHELD
    assert assign_tier(inputs(contexts=frozenset({"den"}))).tier is PolicyTier.WITHHELD
    d = assign_tier(inputs(st("IUCN", "NT"), inat_geoprivacy="obscured"))
    assert d.tier is PolicyTier.COARSE
    assert len(d.reasons) == 2


def test_seasonal_window_raises():
    w = TierWindow(start="03-15", end="06-15", tier=PolicyTier.GENERALIZED, regions=("socal",))
    kw = dict(auto_tier=PolicyTier.OPEN, taxon_id="t", now=NOW, windows=[w])
    assert resolve_tier(on=date(2026, 5, 1), region="socal", **kw).tier is PolicyTier.GENERALIZED
    assert resolve_tier(on=date(2026, 5, 1), region="baja", **kw).tier is PolicyTier.OPEN
    assert resolve_tier(on=date(2026, 8, 1), region="socal", **kw).tier is PolicyTier.OPEN


def _lower(**kw):
    base = dict(
        taxon_id="t",
        tier=PolicyTier.OPEN,
        region="park",
        rationale="managed viewing",
        approvers=("alice", "bob"),
        expires_at=NOW + timedelta(days=365),
    )
    base.update(kw)
    return TierOverride(**base)


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        (_lower(), PolicyTier.OPEN),
        (_lower(approvers=("alice",)), PolicyTier.COARSE),
        (_lower(approvers=("alice", "alice")), PolicyTier.COARSE),
        (_lower(rationale=" "), PolicyTier.COARSE),
        (_lower(expires_at=None), PolicyTier.COARSE),
        (_lower(expires_at=NOW - timedelta(days=1)), PolicyTier.COARSE),
        (_lower(region="elsewhere"), PolicyTier.COARSE),
    ],
)
def test_lowering_requires_approval(override, expected):
    eff = resolve_tier(
        auto_tier=PolicyTier.COARSE,
        taxon_id="t",
        on=date(2026, 8, 1),
        region="park",
        now=NOW,
        overrides=[override],
    )
    assert eff.tier is expected
    if expected is PolicyTier.COARSE and override.region == "park":
        assert eff.ignored


def test_windows_survive_lowering_and_raises_apply():
    w = TierWindow(start="01-01", end="12-31", tier=PolicyTier.GENERALIZED)
    eff = resolve_tier(
        auto_tier=PolicyTier.COARSE,
        taxon_id="t",
        on=date(2026, 8, 1),
        region="park",
        now=NOW,
        windows=[w],
        overrides=[_lower()],
    )
    assert eff.tier is PolicyTier.GENERALIZED
    raised = resolve_tier(
        auto_tier=PolicyTier.OPEN,
        taxon_id="t",
        on=date(2026, 8, 1),
        region=None,
        now=NOW,
        profile_default=PolicyTier.COARSE,
        overrides=[_lower(tier=PolicyTier.WITHHELD, region=None, approvers=())],
    )
    assert raised.tier is PolicyTier.WITHHELD


def test_tier_table_fails_closed():
    table = TierTable(tiers={"a": PolicyTier.OPEN}, default=PolicyTier.GENERALIZED)
    assert table.get("a") is PolicyTier.OPEN
    assert table.get("b") is PolicyTier.GENERALIZED
    assert table.get(None) is PolicyTier.COARSE
