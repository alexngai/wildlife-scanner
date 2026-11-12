# Wildlife-radar: environmental covariate sources (oceanographic, astronomical, weather)

**How this was checked.** I verified sources with WebSearch only, and the shared 200-search budget ran out before I finished. WebFetch could not reach `api.tidesandcurrents.noaa.gov` or `mjacox.com` because those hosts are not allowed in this session's network. I stopped trying other hosts after those two failures, so I did not run live smoke tests on any endpoint. Anything marked **UNVERIFIED** comes from memory or from a single secondary source. Check those before writing code against them.

## 1. Summary table

| Source | Covariates | Resolution | Obs / forecast and latency | Access | Auth / license | Relevance |
|---|---|---|---|---|---|---|
| NOAA CO-OPS Data API | Tide predictions, water level, water temp | Station points | Predictions run years ahead; obs every 6 min | REST `datagetter` (JSON/CSV) | None; public domain | **High** |
| Local harmonic tide calc (neaps, pyTMD, UTide) | Tide height at any time | Station points | Unlimited horizon | Library + NOAA `harcon.json` | OSS licenses (UNVERIFIED) | **High** (scale/fallback) |
| astronomy-engine / Skyfield / suncalc | Moon phase, illumination, rise/set, sun/twilight | Any lat/lon | Unlimited, offline | Library | OSS | **High** |
| USNO AA API v4 | Same as above | Point | Any date | REST | Public | Low (test oracle) |
| MUR SST `jplMURSST41` | Gap-free SST | 0.01° daily | Obs only; nominal 4-day latency; last 7 days revised | ERDDAP griddap; PO.DAAC/earthaccess | Public (NASA) | **High** |
| NOAA Geo-polar Blended SST | Gap-free SST | 0.05° daily | NRT (~1 day, UNVERIFIED) | ERDDAP (coastwatch.noaa.gov) | Public | Med-High |
| OISST v2.1 | SST and anomaly baseline | 0.25° daily | Preliminary at 1 day; final at +2 weeks | ERDDAP | Public | Med (climatology) |
| CDIP buoys and MOP model | Waves (Hs, Tp, Dp, spectra), SST | Points; 0.01° nowcast | Obs NRT; nowcast; experimental ECMWF-driven forecast | THREDDS/OPeNDAP, ERDDAP | Scripps, non-federal; license UNVERIFIED | **High** |
| NDBC | Wind, waves, water temp | Points | Obs NRT (45-day realtime files) | Text files; ERDDAP `cwwcNDBCMet` | Public | Med |
| SCCOOS Automated Shore Stations | Temp, salinity, chl at piers | Points, every 4–6 min | Obs NRT | ERDDAP tabledap | IOOS/UCSD (UNVERIFIED) | **High** (nearshore truth) |
| Del Mar mooring / mini-moorings | Temperature profile | Point | Obs, preliminary RT | ERDDAP | IOOS/UCSD | Med-High (thermocline) |
| CUGN Spray gliders | T/S profiles to ~500 m | Transects | Obs RT (L2 QC); delayed-mode months later | ERDDAP (gliders.ioos.us, spraydata.ucsd.edu) | IOOS | Low-Med |
| WCOFS (NOS ROMS) | 3-D temp, salinity, currents, sea level | ~2 km (UNVERIFIED) | 24 h nowcast + **72 h forecast** | AWS S3 `noaa-nos-ofs-pds` | Public | **High** |
| Copernicus Marine GLO PHY 001_024 | 3-D T/S, currents, SSH, MLD | 1/12° (~8 km); hourly surface | **10-day forecast**, daily | `copernicusmarine` toolbox, ARCO Zarr | Free account; free incl. commercial with attribution | **High** |
| VIIRS chl / Kd490 (CoastWatch) | Clarity proxies | 750 m daily | NRT | ERDDAP | Public | **High** |
| Sentinel-3 OLCI chl (CoastWatch) | Clarity proxy | 300 m daily (rolling 90 days) | NRT | ERDDAP | Sentinel attribution required | Med-High |
| HF radar (HFRNet) | Surface u/v currents | 0.5/1/2/6 km hourly | Obs only | ERDDAP `ucsdHfrW1`/`W2` | Public | Med |
| CUTI / BEUTI | Upwelling, nitrate flux | 1° latitude bins, daily | Obs; latency UNVERIFIED | ERDDAP (upwell.pfeg) | Academic/NOAA | Med |
| RONI/ONI, PDO | Climate state | Basin, monthly | Monthly | Text files | Public | Low-Med |
| Kelpwatch | Kelp canopy area | 30 m, quarterly | Obs; lags months | Web download; EDI | UNVERIFIED | Med-High |
| C-HARM v3.1 | HAB / domoic acid probability | 0.03° daily | Nowcast + **1–3 day forecast** | ERDDAP `wvcharmV3_*` | Public | Low-Med |
| CalHABMAP piers | Pseudo-nitzschia counts, domoic acid | Weekly at piers | Obs | ERDDAP `HABs-*` | IOOS | Low |
| NWS API | Wind, weather, precipitation forecast | 2.5 km grid (UNVERIFIED) | ~7-day forecast | REST JSON | Public; User-Agent required | **High** |
| Open-Meteo (weather + marine) | Wind, waves, SST, currents, sea level | 0.08–0.25° | 7-day default; up to ~10–15 days | REST JSON | Free non-commercial only; paid for commercial | **High** convenience, license risk |
| HRRR / RRFS | Hourly mesoscale weather | 3 km | 18–48 h (HRRR); 84 h (RRFS) | AWS NODD GRIB2 (Herbie) | Public | Low-Med (birding) |
| ERA5 / ARCO-ERA5 | Reanalysis weather | 0.25° hourly | ERA5T ~5–7 days; ARCO Zarr ~3 months | CDS API; GCS Zarr | Copernicus licence (free, attribution) | Med (training/backtest) |

## 2. Per-source details

### Tides
- **NOAA CO-OPS Data API.** Base URL is `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter`; CO-OPS moved its data services to the cloud ([web services info](https://tidesandcurrents.noaa.gov/web_services_info.html), [API docs](https://tidesandcurrents.noaa.gov/api/)).
  - Products: `predictions` (`interval=hilo|6|h`), `water_level`, `water_temperature`, `currents_predictions`.
  - Size limits per request: 6-minute data is limited to 1 month, hourly and high/low to 1 year, monthly means to 200 years.
  - No published rate limit (third-party catalogs agree). Pass `application=<org name>`.
  - Harmonic constants: `https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{id}/harcon.json?units=metric` ([MDAPI](https://api.tidesandcurrents.noaa.gov/mdapi/prod/)).
  - La Jolla 9410230, San Diego 9410170 and Los Angeles 9410660 are **harmonic** stations.
  - Subordinate stations give high/low only, via offsets that are updated quarterly ([help](https://tidesandcurrents.noaa.gov/PageHelp.html)).
  - Santa Monica 9410840 and Santa Barbara 9411340 are UNVERIFIED IDs.
  - Tidal current predictions in SoCal are mostly at bay entrances; I did not verify open-coast coverage.
  - Change notice: on 2026-10-01, sea level products moved to the Derived Product API ([SCN 26-79](https://www.weather.gov/media/notification/pdf_2026/scn26-79_CO-OPS_Sea_Level_Trend_Changes.pdf)).
  - Relevance: high. Predictions are deterministic, so fetch once and cache years ahead.
- **Computing tides locally.**
  - [Neaps](https://neaps.js.org) (`@neaps/tide-predictor`, TypeScript) takes NOAA constituents. Its `tide-database` refreshes NOAA stations monthly. It claims minute-level and centimetre-level agreement with NOAA predictions and says it is not for navigation.
  - [pyTMD](https://www.theoj.org/joss-papers/joss.08566/10.21105.joss.08566.pdf) (JOSS 2025) predicts from global tide models such as FES/TPXO, so it works at any point, not only stations.
  - UTide does harmonic analysis on your own series (version UNVERIFIED).
  - pytides is dormant (last release 0.0.3).
  - Recommendation: use NOAA predictions as the source of truth and neaps as a fallback or for arbitrary-time interpolation.

### Moon and sun
- **Compute locally; do not call an API.**
  - [astronomy-engine](https://www.npmjs.com/package/astronomy-engine) (JS/TS, Python, C, C#, identical algorithms). It has `MoonPhase` (ecliptic longitude), `SearchMoonQuarter`, `Illumination` (phase angle, from which you derive illuminated fraction), rise/set (`SearchRiseSet`, name UNVERIFIED), and moon distance (perigee).
  - [suncalc](https://github.com/mourner/suncalc) is tiny JS: `getMoonIllumination` gives fraction and phase, `getMoonTimes` handles no-rise/no-set days. Its illumination accuracy has documented issues, so use it client-side only.
  - Skyfield (Python) offers `almanac.moon_phase`, risings/settings and `fraction_illuminated`. Details are from memory (UNVERIFIED) because search ran out.
- **USNO API v4.0.1.** `https://aa.usno.navy.mil/api/<service>`, e.g. `/api/moon/phases/...`; dates are `yyyy-mm-dd` ([API](https://aa.usno.navy.mil/data/api), [changelog](https://aa.usno.navy.mil/data/api_changelog)). Use it only as a test oracle.
- Useful features: night-time illumination × moon altitude, minutes from moonrise, days from new/full moon, perigee, sun elevation and civil twilight.

### Sea surface temperature
- **MUR `jplMURSST41`** ([ERDDAP](https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41)).
  - 0.01° daily, 2002–present. Nominal 4-day latency: the 1-day NRT version was retired.
  - The most recent 7 days are revised daily, so backtests must use as-of data.
  - Cloud path: earthaccess with short name `MUR-JPL-L4-GLOB-v4.1`. Direct S3 works only inside us-west-2 ([earthaccess](https://earthaccess.readthedocs.io/en/latest/user-reference/api/api/)).
  - The AWS public MUR Zarr stops at 2020-01-20 ([registry](https://registry.opendata.aws/mur/)), so don't use it.
  - In a Saildrone validation off California/Baja, MUR bias was about 0.2 °C and OSTIA had the lowest RMSD at 0.36 °C ([preprint](https://www.preprints.org/manuscript/201905.0309/v1/download)).
- **Geo-polar Blended** ([product](https://coastwatch.noaa.gov/cwn/products/noaa-geo-polar-blended-global-sea-surface-temperature-analysis-level-4.html), ERDDAP `noaacwBLENDEDsstDaily`).
  - 0.05°, merges geostationary and polar-orbit data. Night-only, day/night and diurnal-warming variants.
  - Dataset IDs differ between mirrors (`nesdisBLENDEDsstDaily`, `noaacwBLENDEDCsstDaily`), so confirm in the live catalog.
  - Good low-latency complement to MUR.
- **OISST v2.1** (`ncdcOisst21NrtAgg` preliminary at 1 day; `ncdcOisst21Agg` final about 2 weeks later) ([ERDDAP](https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg.html)). 0.25° is too coarse for nearshore work but is the standard anomaly climatology.
- **Gotcha: nearshore cloud.** The May–Sept marine layer ("June gloom") blanks infrared SST nearshore, and L4 products then gap-fill and smooth fronts ([MDPI RS 15:2277](https://mdpi.com/2072-4292/15/9/2277)). Satellites also measure skin temperature, not temperature at 10–30 m. In-situ sources below are essential.
- **In situ SST:**
  - **CDIP buoys** report SST aligned to wave records ±15 min ([e.g. Torrey Pines Outer 100](https://cdip.ucsd.edu/m/products/parameter_table/?stn=100p1)); ERDDAP aggregate [`sst_agg`](https://erddap.cdip.ucsd.edu/erddap/tabledap/sst_agg.html).
  - **NDBC**: `https://www.ndbc.noaa.gov/data/realtime2/{id}.txt` holds 45 days, with missing values as `MM`; ERDDAP mirror `cwwcNDBCMet` ([NDBC](https://www.ndbc.noaa.gov/rt_data_access.shtml)). 46025 (Santa Monica Basin) is confirmed. I did not verify the current status of 46086 or 46232.
  - **SCCOOS Automated Shore Stations** (Scripps Pier and other piers): SBE16+ CTD and chl fluorometer every 4–6 min since 2005 ([SCCOOS](https://sccoos.org/autoss), ERDDAP [`autoss`](https://erddap.sccoos.org/erddap/info/autoss/index.html)).

### Subsurface temperature and thermocline
- **Del Mar mooring** (Scripps/SCCOOS): temperature, salinity, oxygen, currents, fluorescence ([mooring.ucsd.edu](https://mooring.ucsd.edu/delmar1/)).
  - ERDDAP `delmar_temperature` is labelled PRELIMINARY, no QA/QC.
  - The CeNCOOS copy `del-mar-mooring-1` is daily-averaged and ends July 2025.
  - Mini-moorings also exist (Del Mar, Imperial Beach, Point Loma).
- **CUGN Spray gliders.** Lines 66.7, 80 and 90 (90 is off Dana Point). Per-mission datasets on [gliders.ioos.us ERDDAP](https://gliders.ioos.us/erddap/) carry Level-2 real-time QC; 2026 missions exist on Lines 56 and 66.
  - The UCSD binned Line 90 product ends 2025-06-11 ([`binnedCUGN90`](https://spraydata.ucsd.edu/erddap/info/binnedCUGN90/index.html)).
  - These are offshore transects, useful for regional thermocline state but not site-specific.
- **WCOFS** ([info](https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html)). ROMS with 4D-Var assimilation of satellite SST and HF radar; RTOFS boundaries; NAM forcing.
  - 24 h nowcast + 72 h forecast, CF NetCDF. Sources conflict on 1 vs 4 cycles per day.
  - Files are on AWS `s3://noaa-nos-ofs-pds/wcofs/netcdf/YYYY/MM/DD/` (layout since 2025-01-01; file names changed Sept 2024) ([registry](https://registry.opendata.aws/noaa-ofs/)).
  - Grid is ~2 km (UNVERIFIED). Curvilinear ROMS grid, so regrid it.
  - It is the only regional 3-D forecast, and C-HARM v3 already uses it.
- **Copernicus Marine GLO PHY 001_024** ([product](https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_PHY_001_024/description)). 1/12°, 10-day 3-D forecast updated daily.
  - Hourly surface temperature, currents and SSH in dataset `cmems_mod_glo_phy_anfc_0.083deg_PT1H-m`; daily 3-D T/S, currents and MLD.
  - Too coarse for individual kelp beds but good for multi-day trend and anomaly.
  - SCCOOS ROMS (JPL/UCLA) status is UNVERIFIED; I believe it is retired.

### Water clarity and diver visibility
- **VIIRS (S-NPP/NOAA-20) chl-a OC3 and Kd490, 750 m daily NRT** on [coastwatch.noaa.gov ERDDAP](https://coastwatch.noaa.gov/erddap/). Sectors are lettered: UY appears to cover the West Coast, but I did not verify a Kd490 dataset for UY.
- **Sentinel-3 OLCI chl, 300 m** (`noaacwS3AOLCIchlaSectorDIDaily`, covering 30–45°N, 120–100°W). It keeps a rolling 90 days and requires the attribution "Contains modified Copernicus Sentinel data" ([info](https://coastwatch.noaa.gov/erddap/info/noaacwS3AOLCIchlaSectorDIDaily/index.html)). Archive it yourself.
- **MODIS sunset.** Aqua ends ~Sept 2027 and Terra ~Feb 2027 ([NASA transition](https://www.earthdata.nasa.gov/learn/articles/modis-to-viirs-transition)), so build on VIIRS and OLCI. PACE OCI availability on ERDDAP is UNVERIFIED.
- **Swell and surge:**
  - CDIP buoys (obs).
  - CDIP MOP swell nowcast (0.01°, last 6 h, ~2 h old). The [experimental coastal forecast](https://cdip.ucsd.edu/m/classic_models/nowcast) uses ECMWF to drive CDIP propagation to the 10 m depth contour.
  - THREDDS `socal_nowcast_spectra.nc` was last modified 2024-11-14, so it is possibly stale ([catalog](https://thredds.cdip.ucsd.edu/thredds/catalog/cdip/model/MOP_grids/catalog.html)).
  - For multi-day forecasts, Open-Meteo marine (ECMWF WAM / MeteoFrance) is simplest.
- **Rain and runoff turbidity.** No dedicated product was found. Use NWS QPF plus observed precipitation as a rule-based "≤72 h after ≥0.1 in rain" flag. The county advisory convention behind that rule is UNVERIFIED. USGS stream gauges are an UNVERIFIED option.
- **Existing "dive visibility" products are all commercial/prior art:** DiveViz, DiveSight, Element, VizReport, Fish & Dive Conditions ([DiveViz](https://divernet.com/scuba-news/get-underwater-dive-condition-forecasts-from-the-diveviz-app)). Their chl thresholds (<0.5 mg/m³ for blue water, >1.0 for poor) are anecdotal marketing. No public authoritative product exists, so this is a modelling opportunity. Diver reports would be the label source.

### Currents
- **HF radar.** SCCOOS runs the stations from San Luis Obispo to the Mexico border. Hourly surface currents (upper ~0.3–2.5 m) at 0.5/1/2/6 km ([SCCOOS](https://sccoos.org/high-frequency-radar/)); ERDDAP `ucsdHfrW1` and `ucsdHfrW2` ([W2](https://coastwatch.pfeg.noaa.gov/erddap/griddap/ucsdHfrW2)).
  - The West Coast 6 km catalog entry shows coverage only to 2022 (UNVERIFIED whether that is just stale metadata).
  - Obs only, with coverage gaps near the coast. Use for upwelling fronts and plume transport; for forecasts use WCOFS or CMEMS currents.

### Upwelling and climate indices
- **CUTI / BEUTI** (Jacox et al. 2018). Daily, 31–47°N in 1° bins, 1988–present. ERDDAP [`erdCUTIdaily`](https://upwell.pfeg.noaa.gov/erddap/griddap/erdCUTIdaily.html) and `erdBEUTImonthly` (monthly data seen to 2026-06).
  - Update latency UNVERIFIED; mjacox.com was blocked in this session. Use the 33°N bin for SoCal.
- **ENSO.** CPC switched to the **Relative ONI (RONI)** effective 2026-02-01 ([PNS](https://weather.gov/media/notification/pdf_2026/pns26-05_Relative_ONI.pdf)). File: `cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt`. The legacy `oni.ascii.txt` is still updated. Historical event classes changed.
- **PDO.** [NCEI PDO](https://www.ncei.noaa.gov/access/monitoring/pdo/) (ERSSTv5-based, monthly); CPC also publishes a [GODAS PDO file](https://www.cpc.ncep.noaa.gov/products/GODAS/multiora/index/mnth.ersstv5.clim19912020.pdo_current.txt). The UW/JISAO series is no longer updated.

### Kelp canopy
- **[Kelpwatch](https://kelpwatch.org).** Landsat, 30 m, seasonal (quarterly) from 1984. Free download through the web UI; no documented API.
  - Research data are on EDI (DOI 10.6073/pasta/93b47266b20bc1782c8df9c36169e372).
  - One listing says coverage runs to 2025, so lag is likely 1–2+ quarters (UNVERIFIED). A Landsat 9 safehold in Oct 2025 delayed some products ([USGS](https://www.usgs.gov/landsat-missions/news/landsat-9-products-impacted-2025-safehold-now-available)).
  - License UNVERIFIED.
- **Gotcha:** 1 m of tide reduces detected canopy by 15–30% ([Frontiers 2020](https://www.frontiersin.org/article/10.3389/fenvs.2020.587354)).
- **Historical alternatives:** CDFW aerial surveys (1989, 1999, 2002–2016) and MBC Bight surveys ([CDFW](https://wildlife.ca.gov/Conservation/Marine/Kelp/Monitoring)). Sentinel-2 kelp products: none found.

### Harmful algal blooms
- **C-HARM v3.1.** Probabilities of Pseudo-nitzschia ≥10k cells/L, particulate domoic acid ≥500 ng/L, and cellular domoic acid ≥10 pg/cell. 0.03° grid, WCOFS-driven.
  - ERDDAP `wvcharmV3_0day` (nowcast) and `_1day`, `_2day`, `_3day` ([ERDDAP](https://coastwatch.pfeg.noaa.gov/erddap/griddap/wvcharmV3_3day.html), [SCCOOS](https://habs.sccoos.org/hab-forecast)).
- **CalHABMAP.** Weekly net tows at piers including Scripps, Newport, Santa Monica and Stearns Wharf; one ERDDAP dataset per pier (`HABs-*`) on erddap.sccoos.org; bi-monthly [bulletins](https://sccoos.org/california-hab-bulletin/january-february-2026/).
- Relevance: low for seabass presence; moderate as a water-quality/safety layer.

### Wind and weather
- **[NWS API](https://www.weather.gov/documentation/services-web-API).**
  - A User-Agent header is required; requests without one are blocked.
  - The rate limit is undisclosed; retry after ~5 s.
  - Flow: `/points/{lat},{lon}` then `/gridpoints/{wfo}/{x},{y}/forecast` (and `/forecastGridData` for raw hourly wind, precipitation and sky cover).
  - The marine-zone endpoint (coastal waters forecast for PZZ zones from LOX/SGX) is UNVERIFIED.
- **[Open-Meteo Marine](https://open-meteo.com/en/docs/marine-weather-api).**
  - Wave, swell and wind-wave height/period/direction; `sea_surface_temperature` (MeteoFrance, 0.08°, hourly, 10-day); `ocean_current_velocity` (SMOC 0.08°, 10-day); `sea_level_height_msl` (includes tides, "not for coastal navigation").
  - 7-day default; ECMWF WAM 0.25° goes to ~15 days. The exact max `forecast_days` is UNVERIFIED.
  - **Free tier is non-commercial only** ([terms](https://open-meteo.com/en/terms)). Commercial use needs a paid plan; prices were not shown on the official pages, and third-party figures conflict. The ~10k calls/day free limit is unofficial.
- **HRRR** (3 km, AWS NODD since 2014, via [Herbie](https://herbie.readthedocs.io/)) is not retired. **RRFS v1** (3 km, 84 h) replaces NAM, HREF, SREF and HiresW; its implementation date slipped from Aug 31 to Oct 6 to Nov 3, 2026 ([SCN 26-048](https://www.weather.gov/media/notification/pdf_2026/scn26-48_RRFS_and_REFS_Implementation.pdf)).
- **ERA5.**
  - CDS API: new system, and ERA5 data from January 2025 had a degradation that was being corrected ([forum](https://forum.ecmwf.int/t/era5-data-from-1st-january-2025-was-degraded-and-is-being-corrected/10689)).
  - [ARCO-ERA5](https://github.com/google-research/arco-era5) on GCS `gcp-public-data-arco-era5` (us-central1, Zarr v3): monthly with ~3-month lag. ERA5T has ~5–7 day latency.
  - Earthmover offers an Icechunk ERA5 on AWS with daily ERA5T.
  - Birding uses: frontal passages, wind direction and precipitation from NWS/HRRR for forecasts, ERA5 for training.

### Access patterns in general
- **ERDDAP** is the workhorse: griddap/tabledap, bbox subset, NetCDF/CSV/JSON, no auth. Use the `erddapy` Python client.
- **Copernicus Marine.** Free account. Python/CLI toolbox `copernicusmarine` v2 with `subset` and `open_dataset` (lazy xarray). ARCO Zarr comes in two layouts: "timeChunked" for maps and "geoChunked" for point time series ([ARCO intro](https://help.marine.copernicus.eu/en/articles/12332770-introduction-to-the-arco-format)).
  - Free including commercial use with the credit line "E.U. Copernicus Marine Service Information" plus the DOI ([licence](https://marine.copernicus.eu/user-corner/service-commitments-and-licence)). The service is funded to 30 June 2028.
- **NASA Earthdata.** Earthdata Login plus `earthaccess`. Direct S3 only in us-west-2; elsewhere HTTPS, OPeNDAP or Harmony subsetting. Format is NetCDF4/HDF5; kerchunk/virtualizarr give Zarr-like access.
- **NOAA NODD.** Anonymous S3 for OFS, HRRR and RRFS.

## 3. Recommended minimum viable covariate stack (SoCal marine MVP)

Area of interest: Point Conception to the border, about 32.5–34.6°N, 121–117°W. Build daily per-site features on a ~1 km coastal grid plus about 20 named dive sites.

1. **Astronomy (local, zero dependencies on external services).** astronomy-engine, in either TS or Python. Moon phase angle, illuminated fraction, moon altitude at night, rise/set, perigee distance, sun/twilight. Unit-test against the USNO API.
2. **Tides.** CO-OPS predictions (high/low + hourly) for 4–6 harmonic stations, fetched 2 years ahead and refreshed quarterly; each site maps to its nearest station. Neaps with `harcon.json` as fallback. Features: tidal range (spring/neap), slack timing, stage at dawn.
3. **SST now.** MUR (spatial, gap-free) + Geo-polar Blended (latency) + in-situ truth: CDIP SST, SCCOOS shore stations, NDBC. Add OISST climatology for anomalies and 7- to 30-day trends.
4. **Temperature forecast and thermocline.** Copernicus GLO PHY (10-day, MLD, temperature at depth) + WCOFS (72 h, finer grid). Add the Del Mar mooring as a thermocline validation point.
5. **Clarity.** VIIRS Kd490/chl (750 m) and OLCI chl (300 m). Composite over 1–3 days for clouds and archive daily, because of OLCI's rolling 90-day window. Combine with CDIP swell height and period (obs + Open-Meteo/ECMWF forecast) and a rain/runoff flag from NWS precipitation.
6. **Weather.** NWS gridpoint forecast (wind, precipitation) as primary. Open-Meteo for prototyping only until a commercial license is settled.
7. **Context (low frequency).** CUTI/BEUTI daily at 33°N; RONI and PDO monthly; Kelpwatch quarterly canopy as a habitat mask/prior.
8. **Defer.** HF radar, gliders, C-HARM/HABMAP, ERA5 (add ERA5 when training historical models).

Ingestion: scheduled Python workers using `erddapy`, `copernicusmarine`, `earthaccess`, `xarray` and `s3fs`, writing to Zarr/Parquet. Store **as-of snapshots** so backtests don't leak revised data (MUR's 7-day revisions, OISST preliminary to final, ERA5T to ERA5).

## 4. Open questions and risks

- **IOOS funding is the top risk.** The FY26 proposal zeroed IOOS regional funding, and FY27 does again ([GCOOS](https://gcoos.org/federal-funding-2027/)). The 2021–2026 cooperative agreements ended June 30, 2026, and lags were reported in Dec 2025 ([Inside Climate News](https://insideclimatenews.org/news/08122025/noaa-integrated-ocean-observing-system-funding/)). SCCOOS shore stations, HF radar, gliders, HABMAP and possibly CDIP are exposed; a July 2025 Stormsurf headline cited CDIP buoy cuts. Current operating status as of Nov 2026 is UNVERIFIED. Design for redundancy and graceful degradation: satellite + CMEMS + NDBC as the federal/EU backbone.
- **Nearshore gap.** Seabass habitat is within ~1 km of shore in kelp at 10–30 m. Satellite pixels (300 m–1 km) are land- and kelp-contaminated, cloud-blocked in the May–Sept season, and measure skin temperature only. In situ and models are needed for temperature at depth, and summer thermocline swings can be several °C within hours (UNVERIFIED magnitude).
- **Visibility forecast skill** beyond ~2–3 days is likely low. Present probabilistic bands. Ground-truth labels must come from diver reports (other agents' scope).
- **Licensing.**
  - Open-Meteo: commercial use needs a paid plan.
  - Copernicus and Sentinel: attribution required.
  - CDIP, SCCOOS, Kelpwatch: non-federal terms UNVERIFIED.
- **Endpoint drift.** ERDDAP dataset IDs differ across mirrors (pfeg vs coastwatch.noaa.gov), CDIP model files look stale, and the NWS RRFS cutover was in flux in Nov 2026. Pin dataset IDs in config and add daily "freshness" health checks using the `time_coverage_end` attribute.
- **Not verified because search ran out:** Skyfield API names, CUTI/BEUTI latency, Kelpwatch latency and license, NWS marine-zone endpoints, Open-Meteo max horizon and pricing, WCOFS grid resolution and cycle count, PACE OCI on ERDDAP, current status of NDBC 46086 and 46232, CDIP data policy. To verify these, `api.tidesandcurrents.noaa.gov`, `mjacox.com` and the other data hosts need to be allowed in the session's network settings, then a follow-up session can smoke-test the endpoints and finish the search.
