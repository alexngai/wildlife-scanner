# Data sources used by the connectors

**This repository contains no third-party data.** Connectors fetch data at runtime, under the credentials and terms of whoever runs them. If you run this code, you are responsible for complying with each source's terms.

wildlife-radar itself is an exclusively non-commercial, educational project (see [`docs/design/licensing.md`](docs/design/licensing.md)).

| Connector | Source | Data license | Terms | Notes |
|---|---|---|---|---|
| `connectors/inaturalist.py` | [iNaturalist](https://www.inaturalist.org) API v1 | Per observation; mostly **CC BY-NC**. A blank license means all rights reserved | [Terms](https://www.inaturalist.org/pages/terms), [API practices](https://www.inaturalist.org/pages/api+recommended+practices) | ≤1 request/s; the API is for applications, not bulk scraping (use GBIF for bulk). Never de-obscure coordinates. Commercial AI training is prohibited. |
| `connectors/gbif.py` | [GBIF](https://www.gbif.org) occurrence search API; Darwin Core snapshot rows | Per dataset/record: CC0, CC BY or CC BY-NC | [Terms](https://www.gbif.org/terms), [citation guidelines](https://www.gbif.org/citation-guidelines) | Cite download DOIs; register derived-dataset DOIs for filtered or snapshot use. Search paging caps at ~100k records. |
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
- Never commit API keys, downloaded data or caches. `.gitignore` excludes `data/`, `cache/`, `*.parquet`, `*.zarr/`, `*.nc` and `.env*`.
