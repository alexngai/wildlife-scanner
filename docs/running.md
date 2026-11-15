# Running Wildlife Scanner

How to build the data for a region by hand, step by step, and how the same steps run as a
pipeline. The [README](../README.md) has the overview; [`deploy.md`](deploy.md) covers hosting;
[`design/ingestion.md`](design/ingestion.md) explains coverage areas and the live log.

Data goes in `data/`, which git ignores. Commands run from the repository root.

## The quick way: the job graph

For a region inside a coverage area (all current packs are inside `california`), one command
builds everything, skipping steps whose inputs haven't changed:

```bash
uv run wildlife-scanner run publish --region montereybay --db data/mb.duckdb --lake data/lake \
    --ingest-snapshots
```

The first run extracts the coverage area from GBIF's monthly snapshot (about 25 minutes and
180 GB read for California, shared by every region in it), loads the region, and builds the
models and the published version (1–2 hours). Later runs take minutes.

`run list` shows the jobs. `--force <job>` reruns one; `--dry-run` shows the plan.

## Step by step, for one region

Data goes in `data/`, which git ignores:

1. Ingest the GBIF monthly snapshot (AWS open data, needs DuckDB's `httpfs` extension), keeping only records inside the region:

   ```bash
   uv run wildlife-scanner ingest-snapshot --region socal --snapshot-date 2026-11-01
   ```

2. Build the Level-0 baseline and backtest it against a range-only map:

   ```bash
   uv run wildlife-scanner build-baseline --region socal
   ```

   ```bash
   uv run wildlife-scanner evaluate-baseline --region socal --split 2025-01-01
   ```

3. Look up conservation statuses and assign sensitivity tiers. Without a completed lookup, taxa fail closed to awareness-only:

   ```bash
   uv run wildlife-scanner build-tiers --region socal
   ```

4. Query or serve:

   ```bash
   uv run wildlife-scanner query taxa
   ```

   ```bash
   uv run wildlife-scanner serve
   ```

5. Generate draft species profiles (written to `data/profiles/generated/`). Download [TetrapodTraits](https://zenodo.org/records/11303604) into `data/` first if you want trait values:

   ```bash
   uv run wildlife-scanner profilegen generate "Puma concolor" "Limosa fedoa" --traits data/traits/TetrapodTraits_1.0.0.csv --db data/wildlife-scanner.duckdb --region socal
   ```

   To resolve every baseline taxon (verified iNaturalist ids make `build-tiers` faster and robust to renamed taxa), run this before step 3:

   ```bash
   uv run wildlife-scanner profilegen crosswalk --db data/wildlife-scanner.duckdb --region-id socal
   ```

   LLM extraction from Wikipedia (`--extract`) needs the `llm` extra (`uv sync --extra llm`), an Anthropic API key, an extraction model (`--model` or `WILDLIFE_SCANNER_EXTRACTION_MODEL`), and a User-Agent with your contact details (Wikimedia policy). See [`profiles/README.md`](profiles/README.md) for review and promotion.

6. Phase 3, conditions and live signals. Download daily station signals (NOAA CO-OPS water/air temperature, wind, tides), then fit Level 1 (conditions) and Level 2 (recent sightings) for species profiles. Each level must beat the one below in a backtest:

   ```bash
   uv run wildlife-scanner fetch-signals --region socal --start 2010-01-01
   ```

   ```bash
   uv run wildlife-scanner fit-conditions --region socal --split 2023-01-01 --since-year 2010
   ```

   ```bash
   uv run wildlife-scanner scorecard --region socal
   ```

   The scorecard reports, for each condition term, whether it improves held-out predictions (supported, contradicted or inconclusive). `serve` then answers `/species/{id}/forecast?place_id=…&date=…` at the highest level that passed its gate, with each term's contribution.

   The `nowcast` job (part of `run publish`) fits recent-sightings forecasts for the best-sampled openly mapped species, with no profile needed. `/places/{id}/recent` and `/nearby/recent` list what has been reported nearby in the last two weeks, and which species those reports make more likely today. They use live sources only (iNaturalist) and respect the publication delays.

7. Before publishing, check the tiers against every status signal in the store. The command exits non-zero on high-severity findings:

   ```bash
   uv run wildlife-scanner audit-tiers --region socal
   ```

Data repairs: `repair-dates` re-dates records a dataset stamped with a placeholder date, using the date in their event ids (see `regions/california/datasets.yaml`).

## Running it as a pipeline

After the first snapshot ingest, the steps above form a job graph ([`docs/design/data-platform.md`](docs/design/data-platform.md)). `run` brings a target up to date and skips every job whose inputs haven't changed. Each job records a manifest under `data/lake/manifests/`:

```bash
uv run wildlife-scanner run list
```

```bash
uv run wildlife-scanner run publish --region socal
```

`publish` writes a policy-filtered, read-only serving bundle per region, and only if the tier audit has no high-severity findings. The API serves the current bundle and switches to new ones as they are published, so rebuilds never block it:

```bash
uv run wildlife-scanner serve --region socal --bundle-dir data/lake/publish
```

Scheduled every 30 minutes, `run publish` refreshes recent iNaturalist records (the `live` job) and republishes. Signals refresh daily, and baselines, tiers and condition models monthly.

Other commands work without a database:

```bash
uv run wildlife-scanner astro --lat 32.8505 --lon -117.272 --date 2026-11-15 --utc-offset -8
```

```bash
uv run wildlife-scanner profiles tier atractoscion-nobilis --region socal --date 2026-05-01
```

```bash
uv run wildlife-scanner tides --station 9410230 --start 2026-11-15 --days 2
```
