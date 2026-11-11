# Wildlife-radar: species observation and occurrence data sources (as of 2026-11-11)

**What I could and could not check.** In this session WebFetch could not reach `inaturalist.org` or `api.inaturalist.org` (DNS blocked by the network allowlist). Per the tool's instruction I stopped trying other hosts with WebFetch. The shared web-search budget then ran out near the end. So everything below comes from web search results (official pages where they showed up, otherwise forum posts or docs), plus prior knowledge where marked **UNVERIFIED**.

I could not pull live record counts, such as how many *Atractoscion nobilis* observations exist on iNat or GBIF in SoCal. To verify the gaps, allow `api.inaturalist.org`, `www.inaturalist.org`, `api.gbif.org`, `api.obis.org` and `documenter.getpostman.com` (eBird docs) in the session's network settings.

## 1. Summary table

| Source | What | Latency | Access / auth | Commercial use / redistribution | Effort / absence | Relevance (WSB / birding) |
|---|---|---|---|---|---|---|
| **iNaturalist API (v1/v2)** | Photo-vouchered citizen observations | Minutes | REST, no auth for reads; ~60 req/min | Terms restrict commercial use and ban commercial AI training. Each observation has its own CC license | Presence-only | **High / Med** |
| **iNat AWS Open Data** | Monthly metadata and photos for licensed observations | Monthly | S3, no sign-in | Photos have per-photo CC licenses; metadata license UNVERIFIED | Presence-only | Med / Low |
| **GBIF** | Aggregator; iNat research-grade data arrives weekly | Days to about 1 yr depending on publisher | REST search; async downloads need an account; monthly cloud Parquet | CC0 / CC BY / CC BY-NC per dataset; citing the DOI is required | Mostly presence-only; some event/survey datasets | **High / High** |
| **eBird API 2.0** | Recent, notable and nearby observations; hotspots | Near-real-time | REST with free API key | **Non-commercial only without written Cornell permission** | Presence-only through the API | Low / **High** |
| **eBird Basic Dataset (EBD) + Sampling Event Data (SED)** | Full eBird database plus a checklist (sampling-event) file | Monthly (15th) | Request form, approval typically ≤7 days | Research and education only; commercial use needs permission; no redistribution in the original format | **Yes**: complete checklists can be zero-filled | — / **High** |
| **OBIS** | Marine occurrences | Months to years | REST v3, no key; CSV/Parquet export | Per-dataset CC licenses | Absence records available through the API, not in the bulk export | Med / — |
| **REEF Volunteer Fish Survey** | Roving-diver fish species lists | Months | Online summary reports; raw data on request | No published license (UNVERIFIED) | **Yes** (time per survey, full species list) | **High** / — |
| **Reef Check California** | Volunteer kelp-forest transects since 2006 | Annual | data.ca.gov CSVs and API; viewer | License not stated in the search results | **Yes** | Med-High |
| **NPS Channel Islands Kelp Forest Monitoring (KFM)** | Fish counts since 1982 | Annual, 1–2 yr lag | IRMA DataStore, ERDDAP | US federal; likely public domain (UNVERIFIED) | **Yes** | Med-High |
| **PISCO** | Kelp-forest fish transects | Annual | data.gov / EDI | One SoCal subset is CC0 | **Yes** | Med |
| **SBC LTER** | Fish at 11 Santa Barbara Channel sites since 2000 | Annual | EDI; Darwin Core Archive (DwC-A) on GBIF/OBIS | DwC-A is CC BY 4.0; older EDI versions had restrictive terms | **Yes** | Med |
| **SBC MBON integrated fish** | Merges SBC LTER, PISCO and KFM | Annual | EDI (+ DwC-A script) | Owners ask to see manuscripts before publication; license UNVERIFIED | **Yes** (counts + area surveyed) | **High** for priors |
| **CalCOFI larval fish** | Larvae per net tow | Historical | ERDDAP | Public domain / CC0 | **Yes** (zero tows included) | Low-Med |
| **CRFS / RecFIN + landing reports** | Recreational catch | Daily (landings) to monthly (estimates) | RecFIN download; landing websites | RecFIN public; landing websites' terms UNVERIFIED | Partial (angler effort) | **High (timing)** |
| **Movebank** | Animal tracking | Varies | REST, account; accept license per study | Set per study | Tracks, not sightings | Low / Med |
| **Happywhale** | Cetacean photo-ID encounters | Near-real-time on site | No public API; data reaches OBIS-SEAMAP | Collaborator agreements | No | Low |
| **Whale Alert / Ocean Alert / Whale Safe** | Whale sightings and presence ratings | Near-real-time | Web, email alerts; no public API found | Unknown | Partial | Low |
| **Acartia** | Marine mammal sightings, CA to AK | Real-time | Public REST API with key | Open data cooperative (license UNVERIFIED) | No | Low |
| **Macaulay Library** | Media linked to eBird checklists | Real-time | No documented public API | Commercial use only with the contributor's consent | No | — / Low |
| **xeno-canto** | Geotagged sound recordings | Real-time | API v3, **key required since 2025-10-10** | CC license per recording (mostly NC, UNVERIFIED) | No | — / Low |

## 2. Per-source details

### iNaturalist API
- **URLs:** https://api.inaturalist.org/v1/docs/ , https://api.inaturalist.org/v2/ , https://www.inaturalist.org/pages/api+recommended+practices
- **v1 vs v2 status.** On the forum thread "Is v2 the official API now?" (active April 2026), staff say v2 is out of beta and is "the preferred API to use going forward". The website and iOS app run on v2, and `api.inaturalist.org` now points to the v2 docs. I found **no v1 retirement date**. Plan on v2, and keep the client abstracted in case v1 is switched off. https://forum.inaturalist.org/t/is-v2-the-official-api-now/77258
- **Rate limits.** The documented guideline is ≤60 requests/min. Users report HTTP 429 errors at 60/min, and 30/min was reliable. https://forum.inaturalist.org/t/429-error-from-observations-histogram-api-when-calling-at-60-calls-minute/64709
  - A daily cap (~10k requests/day) and media download caps (GB/hr) are **UNVERIFIED**; I could not fetch the recommended-practices page.
- **Paging.** Max `per_page` is 200. Page/offset paging stops at 10,000 results; use `id_above` / `id_below` (keyset paging) to go further. Use `updated_since` for incremental syncs.
- **Auth.** Public reads need none. Writes and private data need a JWT obtained through OAuth; it expires after 24h. One forum report says the token endpoint no longer works non-interactively.
- **Terms.**
  - The API docs say the API supports application development, "not data scraping", and that iNat will block uses that violate the Terms without notice.
  - The Terms (2023 revision) include a **ban on using iNat data to train AI/ML models for commercial purposes**.
  - A third-party summary of the Terms says content may not be used commercially, with an exception for non-commercial research and conservation. **Exact wording UNVERIFIED.** https://www.inaturalist.org/pages/terms
  - Whether the AWS open dataset falls under the Terms is disputed on the forum, with no staff answer. https://forum.inaturalist.org/t/can-i-use-inaturalist-aws-open-data-to-train-commercial-ai-model/77663
- **Licenses per observation.** The default is CC BY-NC. Users can choose CC0, CC BY, CC BY-SA, CC BY-ND, or all rights reserved. **The observation license and each photo's license can differ.** A blank license field in exports means all rights reserved.
- **Research grade.** Requires date, location, media and community ID agreement. Use `quality_grade=research`, but "needs ID" records also carry signal.
- **Geoprivacy.**
  - Users can mark observations obscured or private.
  - Automatic taxon geoprivacy applies to IUCN Near Threatened or worse taxa, and to taxa flagged by curators or other conservation authorities.
  - Obscured coordinates are a random point in a 0.2°×0.2° cell (about 22×18 km at 33°N). Positional accuracy can exceed 29 km. Fields to check: `obscured` / `coordinates_obscured`, `taxon_geoprivacy`, `geoprivacy`.
  - True coordinates are visible only to the observer, trusted users and project curators. https://help.inaturalist.org/en/support/solutions/articles/151000233080 , https://help.inaturalist.org/support/solutions/articles/151000169938
  - White seabass is IUCN **Least Concern** (2020 assessment), so automatic obscuring is unlikely. That is UNVERIFIED on iNat itself, and user-level obscuring still happens.
  - Giant sea bass (*Stereolepis gigas*) is probably auto-obscured (UNVERIFIED). That matters if we expand to it.
- **Gotchas.**
  - Strong observer and access bias (La Jolla Cove, shore-diving sites, popular boats).
  - Observation dates can be upload dates for imported photos.
  - Only 4 of 170 papers acknowledged obscured data.
  - Recent guidance: "Guidelines and best practices for the scientific use of global iNaturalist data", *BioScience* 2026, https://academic.oup.com/bioscience/advance-article/doi/10.1093/biosci/biag135/8820383

### iNaturalist AWS Open Data
- **Location:** `s3://inaturalist-open-data/` (us-east-1), readable with `--no-sign-request`. https://registry.opendata.aws/inaturalist-open-data , https://github.com/inaturalist/inaturalist-open-data
- **Contents.** Monthly tab-separated metadata (observations, observers, photos, taxa) plus photos in several sizes, for **observations with licensed photos only**. Older count: about 42M observations, 1.6 GB gzipped.
- **Gotchas.** Rows carry a UUID but no observation ID. No observation fields or annotations. Metadata license and coordinate obscuring behavior **UNVERIFIED**. Best use is bulk historical seeding and a commercially licensable photo pool (filter per photo).

### GBIF
- **URLs:** https://techdocs.gbif.org/en/openapi/ , https://techdocs.gbif.org/en/data-use/api-downloads , SQL downloads at https://techdocs.gbif.org/en/data-use/api-sql-downloads
- **Search API.** No auth. Up to 300 records per page. Sources disagree on the offset cap (100k vs 200k). GBIF returns 429 when overloaded, guarantees no particular rate, and says to use downloads for bulk.
- **Downloads.** Asynchronous; need a GBIF account (HTTP Basic). Formats: SIMPLE_CSV, DWCA, SPECIES_LIST, plus SQL downloads, which are useful for gridded counts. Too many concurrent downloads returns 420. **Every download gets a DOI, and the data user agreement requires citing it.** If you filter heavily or use cloud snapshots, register a "derived dataset" DOI. https://www.gbif.org/citation-guidelines
- **Cloud snapshots.** Monthly Parquet on AWS (several regions, including us-east-1), Azure (Planetary Computer) and GCS/BigQuery. The 2026-09-01 snapshot had about 3.57B records. Good for DuckDB/Athena queries without the API. https://www.gbif.org/occurrence-snapshots , https://registry.opendata.aws/gbif/
- **Licensing.**
  - GBIF accepts CC0, CC BY 4.0 and CC BY-NC 4.0 only, licensed per dataset.
  - A download takes the most restrictive license among its records.
  - **You can filter downloads with a `license` predicate** (for example CC0 + CC_BY_4_0) to get a commercially safe subset. https://www.gbif.org/news/82868 , https://data-blog.gbif.org/post/gbif-occurrence-license-processing/
- **iNat on GBIF.**
  - Weekly export of research-grade observations licensed CC0, CC BY or CC BY-NC; changes resync. https://help.inaturalist.org/en/support/solutions/articles/151000170346
  - The dataset-level license shows as CC BY-NC, but the records keep their original licenses in the archive. https://forum.inaturalist.org/t/inaturalist-data-on-gbif-shows-only-cc-by-nc-excluding-cc0-and-cc-by/9952
  - Dataset: https://www.gbif.org/dataset/50c9509d-22c7-4a22-a47d-8c48425ef4a7
- **eBird on GBIF ("EOD").** Updated **annually**; the last confirmed release was August 2025. Data on GBIF is therefore 3–15+ months old. Presence-only; sensitive species are withheld. https://doi.org/10.15468/aomfnb
  - **UNVERIFIED and worth checking:** the license on GBIF may be CC BY 4.0. If so, it is a more permissive route to eBird *presence* data than the eBird terms.
- **Effort.** Mostly presence-only. Survey-and-monitoring (event-core) datasets with `occurrenceStatus=absent` exist and can be selected.
- **Duplicates.** iNat records in GBIF duplicate the iNat API; deduplicate on `occurrenceID` / `catalogNumber` (UNVERIFIED mapping).

### eBird API 2.0
- **Base URL:** `https://api.ebird.org/v2`. Free key sent in the `X-eBirdApiToken` header.
- **Endpoints:** recent observations by region (`/data/obs/{region}/recent`), nearby (`/data/obs/geo/recent`), notable (`.../recent/notable`), by species, hotspots (`/ref/hotspot/geo`), checklist view.
- **Limits.** A maximum look-back of 30 days (`back`) and a maximum radius of 50 km (`dist`) are **UNVERIFIED**; the Postman docs were not reachable. Rate limits are undocumented; clients throttle to about 100/min.
- **Terms.** https://www.birds.cornell.edu/home/ebird-api-terms-of-use/
  - Revocable, non-commercial license.
  - **Commercial use requires prior written permission from Cornell.** "Commercial purposes" covers *any* use by a for-profit entity and some non-profit uses.
  - Do not share the API key.
  - All data obtained through the API fall under the eBird Data Access Terms.
- **Sensitive species.** Output is restricted (325 taxa per an older article), hidden from public checklists, and shown only at 20/100 km grid resolution. Whether the API applies the same masking is UNVERIFIED (likely yes). https://www.allaboutbirds.org/sensitive-species-in-ebird/

### eBird Basic Dataset (EBD) + Sampling Event Data
- **URL:** https://science.ebird.org/en/use-ebird-data/download-ebird-data-products
- **Release and access.** Monthly (15th). Log in, submit a request form, typically approved within 7 days. Custom subsets by species, region and date; the full file is over 100 GB.
- **Purpose-bound.** A new use requires a new request. Sensitive species require extra vetting.
- **Effort and absence.** The SED file has one row per checklist with protocol, duration, distance, observer count and start time (fields per the eBird best-practices guide). On **complete checklists** you can zero-fill unreported species into non-detections (`auk_zerofill`, which also needs `auk_unique` to remove duplicate group checklists). This is the gold standard for bird occupancy/abundance models. https://ebird.github.io/ebird-best-practices/ebird.html , https://rdrr.io/cran/auk/man/auk_zerofill.html
- **Terms.** https://www.birds.cornell.edu/home/ebird-data-access-terms-of-use (Nov 2020 version found; check for newer)
  - Research and education only; commercial use requires permission.
  - Attribution required; no redistribution in the original format.
  - eBird Status & Trends modeled products have separate terms (2023), and commercial use is explicitly not covered.

### OBIS
- **URLs:** https://api.obis.org/v3/occurrence , https://manual.obis.org/access.html
- **Access.** Open API with no key (UNVERIFIED that none is ever needed); `robis` R client.
- **Full export.** CSV or Parquet, **presence-only**. Absence records are excluded from downloads but retrievable through the API or robis.
- **Licenses.** Per dataset. One 2025-08 snapshot STAC record says CC BY 4.0. Check the license field on each record.
- **Relevant content.** SBC LTER reef fish DwC-A (CC BY 4.0, 2025) and OBIS-SEAMAP marine mammal surveys, for example the SCB 1975–78 surveys (CC BY-NC, with effort in km surveyed).
- **Latency.** Publisher-dependent, usually months to years. Use it as a historical prior.

### REEF Volunteer Fish Survey Project
- **URL:** https://www.reef.org
- **Method.** Roving Diver Technique: each survey is a full species list with abundance categories, bottom time, depth and temperature. Data are error-checked.
- **Effort and non-detection.** Because each survey is a full species list with effort, it supports detection/non-detection analysis. This is the closest public analogue to "a diver's chance of seeing species X on a dive". Pacific-coast coverage dates and abundance bins from memory, UNVERIFIED.
- **Access.** Public online summary reports. **Raw data only on request** through REEF staff, with a required citation format. No published license; **commercial use UNVERIFIED, so a partnership is needed.**

### Reef Check California
- **History and scale.** Surveys in SoCal since 2006; more than 190 surveys region-wide in 2024. 2024 season data was released April 2025. https://www.reefcheck.org/data-now-available-from-the-2024-kelp-forest-monitoring-season/
- **Data access.** MPA-baseline data on data.ca.gov: South Coast 2011–12 and North Coast 2014–16, as CSVs plus an API. https://catalog.data.gov/dataset/citizen-scientist-monitoring-of-rocky-reefs-and-kelp-forests-california-south-coast-mpa-ba
- **Viewer:** https://californiampas.org/?p=8476
- **Open points.** Newer years require a request (UNVERIFIED). Whether white seabass is on the fish list is UNVERIFIED.

### NPS Channel Islands Kelp Forest Monitoring
- **Program.** Annual surveys since 1982 across the five park islands, May–Oct; dates are recorded as a nominal July 1.
- **Roving diver fish counts.** 30-minute counts within 10 m of a permanent 100 m transect. One paper finds roving divers likely under-sample the target area (Rassweiler et al. 2020). https://www.frontiersin.org/articles/10.3389/fmars.2020.00272
- **Data.**
  - Fish transects 1985–2007 on ERDDAP: https://coastwatch.pfeg.noaa.gov/erddap/info/erdCinpKfm5Q/index.html
  - Annual reports and data on the IRMA DataStore.
  - Roving diver counts 2003–2019 mirrored in BioTIME (study 595).

### PISCO, SBC LTER, and SBC MBON
- **PISCO.** A SoCal kelp-fish SCUBA survey subset (with the Vantuna Research Group) is on data.gov under **CC0**. https://catalog.data.gov/dataset/fish-diversity-in-southern-california-using-scuba-surveys-in-kelp-forests
- **SBC LTER.** Permanent transects at 11 Santa Barbara Channel sites.
  - Fish DwC-A is CC BY 4.0 (published on OBIS June 2025): https://www.gbif.org/dataset/1683e434-321c-4b55-a5b0-6e05eb6d931f
  - An older EDI version had LTER terms ("no sell/redistribute", contact before publishing). Check the current EDI revision.
- **SBC MBON "Nearshore kelp forest integrated fish" (EDI).** https://marinebon.org/datasets/santa-barbara-channel-marine-bon-nearshore-kelp-forest-integrated-fish/
  - Harmonizes SBC LTER, PISCO and NPS KFM from 1980/81 onward: about 400 taxa, counts plus area surveyed (so density can be computed), and site coordinates.
  - Includes a script that converts it to DwC-A.
  - Owners expect to see manuscripts before publication.
  - **Best single effort-bearing kelp-forest fish dataset for SoCal.** Catalog: https://scbmarinebon.grit.ucsb.edu/data/catalog/

### CalCOFI larval fish
- **What.** Larvae per net tow on ERDDAP, with **zero tows included**, standardized per 10 m² or per 1000 m³. Coverage 1951–2020 in the metadata. Public domain.
- **Where white seabass would be.** *Atractoscion* should sit in the "AS to BA" dataset (my inference from the alphabetical split). https://catalog.data.gov/dataset/calcofi-larvae-counts-scientific-names-as-to-ba
- **Relevance.** Offshore station grid, and white seabass larvae are likely rare in it (UNVERIFIED). Useful only as a spawning-season indicator.

### Fisheries-dependent catch data (notable addition for white seabass)
- **CRFS via RecFIN.** Catch, effort and interview-level data, publicly downloadable. Spatial unit is coarse (district or month). https://wildlife.ca.gov/Conservation/Marine/CRFS
- **Party-boat (CPFV) logbooks.** Block-level confidentiality is UNVERIFIED.
- **Sportfishing landing counts.** Daily per-landing white seabass counts, for example https://sportfishingreport.com/ytd/202/white-seabass/seawatch.php . This is probably the **strongest near-real-time "they're in" timing signal**. Terms for scraping are UNVERIFIED; treat it as a partnership target.
- **OREHP hatchery coded-wire tag recoveries.** 1,400 juveniles and 156 adults recovered; low relevance. https://wildlife.ca.gov/Conservation/Marine/OREHP/Evaluation

### Telemetry and acoustics
- **Movebank.** License set per study by the data owner, otherwise the general terms apply. You must accept the terms before download, including through the API. Public studies use CC licenses. Commercial use is a per-study matter. Useful mainly for bird migration. https://www.movebank.org/cms/movebank-content/permissions-and-sharing
- **White seabass acoustic tag detections.** Southern California / Animal Telemetry Network (ATN) detections: I found no public feed.
- **PIER passive acoustic monitoring.** Has located white seabass spawning sites in SoCal kelp beds. Possibly a partner data source (UNVERIFIED access).

### Cetacean and sighting networks
- **Happywhale.** No official API; an unofficial CLI exists. Data is automatically transferred to OBIS-SEAMAP, so published data flows on to OBIS and GBIF. Research access through collaborator agreements.
- **Whale Alert / Ocean Alert (IFAW + Conserve.IO).** Sightings go to a central database. **Whale Safe** (UCSB Benioff lab) combines acoustic, visual and model inputs into blue-whale presence ratings for the Santa Barbara Channel, available by web and email only. https://whalesafe.com/methodology/
- **Acartia.** Open-source data cooperative covering CA to AK, with a real-time public API (account plus key). https://github.com/salish-sea/acartia
- **Spotting Giant Sea Bass (UCSB).** Photo-ID community science; an analogue model for fish. https://bosl.ucsb.edu/wp-content/uploads/2025/05/Using-community-science-to-assess-the-population-dynamics-and-spatial-ecology-of-the-giant-sea-bass-in-Southern-California.pdf

### Bird media
- **Macaulay Library.** No documented public API found. For eBird-uploaded media, Cornell will not sublicense commercially without the contributor's consent.
- **xeno-canto.** API v3 (`/api/3/recordings`) has needed a key since 2025-10-10. Recordings carry coordinates and dates. License is set per recording (mostly NC variants, UNVERIFIED).

## 3. Top recommendations
1. **Three-layer data architecture.**
   - **Historical prior:** GBIF monthly Parquet snapshot plus OBIS. Filter by license into a commercially safe layer (CC0/CC BY) and a non-commercial layer (CC BY-NC), and keep a per-record license field.
   - **Effort-corrected baseline:** SBC MBON integrated fish, REEF, KFM and Reef Check for white seabass; EBD + SED zero-filled for birds.
   - **Live layer:** iNat v2 incremental pulls (`updated_since`, ≤30–60 req/min, cached) and the eBird API. Add landing-count data for white seabass if a partnership is secured.
2. **Fit models on detection/non-detection data with effort**, not presence-only data. Use iNat/GBIF presences as a bias-corrected supplement, for example with a target-group background.
3. **Decide early whether wildlife-radar is "commercial".** Any for-profit operator counts as commercial under the eBird terms, and iNat restricts commercial use and commercial AI training. If commercial, seek written permission from Cornell (eBird) and iNat, and pursue data-sharing agreements with REEF and Reef Check.
4. **Respect geoprivacy end to end.**
   - Drop or down-weight records that are obscured or have positional accuracy worse than about 1 km for fine-scale predictions.
   - Never try to de-obscure.
   - Do not output finer locations than the source does for sensitive taxa (eBird sensitive species, giant sea bass).
5. **Build citation into the pipeline.** Store GBIF download DOIs, register derived-dataset DOIs, and keep per-source attribution strings.

## 4. Open questions and risks
- **Commercial terms (eBird, iNat, Macaulay, CC BY-NC records) are the biggest legal risk.** Exact current iNat Terms wording is UNVERIFIED; get legal review.
- **iNat says the API is not for scraping**, and no v1 sunset date has been announced. Heavy multi-species polling may be blocked. Prefer GBIF or AWS for bulk and the API for small incremental updates.
- **Data sparsity for white seabass.** The species roams mid-water in kelp, so transect surveys are probably zero-inflated, and iNat counts are likely small (couldn't query). Pull actual counts as a first spike.
- **Latency mismatch.** Survey programs lag 1–2 years, eBird on GBIF lags about a year, and the iNat API is live. Near-real-time white seabass signals mostly come from fishing reports, which have unclear terms.
- **Unverified items:** iNat daily and media limits; eBird `back` / `dist` limits and API sensitive-species handling; EOD license on GBIF; REEF and Reef Check licenses; whether OBIS ever requires a key; xeno-canto license mix.
- **Ethics/regulatory crossover.** Publishing white seabass aggregation or spawning timing may increase targeting (the ethics agent covers this).
