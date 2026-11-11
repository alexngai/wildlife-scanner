# wildlife-radar

An online resource to help people find wildlife. It fuses several data sources into predictions of when and where a species is likely to be:

- species observations (iNaturalist, GBIF, eBird, survey programs, fishing reports)
- environmental conditions (water temperature, tides, moon, swell, clarity, weather)
- prey and behavioral signals (for example, market squid spawning)

**Flagship use case:** white seabass in Southern California for underwater photographers and freedivers.

**Second vertical:** birding.

## Status

**Phases 0–1 are done**: the skeleton plus a policy-enforced baseline for every species. Phase 2, profile generation, is next. For the research and design, start with [`docs/research/00-synthesis.md`](docs/research/00-synthesis.md). It summarizes the data landscape, the evidence behind the candidate signals, a proposed model architecture, ethics guardrails and next steps. It links to seven detailed research reports.

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
