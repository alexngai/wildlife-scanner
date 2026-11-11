# wildlife-radar

An online resource to help people find wildlife. It fuses several data sources into predictions of when and where a species is likely to be:

- species observations (iNaturalist, GBIF, eBird, survey programs, fishing reports)
- environmental conditions (water temperature, tides, moon, swell, clarity, weather)
- prey and behavioral signals (for example, market squid spawning)

**Flagship use case:** white seabass in Southern California for underwater photographers and freedivers.

**Second vertical:** birding.

## Status

Research / design phase. Start with [`docs/research/00-synthesis.md`](docs/research/00-synthesis.md). It summarizes the data landscape, the evidence behind the candidate signals, a proposed model architecture, ethics guardrails and next steps. It links to five detailed research reports.

The framework design (draft) is in [`docs/design/framework.md`](docs/design/framework.md). It covers the species-agnostic architecture: core concepts, species profiles generated from metadata, how signals are combined, rare and cryptic species, species-first and place-first queries, the policy layer and the roadmap.
