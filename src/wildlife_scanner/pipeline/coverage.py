"""Coverage-area snapshots: one GBIF snapshot pass for many regions (docs/design/ingestion.md §2).

A coverage area (a region pack such as ``california``) is extracted from each monthly GBIF
snapshot once, into Parquet tiles of 1° × 1°::

    lake/norm/observations/source=gbif/snapshot=<date>/coverage=<id>/tlat=<°>/tlon=<°>/*.parquet
    …/coverage=<id>/_SUCCESS.json     rows per tile, written last (a partial build has none)
    …/coverage=<id>/delta.json        what changed since the previous snapshot

Regions whose pack names ``coverage: <id>`` ingest the tiles their bounding box touches,
with no download of their own; a new region inside the area costs no network at all.

**Deletions.** Each snapshot is complete. When a region ingests a new one, GBIF rows from
earlier ingests that it no longer contains are deleted: records deleted or re-licensed at the
source, datasets withdrawn. Rows of live datasets pulled from the API after the snapshot was
taken are kept until the next snapshot can confirm them.
"""

from __future__ import annotations

import json
import math
import os
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from wildlife_scanner.connectors import gbif_snapshot_remote as remote
from wildlife_scanner.regions import Region

SUCCESS = "_SUCCESS.json"
DELTA = "delta.json"
MAX_FILE_BYTES = 200_000_000
"""Tile files are cut at about this size (a dense tile holds ~20 M rows, 650 MB): object
storage uploads are limited (R2's REST API takes at most 300 MiB per object)."""


def snapshot_dir(lake: Path, coverage_id: str, snapshot_date: str) -> Path:
    return (
        lake
        / "norm"
        / "observations"
        / "source=gbif"
        / f"snapshot={snapshot_date}"
        / f"coverage={coverage_id}"
    )


def built(lake: Path, coverage_id: str, snapshot_date: str) -> dict | None:
    marker = snapshot_dir(lake, coverage_id, snapshot_date) / SUCCESS
    return json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else None


def previous_snapshot(lake: Path, coverage_id: str, before: str) -> str | None:
    root = lake / "norm" / "observations" / "source=gbif"
    dates = sorted(
        p.name.removeprefix("snapshot=")
        for p in root.glob("snapshot=*")
        if (p / f"coverage={coverage_id}" / SUCCESS).exists()
        and p.name.removeprefix("snapshot=") < before
    )
    return dates[-1] if dates else None


def build(
    coverage: Region,
    snapshot_date: str,
    lake: Path,
    *,
    workers: int = 10,
    keep_staging: bool = False,
    log=print,
    parts: list[tuple[str, int]] | None = None,
) -> dict:
    """Extract the coverage area from a snapshot into tiles (reused if already built)."""
    done = built(lake, coverage.id, snapshot_date)
    if done:
        return {**done, "reused": True}
    out_dir = snapshot_dir(lake, coverage.id, snapshot_date)
    work = lake / "raw" / "gbif-snapshot" / f"date={snapshot_date}" / f"coverage={coverage.id}"
    staging, scratch = work / "staging", work / "work"
    parts = parts if parts is not None else remote.list_parts(snapshot_date)
    stats = remote.extract_region(parts, staging, scratch, coverage.bbox, workers, log=log)
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    con = duckdb.connect()
    # Order doesn't matter here; not preserving it lets DuckDB stream instead of buffering.
    con.execute("SET preserve_insertion_order = false")
    files = f"'{(staging / '*.parquet').as_posix()}'"
    # One latitude band at a time: writing every tile at once keeps a buffer open per tile and
    # spilled >12 GB for California (180 M rows, 121 tiles).
    bands = [
        b
        for (b,) in con.execute(
            f"SELECT DISTINCT floor(decimallatitude)::INTEGER FROM read_parquet({files}, "
            "union_by_name = true) WHERE decimallatitude IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
    for band in bands:
        con.execute(
            f"""
            COPY (
                SELECT *, floor(decimallatitude)::INTEGER AS tlat,
                    floor(decimallongitude)::INTEGER AS tlon
                FROM read_parquet({files}, union_by_name = true)
                WHERE floor(decimallatitude)::INTEGER = {int(band)}
            ) TO '{out_dir.as_posix()}'
            (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (tlat, tlon), OVERWRITE_OR_IGNORE,
             FILENAME_PATTERN 'part-{{i}}', FILE_SIZE_BYTES {MAX_FILE_BYTES})
            """
        )
        log(f"coverage {coverage.id} {snapshot_date}: wrote latitude band {band}")
    tiles = {
        f"{a}_{b}": n
        for a, b, n in con.execute(
            f"SELECT floor(decimallatitude)::INTEGER, floor(decimallongitude)::INTEGER, count(*) "
            f"FROM read_parquet({files}, union_by_name = true) GROUP BY ALL"
        ).fetchall()
    }
    result = {
        "coverage": coverage.id,
        "snapshot_date": snapshot_date,
        "rows": sum(tiles.values()),
        "tiles": tiles,
        "extract": stats,
        "built_at": datetime.now(UTC).isoformat(),
    }
    prev = previous_snapshot(lake, coverage.id, snapshot_date)
    if prev:
        result["delta"] = delta(lake, coverage.id, prev, snapshot_date)
        (out_dir / DELTA).write_text(json.dumps(result["delta"], indent=2), encoding="utf-8")
    (out_dir / SUCCESS).write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not keep_staging:
        shutil.rmtree(work, ignore_errors=True)
    log(f"coverage {coverage.id} {snapshot_date}: {result['rows']:,} rows in {len(tiles)} tiles")
    return result


def delta(lake: Path, coverage_id: str, old: str, new: str) -> dict:
    """Per dataset: records added, removed, and changed (``lastinterpreted`` moved)."""

    def src(d: str) -> str:
        return f"'{(snapshot_dir(lake, coverage_id, d) / '**' / '*.parquet').as_posix()}'"

    con = duckdb.connect()
    rows = con.execute(
        f"""
        WITH a AS (SELECT gbifid, datasetkey, lastinterpreted FROM read_parquet({src(old)},
                   union_by_name = true)),
             b AS (SELECT gbifid, datasetkey, lastinterpreted FROM read_parquet({src(new)},
                   union_by_name = true))
        SELECT coalesce(b.datasetkey, a.datasetkey) AS dataset,
            count(*) FILTER (WHERE a.gbifid IS NULL) AS added,
            count(*) FILTER (WHERE b.gbifid IS NULL) AS removed,
            count(*) FILTER (WHERE a.gbifid IS NOT NULL AND b.gbifid IS NOT NULL
                             AND a.lastinterpreted IS DISTINCT FROM b.lastinterpreted) AS changed
        FROM a FULL OUTER JOIN b USING (gbifid)
        GROUP BY 1 ORDER BY added + removed DESC
        """
    ).fetchall()
    per = {d: {"added": a, "removed": r, "changed": c} for d, a, r, c in rows if a or r or c}
    totals = {k: sum(v[k] for v in per.values()) for k in ("added", "removed", "changed")}
    return {"from": old, "to": new, "totals": totals, "datasets": per}


def region_files(lake: Path, coverage_id: str, snapshot_date: str, bbox) -> list[str]:
    """The tile files a region's bounding box touches."""
    lon_min, lat_min, lon_max, lat_max = bbox
    root = snapshot_dir(lake, coverage_id, snapshot_date)
    out: list[str] = []
    for tlat in range(math.floor(lat_min), math.floor(lat_max) + 1):
        for tlon in range(math.floor(lon_min), math.floor(lon_max) + 1):
            out += sorted(
                str(p) for p in (root / f"tlat={tlat}" / f"tlon={tlon}").glob("*.parquet")
            )
    return out


def ingest_region(
    region: Region,
    db: Path,
    lake: Path,
    coverage_id: str,
    snapshot_date: str,
    *,
    workers: int = 4,
    log=print,
    live_keys: list[str] | None = None,
) -> dict:
    """Load a region's rows from the coverage tiles, then delete GBIF rows the snapshot no
    longer has (see ``ingest_staged``)."""
    files = region_files(lake, coverage_id, snapshot_date, region.bbox)
    if not files:
        raise RuntimeError(f"no tiles of {coverage_id} {snapshot_date} cover {region.id}")
    taken = datetime.combine(date.fromisoformat(snapshot_date), datetime.min.time())
    return remote.ingest_staged(
        db, files, region.bbox, workers, log=log, reconcile_taken=taken, live_keys=live_keys
    )


def split_large(
    lake: Path,
    coverage_id: str,
    snapshot_date: str,
    max_bytes: int = MAX_FILE_BYTES,
    limit: int | None = None,
) -> list[str]:
    """Cut tile files over ``limit`` (default: the largest single upload; tiles built before
    the size cap) into parts of about ``max_bytes``, in place. Returns the files split.

    The cap is approximate (DuckDB closes a file after it passes it), so pieces can be a
    little over ``max_bytes``; only files over the upload limit are split again."""
    from wildlife_scanner.storage.objects import R2_MAX_PUT

    limit = R2_MAX_PUT if limit is None else limit
    root = snapshot_dir(lake, coverage_id, snapshot_date)
    done: list[str] = []
    for path in sorted(root.glob("tlat=*/tlon=*/*.parquet")):
        if path.stat().st_size <= limit:
            continue
        tmp = path.parent / f".split-{path.stem}"
        shutil.rmtree(tmp, ignore_errors=True)
        con = duckdb.connect()
        con.execute("SET preserve_insertion_order = false")
        con.execute(
            f"COPY (SELECT * FROM read_parquet('{path.as_posix()}', hive_partitioning = false)) "
            f"TO '{tmp.as_posix()}' (FORMAT parquet, COMPRESSION zstd, "
            f"FILE_SIZE_BYTES {int(max_bytes)}, FILENAME_PATTERN 'part-{{i}}')"
        )
        before = con.execute(
            f"SELECT count(*) FROM read_parquet('{path.as_posix()}', hive_partitioning = false)"
        ).fetchone()[0]
        after = con.execute(
            f"SELECT count(*) FROM read_parquet('{(tmp / '*.parquet').as_posix()}', "
            "hive_partitioning = false)"
        ).fetchone()[0]
        if before != after:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"split of {path} lost rows ({before} -> {after})")
        for i, piece in enumerate(sorted(tmp.glob("*.parquet"))):
            os.replace(piece, path.parent / f"{path.stem}-s{i}.parquet")
        path.unlink()
        shutil.rmtree(tmp, ignore_errors=True)
        done.append(str(path.relative_to(root)))
    return done
