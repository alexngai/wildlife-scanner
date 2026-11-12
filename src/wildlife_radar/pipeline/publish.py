"""Publish a policy-filtered serving bundle for one region (docs/design/data-platform.md §2, §5).

A bundle is a read-only DuckDB file holding only what the API needs, already filtered by policy:

- **No raw observations.** Recent activity ships as aggregates (``recent_detections``,
  ``recent_effort``) for the Level-2 nowcast, built from records older than the OPEN tier's
  delay and only for OPEN taxa.
- **Withheld taxa are absent** from every table, so they are indistinguishable from unknown ones.
- **Sensitive taxa keep only statistics at or above their tier's resolution**: GENERALIZED taxa
  lose cell-level rows, COARSE taxa keep only context-level and regional rows. Taxa without a
  tier decision are treated as COARSE (fail closed).

Publishing is gated on the tier audit: any high-severity finding blocks it unless explicitly
overridden, and the override is recorded in the manifest. The bundle is written to a temporary
folder, then moved into place and the region's ``CURRENT`` pointer swapped atomically, so the
API never sees a half-written bundle.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

from wildlife_radar.baseline.builder import (
    LEVEL_CELL,
    LEVEL_CONTEXT,
    LEVEL_PARENT,
    LEVEL_REGION,
    BaselineConfig,
    create_training_view,
)
from wildlife_radar.baseline.effort import DatasetRegistry
from wildlife_radar.core.time import utcnow
from wildlife_radar.policy.audit import Finding, audit_tiers
from wildlife_radar.policy.tiers import PolicyTier, rule_for
from wildlife_radar.regions import Region
from wildlife_radar.storage.observations import naive_utc

BUNDLE_FILE = "serving.duckdb"
CURRENT = "CURRENT"
RECENT_DAYS = 60


class PublishBlocked(RuntimeError):
    def __init__(self, findings: list[Finding]):
        self.findings = findings
        super().__init__(f"tier audit has {len(findings)} high-severity findings")


@dataclass
class PublishResult:
    region_id: str
    version: str
    path: Path
    rows: dict[str, int] = field(default_factory=dict)
    findings: dict[str, int] = field(default_factory=dict)
    overridden: bool = False


def _tables(conn: duckdb.DuckDBPyConnection) -> set[str]:
    return {r[0] for r in conn.execute("SHOW TABLES").fetchall()}


def allowed_levels(conn: duckdb.DuckDBPyConnection, region_id: str) -> dict[int, list[int]]:
    """Statistics levels each tier may keep: those whose cells are no finer than the tier's."""
    res, parent_res, context_res = conn.execute(
        "SELECT res, parent_res, context_res FROM prior_builds WHERE region_id = ?", [region_id]
    ).fetchone()
    level_res = {LEVEL_CELL: res, LEVEL_PARENT: parent_res, LEVEL_CONTEXT: context_res}
    out = {}
    for tier in (PolicyTier.OPEN, PolicyTier.GENERALIZED, PolicyTier.COARSE):
        limit = rule_for(tier).h3_res
        out[int(tier)] = [lv for lv, r in level_res.items() if limit is not None and r <= limit]
        out[int(tier)].append(LEVEL_REGION)
    return out


def publish_bundle(
    conn: duckdb.DuckDBPyConnection,
    region: Region,
    out_root: Path,
    *,
    curated_ids: list[str] = (),  # type: ignore[assignment]
    registry: DatasetRegistry | None = None,
    config: BaselineConfig | None = None,
    now: datetime | None = None,
    allow_findings: bool = False,
    inputs: dict[str, str] | None = None,
    before_swap=None,
) -> PublishResult:
    """``before_swap(bundle_path, version_dir, final_dir)`` may add files (static products) to
    the version before it becomes current; whatever it returns is recorded in the manifest."""
    now = now or utcnow()
    findings = audit_tiers(conn, region.id, list(curated_ids))
    high = [f for f in findings if f.severity == "high"]
    if high and not allow_findings:
        raise PublishBlocked(high)
    version = naive_utc(now).strftime("%Y%m%dT%H%M%S")
    region_dir = out_root / f"region={region.id}"
    tmp = region_dir / f".tmp-{version}"
    final = region_dir / f"version={version}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    bundle = tmp / BUNDLE_FILE
    result = PublishResult(region.id, version, final, overridden=bool(high))
    result.findings = {
        s: sum(1 for f in findings if f.severity == s) for s in ("high", "medium", "info")
    }

    # Tier per taxon (taxa without a decision fail closed to COARSE) and allowed levels.
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE _pub_tier AS
        SELECT p.taxon_id, coalesce(t.tier, 2) AS tier
        FROM (SELECT DISTINCT taxon_id FROM prior_taxa WHERE region_id = ?) p
        LEFT JOIN tiers t ON t.region_id = ? AND t.taxon_id = p.taxon_id
        """,
        [region.id, region.id],
    )
    levels = allowed_levels(conn, region.id)
    conn.execute("CREATE OR REPLACE TEMP TABLE _pub_level (tier SMALLINT, level SMALLINT)")
    conn.executemany(
        "INSERT INTO _pub_level VALUES (?, ?)",
        [(tier, lv) for tier, lvs in levels.items() for lv in lvs],
    )
    visible = "(SELECT taxon_id FROM _pub_tier WHERE tier < 3)"
    timing = "(SELECT taxon_id FROM _pub_tier WHERE tier <= 1)"
    allowed = (
        "EXISTS (SELECT 1 FROM _pub_tier pt JOIN _pub_level pl ON pl.tier = pt.tier "
        "WHERE pt.taxon_id = x.taxon_id AND pl.level = x.level)"
    )
    selects = {
        "prior_builds": "SELECT * FROM prior_builds x WHERE region_id = $r",
        "prior_cells": "SELECT * FROM prior_cells x WHERE region_id = $r",
        "prior_licenses": "SELECT * FROM prior_licenses x WHERE region_id = $r",
        "prior_taxa": f"SELECT * FROM prior_taxa x WHERE region_id = $r AND taxon_id IN {visible}",
        "prior_mask": f"SELECT * FROM prior_mask x WHERE region_id = $r AND taxon_id IN {visible}",
        "prior_hits": f"SELECT * FROM prior_hits x WHERE region_id = $r AND {allowed}",
        "prior_effort": (
            f"SELECT * FROM prior_effort x WHERE region_id = $r AND (taxon_id IS NULL OR {allowed})"
        ),
        "tiers": f"SELECT * FROM tiers x WHERE region_id = $r AND taxon_id IN {visible}",
        "baseline_gates": (
            f"SELECT * FROM baseline_gates x WHERE region_id = $r AND taxon_id IN {visible}"
        ),
        "conditions_gates": (
            f"SELECT * FROM conditions_gates x WHERE region_id = $r AND taxon_id IN {visible}"
        ),
        "conditions_models": (
            f"SELECT * FROM conditions_models x WHERE region_id = $r AND taxon_id IN {visible}"
        ),
        "hypothesis_scorecard": (
            f"SELECT * FROM hypothesis_scorecard x WHERE region_id = $r AND taxon_id IN {visible}"
        ),
        "taxon_alias": f"SELECT * FROM taxon_alias x WHERE taxon_id IN {visible}",
        # Time-of-day patterns carry no places, but only open and generalized taxa get them.
        "timed_index": f"SELECT * FROM timed_index x WHERE region_id = $r AND taxon_id IN {timing}",
        "timed_scorecard": (
            f"SELECT * FROM timed_scorecard x WHERE region_id = $r AND taxon_id IN {timing}"
        ),
        "signal_daily": (
            "SELECT * FROM signal_daily x WHERE station_id IN (SELECT unnest($stations))"
        ),
    }
    present = _tables(conn)
    params = {"r": region.id, "stations": [s.station_id for s in region.tide_stations]}
    conn.execute(f"ATTACH '{bundle}' AS bundle")
    try:
        for table, sql in selects.items():
            if table.split()[0] not in present:
                continue
            used = {k: v for k, v in params.items() if f"${k}" in sql}
            conn.execute(f"CREATE TABLE bundle.{table} AS {sql}", used)
            result.rows[table] = conn.execute(f"SELECT count(*) FROM bundle.{table}").fetchone()[0]
        if "taxon_identity" in present:
            # Display names from the identity crosswalk (iNaturalist's preferred names).
            conn.execute(
                f"""
                CREATE TABLE bundle.taxon_names AS
                SELECT p.taxon_id, any_value(p.scientific_name) AS scientific_name,
                       any_value(i.record->>'$.common_name') AS common_name
                FROM prior_taxa p LEFT JOIN taxon_identity i ON i.query_name = p.scientific_name
                WHERE p.region_id = ? AND p.taxon_id IN {visible} GROUP BY 1
                """,
                [region.id],
            )
            result.rows["taxon_names"] = conn.execute(
                "SELECT count(*) FROM bundle.taxon_names"
            ).fetchone()[0]
        if "observations" in present:
            result.rows.update(_recent(conn, region, registry, config or BaselineConfig(), now))
        conn.execute(
            "CREATE TABLE bundle.bundle_info AS SELECT ? AS region_id, ? AS version, "
            "?::TIMESTAMP AS published_at, ? AS inputs",
            [region.id, version, naive_utc(now), json.dumps(inputs or {})],
        )
    finally:
        conn.execute("DETACH bundle")
    extra = before_swap(bundle, tmp, final) if before_swap else None
    (tmp / "manifest.json").write_text(
        json.dumps(
            {
                "job": "publish",
                "region": region.id,
                "version": version,
                "published_at": naive_utc(now).isoformat(),
                "inputs": inputs or {},
                "rows": result.rows,
                "audit": result.findings,
                "audit_overridden": result.overridden,
                "static": extra,
                "status": "complete",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    tmp.rename(final)
    set_current(region_dir, version)
    return result


def _recent(
    conn: duckdb.DuckDBPyConnection,
    region: Region,
    registry: DatasetRegistry | None,
    cfg: BaselineConfig,
    now: datetime,
) -> dict[str, int]:
    """Recent detections (OPEN taxa only) and outings per taxon group, parent cell and day,
    from live sources and records older than the OPEN tier's delay."""
    delay = rule_for(PolicyTier.OPEN).min_delay
    create_training_view(
        conn,
        cfg,
        region.bbox,
        registry,
        name="_pub_recent",
        after=now - timedelta(days=RECENT_DAYS),
        before=now - delay,
    )
    conn.execute(
        """
        CREATE TABLE bundle.recent_effort AS
        SELECT taxon_group, c1, local_date AS day, count(DISTINCT visit_key) AS n
        FROM _pub_recent WHERE live AND local_date IS NOT NULL GROUP BY ALL
        """
    )
    conn.execute(
        """
        CREATE TABLE bundle.recent_detections AS
        SELECT r.taxon_id, r.taxon_group, r.c1, r.local_date AS day,
               count(DISTINCT r.visit_key) AS k
        FROM _pub_recent r JOIN _pub_tier t ON t.taxon_id = r.taxon_id AND t.tier = 0
        WHERE r.live AND r.detected AND r.local_date IS NOT NULL GROUP BY ALL
        """
    )
    return {
        t: conn.execute(f"SELECT count(*) FROM bundle.{t}").fetchone()[0]
        for t in ("recent_effort", "recent_detections")
    }


def set_current(region_dir: Path, version: str) -> None:
    tmp = region_dir / f".{CURRENT}.tmp"
    tmp.write_text(version + "\n", encoding="utf-8")
    os.replace(tmp, region_dir / CURRENT)


def current_bundle(region_dir: Path) -> Path | None:
    pointer = region_dir / CURRENT
    if not pointer.exists():
        return None
    version = pointer.read_text(encoding="utf-8").strip()
    path = region_dir / f"version={version}" / BUNDLE_FILE
    return path if path.exists() else None
