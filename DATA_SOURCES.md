# Data sources used by the connectors

**This repository contains no third-party data.** Connectors fetch data at runtime, under the credentials and terms of whoever runs them. If you run this code, you are responsible for complying with each source's terms.

wildlife-scanner itself is an exclusively non-commercial, educational project (see [`docs/design/licensing.md`](docs/design/licensing.md)).

| Connector | Source | Data license | Terms | Notes |
|---|---|---|---|---|
| `connectors/inaturalist.py` | [iNaturalist](https://www.inaturalist.org) API v1 | Per observation; mostly **CC BY-NC**. A blank license means all rights reserved | [Terms](https://www.inaturalist.org/pages/terms), [API practices](https://www.inaturalist.org/pages/api+recommended+practices) | ≤1 request/s; the API is for applications, not bulk scraping (use GBIF for bulk). Never de-obscure coordinates. Commercial AI training is prohibited. |
| `connectors/gbif.py` | [GBIF](https://www.gbif.org) occurrence search API; Darwin Core snapshot rows | Per dataset/record: CC0, CC BY or CC BY-NC | [Terms](https://www.gbif.org/terms), [citation guidelines](https://www.gbif.org/citation-guidelines) | Cite download DOIs; register derived-dataset DOIs for filtered or snapshot use. Search paging caps at ~100k records. |
| `connectors/gbif_snapshot.py` | [GBIF monthly occurrence snapshots](https://www.gbif.org/occurrence-snapshots) (Parquet; AWS `s3://gbif-open-data-us-east-1/occurrence/<date>/occurrence.parquet/`) | Per record: CC0, CC BY or CC BY-NC | As GBIF above | Bulk ingestion for baselines. Cite the snapshot; register a derived-dataset DOI for published products. eBird data arrives here as the eBird Observation Dataset (CC BY 4.0, presence-only). |
| `connectors/inaturalist_taxa.py` | iNaturalist taxon conservation statuses (API v1) | — (metadata) | As iNaturalist above | Used for automatic sensitivity tiers only; cached up to 90 days, after which entries are stale and fail closed. |
| `profilegen/identity.py` | [GBIF species match API](https://techdocs.gbif.org/en/openapi/v1/species); [Wikidata Query Service](https://query.wikidata.org) (SPARQL); iNaturalist taxa API | Wikidata: **CC0**. GBIF/iNaturalist: metadata | [Wikidata](https://www.wikidata.org/wiki/Wikidata:Licensing), GBIF and iNaturalist as above | Name → identity crosswalk, batched (100 names per SPARQL query; 30 ids per iNaturalist request; ≤1 request/s). Cached in the store's `taxon_identity` table. |
| `profilegen/traits.py` | [TetrapodTraits 1.0.0](https://zenodo.org/records/11303604) (Moura et al. 2024, *PLOS Biology*) | **CC BY 4.0** | Cite the paper and the Zenodo record | Downloaded by the operator into `data/`. Measured vs. imputed values are kept apart. The IUCN status column is not imported. |
| `profilegen/wikipedia.py` | English Wikipedia (MediaWiki action API, plain-text extracts pinned to a revision) | **CC BY-SA 4.0** | [Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy), [User-Agent policy](https://meta.wikimedia.org/wiki/User-Agent_policy) | Input to LLM extraction only; cached under `data/`. Wikimedia **requires a contact in the User-Agent**: set `WILDLIFE_SCANNER_USER_AGENT`. Profiles store values plus revision id and character range, never text. |
| `profilegen/extract.py` | Anthropic API (operator's key; optional `llm` extra) | Outputs inherit the source text's license | [Anthropic usage policies](https://www.anthropic.com/legal/aup) | The model is set by the operator (`--model` or `WILDLIFE_SCANNER_EXTRACTION_MODEL`). Extractions are weak priors; never used for status or tiers. |
| `connectors/noaa_coops.py` | [NOAA CO-OPS](https://tidesandcurrents.noaa.gov) tide predictions | US Government work (public domain) | [Disclaimers](https://tidesandcurrents.noaa.gov/disclaimers.html) | Not for navigation. |
| `conditions/daily.py` | NOAA CO-OPS water temperature, air temperature and wind (hourly observations), and hi/lo tide predictions | US Government work (public domain) | As above | Aggregated to local-day values per station for Level-1 condition terms; one request per station, product and year. Moon illumination and phase are computed locally (Astronomy Engine). |
| `connectors/gbif_events.py` | GBIF occurrence search API (event ids for re-dating records) | As GBIF above | As GBIF above | Pages only the records of a dataset on a known placeholder date; retries with backoff. |
| `connectors/astronomy.py` | Computed locally with [Astronomy Engine](https://github.com/cosinekitty/astronomy) (MIT) | Our computed values: CC0 | — | No network access. |

## Not used (pending)

| Source | Why not yet |
|---|---|
| eBird API / Basic Dataset / Status & Trends | Needs written confirmation from Cornell for a public web service (map redistribution, caching). |
| IUCN Red List API / spatial data | Its terms on redistributing raw data and range polygons still need checking. |
| Fishing-report sites | Their terms prohibit automated access and redistribution. Partnership only. |

## Operator configuration

- `WILDLIFE_SCANNER_USER_AGENT`: set a User-Agent that includes your contact details. Many APIs ask for one; the default identifies only the software.
- `WILDLIFE_SCANNER_HASH_SALT`: a per-deployment salt for hashing observer identifiers. Only salted hashes are stored, which is enough to group records into visits.
- `WILDLIFE_SCANNER_SOURCE_URL`: the public source URL of your deployment (AGPL §13). The API sends it in the `X-Source-Code` header.
- Never commit API keys, downloaded data or caches. `.gitignore` excludes `data/`, `cache/`, `*.parquet`, `*.zarr/`, `*.nc` and `.env*`.
