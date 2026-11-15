import pytest

from wildlife_scanner.core.licenses import (
    ALL_RIGHTS_RESERVED,
    CC0,
    CC_BY,
    CC_BY_NC,
    CC_BY_ND,
    CC_BY_SA,
    UNKNOWN,
    combine,
    parse_license,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("cc-by-nc", "CC-BY-NC-4.0"),
        ("cc0", "CC0-1.0"),
        ("CC-BY-SA-4.0", "CC-BY-SA-4.0"),
        ("CC_BY_4_0", "CC-BY-4.0"),
        ("CC_BY_NC_4_0", "CC-BY-NC-4.0"),
        ("http://creativecommons.org/licenses/by-nc/4.0/legalcode", "CC-BY-NC-4.0"),
        ("https://creativecommons.org/licenses/by/3.0/", "CC-BY-4.0"),
        ("https://creativecommons.org/publicdomain/zero/1.0/legalcode", "CC0-1.0"),
        ("something custom", "UNKNOWN"),
    ],
)
def test_parse_license(raw, expected):
    assert parse_license(raw).id == expected


def test_missing_license_defaults_to_all_rights_reserved():
    assert parse_license(None) is ALL_RIGHTS_RESERVED
    assert parse_license("", missing=UNKNOWN) is UNKNOWN


def test_combine_constraints():
    assert combine([CC0, CC_BY]).fully_open
    assert combine([]).fully_open

    mixed = combine([CC_BY, CC_BY_NC])
    assert mixed.noncommercial and not mixed.fully_open
    assert mixed.publishable_noncommercially
    assert mixed.license_ids == {"CC-BY-4.0", "CC-BY-NC-4.0"}

    assert not combine([CC_BY_SA]).fully_open  # share-alike excluded from the fully open variant
    assert not combine([CC_BY_ND]).publishable_noncommercially
    assert combine([ALL_RIGHTS_RESERVED]).restricted
    assert not combine([CC0]).attribution_required
