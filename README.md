# wildlife-radar

An online resource to help people find wildlife. It fuses several data sources into predictions of when and where a species is likely to be:

- species observations (iNaturalist, GBIF, eBird, survey programs, fishing reports)
- environmental conditions (water temperature, tides, moon, swell, clarity, weather)
- prey and behavioral signals (for example, market squid spawning)

**Flagship use case:** white seabass in Southern California for underwater photographers and freedivers.

**Second vertical:** birding.

## Status

**Phase 0 (skeleton) is done**; Phase 1, a baseline for every Southern California species, is next. For the research and design, start with [`docs/research/00-synthesis.md`](docs/research/00-synthesis.md). It summarizes the data landscape, the evidence behind the candidate signals, a proposed model architecture, ethics guardrails and next steps. It links to seven detailed research reports.

The framework design (draft) is in [`docs/design/framework.md`](docs/design/framework.md). It covers the species-agnostic architecture: core concepts, species profiles generated from metadata, how signals are combined, rare and cryptic species, species-first and place-first queries, the policy layer and the roadmap.

## Development

Phase 0 (the skeleton) is in place. It includes:
- the canonical data model
- H3 grid and as-of time utilities
- the policy layer: tiers, fail-closed assignment and the egress filter
- species profiles with inheritance
- the first connectors
- evaluation basics

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

Try the CLI. These commands work offline:

```bash
uv run wildlife-radar astro --lat 32.8505 --lon -117.272 --date 2026-11-15 --utc-offset -8
```

```bash
uv run wildlife-radar profiles list
```

```bash
uv run wildlife-radar profiles tier atractoscion-nobilis --region socal --date 2026-05-01
```

These commands need network access to the source APIs:

```bash
uv run wildlife-radar tides --station 9410230 --start 2026-11-15 --days 2
```

```bash
uv run wildlife-radar observations --source gbif --taxon "Atractoscion nobilis" --region socal
```

Where things live:
- `src/wildlife_radar/`: the package. Its layout is in [`docs/design/framework.md`](docs/design/framework.md) §11.
- `profiles/`: species profiles and guild templates (drafts). See [`profiles/README.md`](profiles/README.md).
- `regions/socal/`: the first region pack.
- [`DATA_SOURCES.md`](DATA_SOURCES.md): the sources each connector uses and their terms.

## License

wildlife-radar is an exclusively **non-commercial**, free, educational project.

- **Code:** [GNU AGPL-3.0](LICENSE). If you run a modified version as a network service, you must offer its source to your users.
- **Third-party data:** not included in this repository. Each source keeps its own license and terms; many are non-commercial. Anyone running this code is responsible for complying with them. See [`docs/design/licensing.md`](docs/design/licensing.md).
