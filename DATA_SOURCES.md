# Data sources used by the connectors

**This repository contains no third-party data.** Connectors fetch data at runtime, under the credentials and terms of whoever runs them. If you run this code, you are responsible for complying with each source's terms.

wildlife-radar itself is an exclusively non-commercial, educational project (see [`docs/design/licensing.md`](docs/design/licensing.md)).

| Connector | Source | Data license | Terms | Notes |
|---|---|---|---|---|
| `connectors/inaturalist.py` | [iNaturalist](https://www.inaturalist.org) API v1 | Per observation; mostly **CC BY-NC**. A blank license means all rights reserved | [Terms](https://www.inaturalist.org/pages/terms), [API practices](https://www.inaturalist.org/pages/api+recommended+practices) | ≤1 request/s; the API is for applications, not bulk scraping (use GBIF for bulk). Never de-obscure coordinates. Commercial AI training is prohibited. |
| `connectors/gbif.py` | [GBIF](https://www.gbif.org) occurrence search API; Darwin Core snapshot rows | Per dataset/record: CC0, CC BY or CC BY-NC | [Terms](https://www.gbif.org/terms), [citation guidelines](https://www.gbif.org/citation-guidelines) | Cite download DOIs; register derived-dataset DOIs for filtered or snapshot use. Search paging caps at ~100k records. |
| `connectors/gbif_snapshot.py` | [GBIF monthly occurrence snapshots](https://www.gbif.org/occurrence-snapshots) (Parquet; AWS `s3://gbif-open-data-us-east-1/occurrence/<date>/occurrence.parquet/`) | Per record: CC0, CC BY or CC BY-NC | As GBIF above | Bulk ingestion for baselines. Cite the snapshot; register a derived-dataset DOI for published products. eBird data arrives here as the eBird Observation Dataset (CC BY 4.0, presence-only). |
| `connectors/inaturalist_taxa.py` | iNaturalist taxon conservation statuses (API v1) | — (metadata) | As iNaturalist above | Used for automatic sensitivity tiers only; cached up to 90 days, after which entries are stale and fail closed. |
| `connectors/noaa_coops.py` | [NOAA CO-OPS](https://tidesandcurrents.noaa.gov) tide predictions | US Government work (public domain) | [Disclaimers](https://tidesandcurrents.noaa.gov/disclaimers.html) | Not for navigation. |
| `connectors/astronomy.py` | Computed locally with [Astronomy Engine](https://github.com/cosinekitty/astronomy) (MIT) | Our computed values: CC0 | — | No network access. |

## Not used (pending)

| Source | Why not yet |
|---|---|
| eBird API / Basic Dataset / Status & Trends | Needs written confirmation from Cornell for a public web service (map redistribution, caching). |
| IUCN Red List API / spatial data | Its terms on redistributing raw data and range polygons still need checking. |
| Fishing-report sites | Their terms prohibit automated access and redistribution. Partnership only. |

## Operator configuration

- `WILDLIFE_RADAR_USER_AGENT`: set a User-Agent that includes your contact details. Many APIs ask for one; the default identifies only the software.
- `WILDLIFE_RADAR_HASH_SALT`: a per-deployment salt for hashing observer identifiers. Only salted hashes are stored, which is enough to group records into visits.
- `WILDLIFE_RADAR_SOURCE_URL`: the public source URL of your deployment (AGPL §13). The API sends it in the `X-Source-Code` header.
- Never commit API keys, downloaded data or caches. `.gitignore` excludes `data/`, `cache/`, `*.parquet`, `*.zarr/`, `*.nc` and `.env*`.
