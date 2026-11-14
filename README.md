# wildlife-radar

An online resource to help people find wildlife. It fuses several data sources into predictions of when and where a species is likely to be:

- species observations (iNaturalist, GBIF, eBird, survey programs, fishing reports)
- environmental conditions (water temperature, tides, moon, swell, clarity, weather)
- prey and behavioral signals (for example, market squid spawning)

**Flagship use case:** white seabass in Southern California for underwater photographers and freedivers.

**Second vertical:** birding.

## Status

**Phases 0–2 are done**: the skeleton, a policy-enforced baseline for every species with method-specific effort models, and the profile-generation pipeline (identity crosswalk, trait import, occurrence-derived priors, evidence-checked LLM extraction, reconciliation and review). Phase 3, conditions and live signals, is next. Picking up the work? Read [`docs/handoff.md`](docs/handoff.md) first: current state, open threads, and how to rebuild the data. For the research and design, start with [`docs/research/00-synthesis.md`](docs/research/00-synthesis.md). It summarizes the data landscape, the evidence behind the candidate signals, a proposed model architecture, ethics guardrails and next steps. It links to seven detailed research reports.

The framework design (draft) is in [`docs/design/framework.md`](docs/design/framework.md). It covers the species-agnostic architecture: core concepts, species profiles generated from metadata, how signals are combined, rare and cryptic species, species-first and place-first queries, the policy layer and the roadmap.

## Development

**Phase 0 (skeleton) and Phase 1 (a baseline for every species) are done.**

Phase 1 adds:
- GBIF snapshot ingestion into a DuckDB observation store
- a Level-0 baseline for every species with enough records. It is corrected for where observers go (target-group background) and smoothed over seasons and space.
- backtest gates against a range-only map
- fail-closed sensitivity tiers
- a policy-enforced query layer and HTTP API, for both species-first and place-first questions

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

```bash
uv run pytest
```

```bash
uv run ruff check . && uv run ruff format --check .
```

### Try it offline

This builds a synthetic demo database and serves it:

```bash
uv run wildlife-radar demo
```

```bash
uv run wildlife-radar query place --db data/demo.duckdb --lat 32.85 --lon -117.27 --date 2026-05-15
```

```bash
uv run wildlife-radar serve --db data/demo.duckdb
```

Then open `http://127.0.0.1:8000/docs`.

### Real data for Southern California

Data goes in `data/`, which git ignores:

1. Ingest the GBIF monthly snapshot (AWS open data, needs DuckDB's `httpfs` extension), keeping only records inside the region:

   ```bash
   uv run wildlife-radar ingest-snapshot --region socal --snapshot-date 2026-11-01
   ```

2. Build the Level-0 baseline and backtest it against a range-only map:

   ```bash
   uv run wildlife-radar build-baseline --region socal
   ```

   ```bash
   uv run wildlife-radar evaluate-baseline --region socal --split 2025-01-01
   ```

3. Look up conservation statuses and assign sensitivity tiers. Without a completed lookup, taxa fail closed to awareness-only:

   ```bash
   uv run wildlife-radar build-tiers --region socal
   ```

4. Query or serve:

   ```bash
   uv run wildlife-radar query taxa
   ```

   ```bash
   uv run wildlife-radar serve
   ```

5. Generate draft species profiles (written to `data/profiles/generated/`). Download [TetrapodTraits](https://zenodo.org/records/11303604) into `data/` first if you want trait values:

   ```bash
   uv run wildlife-radar profilegen generate "Puma concolor" "Limosa fedoa" --traits data/traits/TetrapodTraits_1.0.0.csv --db data/wildlife-radar.duckdb --region socal
   ```

   To resolve every baseline taxon (verified iNaturalist ids make `build-tiers` faster and robust to renamed taxa), run this before step 3:

   ```bash
   uv run wildlife-radar profilegen crosswalk --db data/wildlife-radar.duckdb --region-id socal
   ```

   LLM extraction from Wikipedia (`--extract`) needs the `llm` extra (`uv sync --extra llm`), an Anthropic API key, an extraction model (`--model` or `WILDLIFE_RADAR_EXTRACTION_MODEL`), and a User-Agent with your contact details (Wikimedia policy). See [`profiles/README.md`](profiles/README.md) for review and promotion.

6. Phase 3, conditions and live signals. Download daily station signals (NOAA CO-OPS water/air temperature, wind, tides), then fit Level 1 (conditions) and Level 2 (recent sightings) for species profiles. Each level must beat the one below in a backtest:

   ```bash
   uv run wildlife-radar fetch-signals --region socal --start 2010-01-01
   ```

   ```bash
   uv run wildlife-radar fit-conditions --region socal --split 2023-01-01 --since-year 2010
   ```

   ```bash
   uv run wildlife-radar scorecard --region socal
   ```

   The scorecard reports, for each condition term, whether it improves held-out predictions (supported, contradicted or inconclusive). `serve` then answers `/species/{id}/forecast?place_id=…&date=…` at the highest level that passed its gate, with each term's contribution.

   The `nowcast` job (part of `run publish`) fits recent-sightings forecasts for the best-sampled openly mapped species, with no profile needed. `/places/{id}/recent` and `/nearby/recent` list what has been reported nearby in the last two weeks, and which species those reports make more likely today. They use live sources only (iNaturalist) and respect the publication delays.

7. Before publishing, check the tiers against every status signal in the store. The command exits non-zero on high-severity findings:

   ```bash
   uv run wildlife-radar audit-tiers --region socal
   ```

Data repairs: `repair-dates` re-dates records a dataset stamped with a placeholder date, using the date in their event ids (see `regions/california/datasets.yaml`).

### Running it as a pipeline

After the first snapshot ingest, the steps above form a job graph ([`docs/design/data-platform.md`](docs/design/data-platform.md)). `run` brings a target up to date and skips every job whose inputs haven't changed. Each job records a manifest under `data/lake/manifests/`:

```bash
uv run wildlife-radar run list
```

```bash
uv run wildlife-radar run publish --region socal
```

`publish` writes a policy-filtered, read-only serving bundle per region, and only if the tier audit has no high-severity findings. The API serves the current bundle and switches to new ones as they are published, so rebuilds never block it:

```bash
uv run wildlife-radar serve --region socal --bundle-dir data/lake/publish
```

Scheduled every 30 minutes, `run publish` refreshes recent iNaturalist records (the `live` job) and republishes. Signals refresh daily, and baselines, tiers and condition models monthly.

Other commands work without a database:

```bash
uv run wildlife-radar astro --lat 32.8505 --lon -117.272 --date 2026-11-15 --utc-offset -8
```

```bash
uv run wildlife-radar profiles tier atractoscion-nobilis --region socal --date 2026-05-01
```

```bash
uv run wildlife-radar tides --station 9410230 --start 2026-11-15 --days 2
```

Where things live:
- `src/wildlife_radar/`: the package. Its layout is in [`docs/design/framework.md`](docs/design/framework.md) §11.
- `profiles/`: species profiles and guild templates (drafts). See [`profiles/README.md`](profiles/README.md).
- `regions/socal/`: the first region pack (places, status scopes, curated statuses).
- [`DATA_SOURCES.md`](DATA_SOURCES.md): the sources each connector uses and their terms.

## License

wildlife-radar is an exclusively **non-commercial**, free, educational project.

- **Code:** [GNU AGPL-3.0](LICENSE). If you run a modified version as a network service, you must offer its source to your users.
- **Third-party data:** not included in this repository. Each source keeps its own license and terms; many are non-commercial. Anyone running this code is responsible for complying with them. See [`docs/design/licensing.md`](docs/design/licensing.md).
