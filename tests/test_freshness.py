"""Per-source freshness: collected at publish, judged against targets in /health."""

from __future__ import annotations

import warnings
from datetime import UTC, date, datetime, timedelta

from test_publish import NOW, store  # noqa: F401  (fixture)

from wildlife_scanner.pipeline.freshness import report
from wildlife_scanner.pipeline.publish import publish_bundle

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from wildlife_scanner.api import create_app  # noqa: E402


def test_report_compares_ages_with_targets():
    now = datetime(2026, 11, 13, 12, tzinfo=UTC)
    rows = [
        (
            "inaturalist",
            (now - timedelta(minutes=20)).replace(tzinfo=None),
            date(2026, 11, 13),
            9,
            "",
        ),
        ("noaa", (now - timedelta(days=3)).replace(tzinfo=None), date(2026, 11, 10), None, ""),
        ("gbif-snapshot", None, None, None, None),
    ]
    by = {r["source"]: r for r in report(rows, now)}
    assert by["inaturalist"]["status"] == "ok" and by["inaturalist"]["age_hours"] == 0.3
    assert by["noaa"]["status"] == "stale" and by["noaa"]["target_hours"] == 48
    assert by["gbif-snapshot"]["status"] == "unknown"


def test_health_reports_freshness_from_the_bundle(store, tmp_path):  # noqa: F811
    st, region = store
    fresh = [
        (
            "inaturalist",
            (NOW - timedelta(minutes=10)).replace(tzinfo=None),
            date(2026, 1, 19),
            5,
            "",
        ),
        ("noaa", (NOW - timedelta(days=5)).replace(tzinfo=None), date(2026, 1, 15), None, ""),
    ]
    publish_bundle(st.conn, region, tmp_path, now=NOW, freshness=fresh)
    health = (
        TestClient(create_app(bundle_dir=tmp_path, region_id="socal", now=NOW))
        .get("/health")
        .json()
    )
    by = {f["source"]: f["status"] for f in health["freshness"]}
    assert by == {"inaturalist": "ok", "noaa": "stale"}
    assert health["regions"][0]["status"] == "stale"
