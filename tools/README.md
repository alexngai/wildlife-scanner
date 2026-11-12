# Operator tools

Standalone scripts for bulk data work. The range-request extractor now lives in the package
(`wildlife_radar.connectors.gbif_snapshot_remote`), and the `snapshot` job runs all of it with
`wildlife-radar run <target> --ingest-snapshots`. These scripts are thin wrappers for running
the steps one at a time.

## Extracting a region from a GBIF snapshot without DuckDB's `httpfs`

The normal path is `wildlife-radar ingest-snapshot --snapshot-date …`. It reads the snapshot directly from AWS, but needs DuckDB's `httpfs` extension, which DuckDB downloads at first use. Where that download is blocked, or to save bandwidth, these tools do the same with plain HTTPS range requests.

| Script | What it does |
|---|---|
| `list_parts.py` | Lists a snapshot's parts (`[key, size]`) from the public S3 bucket over HTTPS, for `extract_region.py`. |
| `extract_region.py` | For each snapshot part: fetches the footer, then only the lat/lon column chunks, and tests the bounding box. If any rows match, it fetches the remaining needed columns and writes the matching rows to a small local staging Parquet. It is resumable: `.done` markers mark finished parts. |
| `ingest_parallel.py` | Parses staged rows with the package's own parser across N processes and bulk-loads them into an `ObservationStore`. |

```bash
uv run python tools/extract_region.py parts.json staging/ work/ -121.0 32.4 -114.1 35.8 10
```

```bash
uv run python tools/ingest_parallel.py data/wr.duckdb staging/ -117.62 32.53 -116.08 33.51 4
```

`parts.json` is a JSON list of `[key, size]` pairs for the snapshot's parts:

```bash
uv run python tools/list_parts.py 2026-11-01 data/parts.json
```

Reference run, 2026-11-01 snapshot, Southern California bounding box:
- 10,346 parts
- 135 GB fetched out of 272 GB
- 22 minutes at about 100 MB/s with 10 workers
- 81.6 million rows staged, in 1.9 GB

See [`docs/research/08-real-data-run-2026-11.md`](../docs/research/08-real-data-run-2026-11.md).

Keep staging data and databases **outside the repository** or in the git-ignored `data/` folder. Cite the snapshot as GBIF.org (1 November 2026) GBIF Occurrence Download https://doi.org/10.15468/dl.jeesns.
