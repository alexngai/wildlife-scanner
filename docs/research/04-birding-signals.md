# Wildlife Scanner: birding data sources and predictive signals

**How this was checked.** Most official sites were unreachable for direct fetch in this session: science.ebird.org, birds.cornell.edu, ebird.github.io, CRAN, the eBird Postman docs and app.birdweather.com all failed. github.com worked. Web search worked until the shared 200-search budget ran out partway through. Facts confirmed in this session have a source URL next to them. Anything marked **UNVERIFIED** comes from memory and should be re-checked once those hosts are allowed.

**Overall picture:** the most valuable bird data (all eBird products, BirdNET models) is **non-commercial only, unless Cornell gives written permission**. The radar, weather, phenology and land data are open.

## 1. Summary table

| Source | What it gives | Resolution / coverage | Latency / forecast? | Access | Commercial use | Relevance |
|---|---|---|---|---|---|---|
| eBird Status & Trends (S&T) | Expected weekly occurrence, count and relative abundance; seasonal ranges | 3, 9 and 27 km; 52 weeks; global; about 2,900+ species (2023 version) | Average for a typical year; released yearly | `ebirdst` R package plus access key | Needs written permission; redistribution restricted | **High** (prior) |
| eBird API 2.0 | Recent, notable, historic-date and nearest observations; checklist feeds; hotspots; species lists | Point/hotspot; ≤30 days back; ≤50 km radius | Near real-time (minutes to hours) | Free key, sent in a header | Non-commercial only | **High** (nowcast) |
| eBird bar charts / EBD | Weekly detection frequency; full checklist data | Region or hotspot; 48 periods per year | Bar charts are live on the web; EBD is a periodic bulk file | Bar charts: logged-in web download only. EBD: request form | Non-commercial; derived products restricted | High (prior/training) |
| BirdCast | Nightly migration forecast (3 nights); live migration maps; county dashboard | Lower 48; about 143 radars | Forecast updated every 6 h; seasonal only | Web only; **no API found** | Images shareable with citation; reuse otherwise unclear | Med (benchmark/UX) |
| NEXRAD Level II (AWS) | Raw volume scans | About 160 radars; around 5-minute scans | Real time | S3 `unidata-nexrad-level2` (+ `-chunks`) | Open | **High** (migration signal) |
| Dark Ecology dataset | Bird density from every US radar scan, 1995–2025 | Daily, 5-minute, per-scan, vertical profiles | Historic | Zenodo / UMass | **CC BY 4.0** | **High** (training) |
| vol2bird / bioRad / wsrlib / MistNet | Turn radar into bird profiles; separate rain from birds | Per radar | Your own pipeline | GitHub | MIT (vol2bird), GPL-3 (wsrlib) | High (tooling) |
| Weather (GFS/HRRR, fronts, wind) | Migration and fallout drivers | 3 km (HRRR) | Forecast | NOAA | Open | **High** |
| NOAA tides (CO-OPS) | Tide height predictions | Station-level | Forecast | REST, no key | Open | High (shorebirds) |
| USA-NPN | Spring Index (first leaf/bloom), growing degree days, observations | 4 km gridded | Daily, plus 6-day forecast | GeoServer WMS/WCS; REST; `rnpn` | Data-use policy (UNVERIFIED) | Med |
| VIIRS / MODIS phenology | Green-up dates, NDVI/EVI | 500 m | Yearly / 8–16 days | Earthdata, Google Earth Engine | Open | Low–Med |
| Motus | Detections of radio-tagged birds at receivers | Receiver network | Near real-time | `motus` R package; per-project permission | Collaboration policy | Low |
| Movebank | GPS tracks | By study | Varies | API with login; per-study licences | Varies (UNVERIFIED) | Low |
| Rare-bird alerts (eBird RBA/Needs, ABA, listservs, Discord) | Rarity reports | Varies | Minutes to days | Email / web; no API except eBird "notable" | Content owned by posters | Med (use eBird notable only) |
| HawkCount (HMANA) | Daily raptor counts with weather | About 300 sites (UNVERIFIED) | Same day | Web export (UNVERIFIED) | Ask permission (UNVERIFIED) | Med (raptors) |
| CBC / BBS | Winter / breeding survey counts | Count circles / survey routes | Once a year | Audubon request / USGS ScienceBase | CBC non-commercial; BBS public domain (UNVERIFIED) | Low |
| BirdWeather (BirdNET stations) | Acoustic detections from listening stations | Over 18,000 stations (Feb 2026); over 2 billion detections | Real-time | GraphQL, no key | Data terms unknown | **Med–High** (presence) |
| BirdNET models | Sound ID model; geographic species filter | About 6,500 classes | — | GitHub | **CC BY-NC-SA 4.0** (models) | Med |
| Merlin Sound ID | On-device sound ID | — | — | No public API (UNVERIFIED) | — | Low |
| xeno-canto | Bird recordings | Global | — | API v3, **key required since 2025-10-10** | Licence per recording, often NC (UNVERIFIED) | Low |
| NLCD / PAD-US / eBird hotspot metadata / OSM | Land cover; public land and access status; site list | 30 m; national | Yearly | Download / API | Public domain; OSM is ODbL | Med (site ranking) |

## 2. Source details

### eBird Status & Trends
- **What it is:** weekly modelled occurrence, count and relative abundance (with 10th–90th percentile intervals), plus proportion of population, seasonal range polygons, regional statistics, 19 model-performance metrics and data-coverage layers.
- **Resolution and formats:** rasters at 3, 9 and 27 km as GeoTIFF in the Equal Earth projection; ranges as GeoPackage; regional statistics as CSV.
- **Versions:** the latest Status version is **2023**, published 30 April 2025 (ebirdst 3.2023.0 is dated 2025-05-07). The package is now at 4.2023.1. Trends products are still at 2022 (27 km).
- **2024 version:** the GitHub NEWS file shows no 2024 data version → **UNVERIFIED whether one exists.**
- **Species count:** about 2,980 species for 2023, per a CRAN-mirror vignette (not cross-checked).
- **Access:** request a key at ebird.org/st/request. Keys are issued immediately *unless commercial use is requested*. Then call `set_ebirdst_access_key()`.
- **Terms (October 2023, still in effect as far as I could tell):**
  - Commercial use "is not covered… requires the prior written permission" of the Cornell Lab (ebird@cornell.edu).
  - Redistributing products or modified products through websites, documents or APIs is prohibited, except:
    - peer-reviewed publications (unlimited species);
    - modified products from peer-reviewed work based on up to 25 products;
    - educational materials covering up to 100 species.
  - Any other purpose needs written permission, and the most restrictive applicable use governs.
  - **So a public web app that serves S&T-derived maps needs Cornell's permission, even if non-commercial.**
- Sources: https://ebird.org/about/products-access-terms-of-use, https://github.com/ebird/ebirdst (README, NEWS.md, vignettes/articles/status.qmd).
- **Caveat for forecasting:** S&T describes a multi-year *typical* year. It is a prior, not a nowcast.

### eBird API 2.0 (https://documenter.getpostman.com/view/664302/S1ENwy59)
- **Endpoints useful for prediction:**
  - `data/obs/{region}/recent[/{species}]` and `data/obs/geo/recent`: `dist` 0–50 km, `back` 1–30 days, up to 10,000 rows (limits confirmed from rebird source).
  - `data/obs/{region}/recent/notable` and `geo/recent/notable`: the rare-bird feed, including review/validity flags.
  - `data/nearest/geo/recent/{species}`.
  - `data/obs/{region}/historic/{y}/{m}/{d}`.
  - `product/lists/{region}[/{y}/{m}/{d}]` (checklist feed) and `product/checklist/view/{subId}`. Pulling full checklists lets you infer **non-detections** on complete checklists, but at a high request cost.
  - `product/spplist/{region|hotspot}`, `product/stats`, `product/top100`.
  - `ref/hotspot/{region}`, `ref/hotspot/geo`, `ref/hotspot/info/{locId}`, `ref/region/*`, `ref/taxonomy`.
- **Bar chart / frequency data is NOT in the API.** The rebird function `ebirdfreq()` is defunct: "you now need to be logged into the eBird website to download frequency data… we cannot authenticate via the API." Frequency means the share of complete checklists per "week", with four "weeks" per month (https://github.com/ropensci/rebird). The supported route is the EBD/sampling-event bulk download (request form, non-commercial), parsed with `auk`.
- **Rate limits:** not officially published. Clients back off on HTTP 429, and the ProjectBabbler wrapper warns that excessive use can get an account banned (https://github.com/ProjectBabbler/ebird-api).
- **Terms** (https://www.birds.cornell.edu/home/ebird-api-terms-of-use/, last edited October 2021):
  - Non-exclusive, revocable licence for non-commercial use.
  - "You will not use the API or API Content… for commercial purposes whatsoever without prior written permission."
  - "Commercial purposes" includes any use by or to assist a commercial entity.
  - Downloading API content is limited to a single copy on a single device, for personal non-commercial use. Server-side caching is not addressed (UNVERIFIED).
  - Attribution to eBird is required.
- **EBD terms** (https://www.birds.cornell.edu/home/ebird-data-access-terms-of-use): commercial reproduction of eBird data "or any products derived from it" is prohibited without permission. A dataset requested for one purpose cannot be reused for another.
- **Sensitive species:** eBird hides or obscures locations for sensitive species in the API (UNVERIFIED in this session).

### BirdCast (https://birdcast.org)
- **Products:**
  - Forecast maps of nocturnal migration about 3 hours after sunset, for 3 nights ahead, refreshed every 6 hours, driven by GFS weather.
  - Live maps built from about 143 NEXRAD radars (about 100 GB per night).
  - County dashboard showing birds that crossed each county the previous night: https://dashboard.birdcast.info.
  - Lights Out alerts.
- **Seasons:** spring and fall only; fall products stop around 15 November. Sources disagree on whether that is 15 or 30 November.
- **Reuse:** images are "free to share" on social media, TV and broadcasts with citation. **I found no public API or bulk download, and no licence covering data reuse.** Don't scrape the dashboard's JSON; ask the BirdCast team for a partnership.
- **Benchmark:** the forecast model follows Van Doren & Horton (2018, *Science*, doi 10.1126/science.aat7526). It used 12 weather variables, with temperature the most important. It explains about 80% of the variation in migration intensity and stays useful up to 7 days ahead.

### NEXRAD and radar tooling
- **Data:** the Level II archive moved to `s3://unidata-nexrad-level2`, and the old `noaa-nexrad-level2` bucket was retired on 2025-09-01. The real-time bucket is `unidata-nexrad-level2-chunks`, with an SNS topic (https://registry.opendata.aws/noaa-nexrad/, Unidata notice of August 2025).
- **Dark Ecology dataset** (https://github.com/darkecology/darkeco-dataset, v1.1.0):
  - Bird activity in **every US radar scan, 1995–2025**, as daily (160 MB), 5-minute (16 GB), per-scan (12 GB) and per-year vertical-profile (5–10 GB each) archives.
  - **CC BY 4.0**, downloadable from Zenodo or UMass.
  - This is the single best open training set for migration intensity.
  - There is also a Dryad dataset for 16 coastal radars, 2014–2023 (doi 10.5061/dryad.zcrjdfnrr).
- **Tools:**
  - vol2bird (C, MIT): includes `rsl2odim` to convert NEXRAD files, and `libmistnet`. Used through the bioRad R package.
  - wsrlib (MATLAB, GPL-3; v1.0.0 in 2026).
  - MistNet: a convolutional network that separates rain from birds.
  - Europe: aloft/BALTRAD covers 141–151 radars, 2008–2023, in VPTS CSV format on Zenodo and aloftdata.eu, updated daily. Radar cannot tell birds from insects or bats.
- **Feasibility for a small team:**
  - **Historic:** easy (download Dark Ecology).
  - **Live, regional:** feasible. Run vol2bird in Docker every hour at night on about 6 SoCal radars: KNKX, KSOX, KVTX, KVBX, KEYX and KYUX (station IDs UNVERIFIED). That is roughly 100 volumes per radar per night.
  - **Live, national:** a substantial data-engineering effort (BirdCast-scale, about 100 GB per night).
  - **Recommended:** start regional.

### Weather drivers (how well established)
- **Very well established:**
  - Nocturnal migration intensity rises with warm temperatures, tailwinds and no rain (radar studies, Van Doren & Horton).
  - Shorebirds concentrate at roosts around high tide. Observers usually start about 1 hour before high tide, and the flooding threshold is site-specific (e.g. Dunlin leave flats above about +5 ft). Use NOAA CO-OPS tide predictions.
- **Well established but harder to model:**
  - Rain or a front during heavy flight causes "fallouts" at barrier coasts and migrant traps (Gulf Coast, Point Loma, desert oases).
  - Cold fronts drive fall raptor and passerine pulses; HawkCount totals rise after fronts.
  - Onshore and storm winds push seabirds within sight of shore for seawatching, including lake-effect and Great Lakes jaeger/gull events and hurricane "wrecks".
  - Upwelling, SST fronts and chlorophyll concentrate seabirds in the California Current (pair this with the ocean agent's data).
- These relationships are mostly correlational and documented in the literature or anecdotally. Only migration intensity has a published operational forecast.

### Phenology
- **USA-NPN:**
  - Spring Index first-leaf/first-bloom maps at 4 km from PRISM, with current-year, **6-day forecast** and anomaly-versus-1991–2020 layers, plus growing degree days.
  - Access through GeoServer WMS/WCS, a REST data API and `rnpn`.
  - Data-use policy at usanpn.org/terms#DataUse (contents UNVERIFIED).
  - Sources: https://usanpn.org/data/maps/spring, https://pubs.usgs.gov/publication/ofr20171003.
- **Satellites:**
  - VNP22Q2 v2 green-up dates at 500 m (yearly; v1 retired 2025-07-31).
  - **Suomi NPP product delivery ended about 1–2 November 2026.**
  - MODIS science data collection stops around February 2027 (Terra) and September 2027 (Aqua). LAADS and the CAMS article differ on Terra's date.
  - Use NOAA-20/21 VIIRS or HLS/Sentinel-2 NDVI instead.
- **Use for prediction:** a weak-to-moderate covariate for spring timing anomalies (e.g. an early or late warbler peak). Use growing degree days as a proxy for insect emergence; there is no national insect-emergence feed.

### Tracking
- **Motus:**
  - Detections of radio-tagged birds at receivers. Basic project and tag summaries are public; detection data comes through the `motus` R package (v6.1.2, GPL-3) under project-level permissions and a collaboration policy (https://docs.motus.org).
  - Good for storytelling ("a tagged Swainson's Thrush passed here"). It is not a predictor.
- **Movebank:** per-study licences, login for the API, and many restricted studies. The published Data Repository uses CC0/CC BY (UNVERIFIED). Low relevance.

### Rare-bird alert networks
- **eBird Rare Bird Alerts and Needs Alerts:** emailed hourly or daily and tied to an account. They are built on the same "notable" data, so **use the API's notable endpoint instead**.
- **ABA Rare Bird Alert, state listservs (Groups.io, Google Groups), Discord and WhatsApp:** content belongs to the posters, groups are often private, and scraping breaks platform terms and community norms (UNVERIFIED per group). **Recommendation:** don't ingest them; at most, link out to public lists.

### Surveys
- **HawkCount / HMANA** (hawkcount.org): daily site counts with weather. Medium value for raptor timing; terms UNVERIFIED.
- **CBC** (Audubon): data by request, non-commercial terms (https://www.audubon.org/content/policy-regarding-use-christmas-bird-count-data).
- **BBS** (USGS ScienceBase): yearly, public domain (UNVERIFIED). Both CBC and BBS are low value next to S&T.
- **Pelagic trip reports:** eBird pelagic-protocol checklists plus operator blogs (no API). Medium value for the seabird vertical.

### Audio
- **BirdNET-Analyzer:** code is MIT; **models are CC BY-NC-SA 4.0**; about 6,512 classes (https://github.com/birdnet-team/BirdNET-Analyzer). Its geographic species-filter model is trained on eBird data (UNVERIFIED).
- **BirdWeather:**
  - GraphQL at app.birdweather.com/graphql, no key needed.
  - Over 18,000 stations as of February 2026 and over 2 billion detections. Detections are filterable by box, species, date and confidence; station locations are fuzzed (https://github.com/brentpease1/birdweatheR).
  - **Its data-use and commercial terms were not found → ask support@birdweather.com.**
  - A strong near-real-time presence signal for vocal and nocturnal species, but it needs false-positive control: per-species precision and confidence thresholds.
- **Merlin:** no public data feed (UNVERIFIED).
- **xeno-canto:** API v3 requires a key since 2025-10-10. Licences are set per recording (many NC; UNVERIFIED). Useful for training and audio playback, not for presence.

### Habitat and access
- **eBird hotspot metadata** (`ref/hotspot`): location ID, coordinates, species seen all-time, latest observation date. This is the natural "site" unit.
- **PAD-US** (USGS): public and protected lands with a public-access field (Open/Restricted/Closed).
- **Annual NLCD** (30 m) and OSM for trails and parking.
- PAD-US and NLCD are public domain (versions UNVERIFIED).

## 3. Recommended modeling approach

A layered Bayesian "prior → nowcast → driver" stack, scored per **hotspot × day × species**:

1. **Seasonal prior.** Expected weekly occurrence per hotspot from S&T (3 km) if Cornell permits it. Otherwise, build your own from an EBD/sampling-event request using a GLM/GAM on effort-corrected detection frequency; the bar-chart equivalent is the % of complete checklists. Shrink sparse hotspots toward the S&T cell.
2. **Nowcast update.** A dynamic occupancy / state-space update:
   - **Inputs:** recent detections from the API (≤30 days) and non-detections from complete checklists in the checklist feed. Weight non-detections by effort, using species-specific detection probabilities estimated from the EBD.
   - **Rarities:** a **persistence ("chase-ability") model**, P(still present on day *t+k* | reported, days since last report, taxon, habitat, season). Train it as survival analysis on historical notable records followed by repeat reports. eBird does not offer this, and it is a clear differentiator.
3. **Migration-intensity driver.**
   - Train on Dark Ecology (CC BY) radar series against GFS/HRRR covariates: 850 hPa wind relative to the seasonal heading, temperature, precipitation and pressure change. Predict nightly migration for each radar 1–7 days ahead; this is a re-implementation of the published method.
   - Allocate that volume to species using S&T weekly abundance change and migratory status.
   - Add a **"morning-after / fallout index"**: heavy flight, then rain, a front or a sharp wind shift before dawn near barriers and migrant traps.
   - Calibrate against next-day eBird checklist lists in the following morning's checklists.
4. **Context modifiers.**
   - Tide windows for shorebirds (CO-OPS).
   - Onshore wind and storm indices for seawatching.
   - Ocean fields from the marine pipeline for pelagic trips.
   - Daily activity curves for each species from BirdWeather detections, to pick the best time of day.
   - Phenology anomaly (NPN) to shift the prior earlier or later in spring.
5. **Acoustic evidence.** Add BirdWeather detections as a likelihood term with per-station, per-species false-positive rates. Use it mainly for vocal, nocturnal or secretive species.
6. **Validation.**
   - Score against held-out complete eBird checklists, using Brier score, AUC and calibration per species and hotspot-day.
   - **Baseline:** bar-chart frequency, i.e. what eBird Targets uses.
   - Ship a feature only if it beats the baseline.

## 4. Birding MVP that adds value beyond eBird Explore, Targets and Merlin

**"Target Planner + Tonight's Flight", Southern California first** (shares infrastructure with the white seabass vertical):

- **Inputs:** target species (paste a list, or import the user's own eBird life-list CSV), home location, travel radius and date window.
- **Output:** a ranked hotspot × day × time-window table with a probability and plain-language drivers. Example: "68% · Point Loma · Thu 6–9am: heavy flight forecast Wed night over KNKX + front clearing; reported 2 days ago, persistence 55%; Open access (PAD-US)."
- **Modules:**
  1. **Rarity chase-ability** for current notable records.
  2. **Migration nights:** a 3–7 day outlook per radar, plus a morning fallout index for migrant traps such as Point Loma, Galileo Hill and Morongo Valley.
  3. **Shorebird tide planner:** best roost windows at Bolsa Chica, Upper Newport and Tijuana Estuary.
  4. **Seawatch / pelagic outlook:** wind plus upwelling/SST from the ocean pipeline.
- **Why this goes beyond the existing tools:**
  - Targets and Explore show historic monthly frequencies only, with no weather, no persistence and no day-level timing.
  - Merlin's location/date "likely birds" list is a static prior.
  - BirdCast is species-agnostic and has no site recommendations.
- **Ethics:** respect eBird's sensitive-species masking. Never show owl roosts or nests, coarsen locations for species flagged as sensitive, and link to the ABA Code of Birding Ethics.

## 5. Open questions and risks

1. **Commercial status decides everything.** The eBird API, EBD and S&T are all non-commercial only, and S&T forbids web redistribution even for non-commercial use without permission. **Contact ebird@cornell.edu before building on these.**
   - Possible fallback: the eBird Observation Dataset on GBIF, reportedly CC BY 4.0 (UNVERIFIED; check with the generic-biodiversity agent). It lacks some effort and non-detection detail.
2. **eBird API capacity:** rate limits are undocumented, and inferring non-detections takes many checklist calls. Use an EBD request for training and the API only for a thin live layer.
3. **Bar-chart data:** there is no API, and the web download needs a login. Do not automate login-based scraping.
4. **BirdCast:** no API and unclear reuse terms. Partner with them; don't scrape.
5. **S&T 2024 version:** whether it has been released is unverified. S&T is also a climatological prior, not real-time.
6. **Radar pipeline risk:** dealiasing, rain and insect contamination, and gaps in hand-off between radars. Mitigate by limiting the scope to a region and checking against Dark Ecology.
7. **Satellite continuity:** Suomi NPP products ended November 2026 and MODIS ends in 2027. Build on NOAA-20/21 VIIRS or HLS.
8. **BirdWeather and BirdNET:** BirdWeather's data terms are unknown and BirdNET models are NC licensed. Expect false positives and uneven station coverage.
9. **Alert networks:** listservs, Discord and WhatsApp raise terms and consent problems. Exclude them.
10. **Not verified in this session** (network and search limits): eBird Postman docs details, current eBird API attribution wording, Movebank, HawkCount and CBC terms, NLCD/PAD-US versions, xeno-canto licence mix, Merlin API absence, the eBird sensitive-species list, and the SoCal radar station IDs. To re-check them, allow science.ebird.org, birds.cornell.edu, ebird.github.io, documenter.getpostman.com, app.birdweather.com and cran.r-project.org in the session's network settings, and raise the web-search budget (it ran out partway through).

## Sources
- https://ebird.org/about/products-access-terms-of-use
- https://github.com/ebird/ebirdst
- https://www.birds.cornell.edu/home/ebird-api-terms-of-use/
- https://www.birds.cornell.edu/home/ebird-data-access-terms-of-use
- https://github.com/ropensci/rebird
- https://github.com/ProjectBabbler/ebird-api
- https://birdcast.org/migration-tools/migration-forecast-maps/
- https://dashboard.birdcast.info
- https://birdcast.org/creating-a-continental-bird-migration-forecast/
- https://registry.opendata.aws/noaa-nexrad/
- https://www.unidata.ucar.edu/blogs/news/entry/important-changes-to-noaa-nexrad
- https://github.com/darkecology/darkeco-dataset
- https://github.com/darkecology/wsrlib
- https://github.com/adokter/vol2bird
- https://datadryad.org/dataset/doi:10.5061/dryad.zcrjdfnrr
- https://pure.uva.nl/ws/files/329721269/s41597-025-04641-5.pdf
- https://usanpn.org/data/maps/spring
- https://www.earthdata.nasa.gov/data/catalog/lpcloud-vnp22q2-002
- https://ladsweb.modaps.eosdis.nasa.gov/learn/modis-to-viirs-transition/
- https://docs.motus.org/en/about-motus
- https://github.com/birdnet-team/BirdNET-Analyzer
- https://github.com/brentpease1/birdweatheR
- https://app.birdweather.com/api/
- https://pypi.org/project/xenocanto-api/
- https://www.audubon.org/content/policy-regarding-use-christmas-bird-count-data
- https://support.ebird.org/en/support/solutions/articles/48001255130-ebird-bar-charts-and-graphs
