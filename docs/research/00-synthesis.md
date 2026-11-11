# wildlife-radar — research synthesis (2026-11-11)

This summarizes five parallel research reports (files `01`–`05` in this folder). Those reports were written by AI research agents using web search. Network limits in the research session blocked direct reads of several key pages (eBird and iNaturalist terms, iNaturalist API, NOAA tides API). Claims marked **UNVERIFIED** in the source reports must be checked before anyone builds on them. Licensing items especially need a human read of the actual terms.

| File | Scope |
|---|---|
| [01-observation-data-sources.md](01-observation-data-sources.md) | iNaturalist, GBIF, eBird, OBIS, REEF, Reef Check, Channel Islands KFM, PISCO/SBC LTER/MBON, CalCOFI, Movebank, Happywhale, Acartia… |
| [02-environmental-covariates.md](02-environmental-covariates.md) | Tides, moon/sun, SST, subsurface temperature, clarity/visibility, swell, currents, upwelling, kelp, HABs, weather |
| [03-white-seabass-case-study.md](03-white-seabass-case-study.md) | WSB ecology, evidence for each signal, market squid data, fishery data, regulations, MVP model |
| [04-birding-signals.md](04-birding-signals.md) | eBird S&T/API/EBD, BirdCast, NEXRAD + Dark Ecology, weather drivers, phenology, BirdWeather, birding MVP |
| [05-prior-art-methods-ethics.md](05-prior-art-methods-ethics.md) | Competitors, modeling methodology, evaluation, ethics, licensing, liability |

---

## 1. Ten things we learned

1. **Environmental data is the easy part.**
   - Tides, moon, SST, ocean color/clarity, swell, wind and ocean-model forecasts are mostly free US-federal or Copernicus data. Most of it is reachable through ERDDAP.
   - Moon and sun values can be computed locally with no API.
   - Real *forecasts* exist for planning ahead: Copernicus 10-day ocean physics, NOAA WCOFS 72 h, ECMWF waves.
2. **Ground-truth labels are the bottleneck.** For an elusive fish like white seabass (WSB), photo-based sightings are sparse. The densest near-real-time signal is party-boat fish counts. Those sites' terms prohibit scraping and commercial reuse, so they are a **partnership** target.
3. **Most of the founder's hypothesized WSB signals are weaker than folklore suggests.** Per the peer-reviewed evidence in report 03:
   - Season, time of day (dusk), water temperature and *recent reports* are the strong signals.
   - Moon is weak: spawning happens at all lunar phases, with at most a small post-new-moon bump.
   - Tide shows no direct effect.
   - The squid link is plausible but quantitatively unproven, and the SoCal squid fishery peaks in *winter*, while WSB spawn in *spring*.
   - The product can **test** these hypotheses honestly with ablations, and that is a selling point in itself.
4. **A new low-latency squid proxy exists:** NOAA VIIRS Boat Detection (nightly lit-vessel detections, ~1-day latency, public). Squid light boats run up to 30 kW and are among the brightest objects in the Southern California Bight. This proxy is better than CDFW landings data, which are aggregated and suppressed below 3 vessels.
5. **Passive acoustics is the best fishery-independent WSB signal.**
   - WSB "spawning chants" are recorded by PIER's acoustic array, which has run since 2008.
   - The NOAA sanctuary recordings (Kim et al. 2025) have chorus logs public on Dryad.
   - A partnership with PIER is the highest-value scientific relationship.
6. **Effort-bearing survey datasets give solid seasonal priors.**
   - The best single SoCal dataset is the SBC MBON integrated kelp-forest fish dataset (LTER + PISCO + NPS KFM, about 1980–present).
   - REEF roving-diver surveys are the closest public analogue to "P(see species X on a dive)".
   - These data lag 1–2 years, so they serve as priors, not nowcasts.
7. **The market is not empty.**
   - **DiveSight** (mid-2026) claims global 7-day marine-life and visibility forecasts with a "Wildlife Finder"; its ML is proprietary and its accuracy self-reported.
   - **SpearFactor** already claims per-species WSB/yellowtail/halibut forecasts for *spearfishers*.
   - **Whale Safe** (UCSB) is the best design template: habitat model + sensors + trusted sightings → a categorical rating.
   - The open gap is **transparent, calibrated, explainable, photography-first** forecasts plus **structured dive logs that include non-detections**.
8. **Licensing hinges on one question: is this commercial?**
   - The eBird API, the eBird Basic Dataset (EBD) and eBird Status & Trends are all non-commercial unless Cornell grants written permission. S&T forbids redistributing maps on the web *even non-commercially* without permission.
   - Most iNaturalist observations are CC BY-NC. The iNat Terms reportedly ban commercial AI/ML training on iNat content, which needs verification.
   - Open-Meteo's free tier is non-commercial only.
   - GBIF downloads can be **filtered by license** (CC0/CC BY only) to get a commercially safe subset.
9. **Dual-use risk is real and specific.**
   - A spring + dusk + squid-bed WSB forecast is in effect a map of transient *spawning aggregations*.
   - Regulators protect that same window: the bag limit drops to 1 fish south of Point Conception from Mar 15 to Jun 15.
   - A 2026 CDFW paper found less than 1% of females are mature at the 28" legal size.
   - Giant sea bass aggregations are even more sensitive: take is prohibited, and estimates run to only a few hundred breeding adults.
   - Guardrails have to be designed in from day one, and they are also what earns agency and NGO data partnerships.
10. **IOOS funding is a live infrastructure risk.**
    - Regional ocean observing (SCCOOS shore stations, HF radar, gliders, possibly CDIP buoys) faces proposed zero federal funding.
    - Design the pipeline to degrade gracefully onto satellite + Copernicus + NDBC.

---

## 2. Framing: what exactly do we predict?

**P(encounter) = P(present) × P(detect | present)**

- **Prediction unit:** P(encounter) is the probability of seeing species X during a *standard effort unit* at site/zone S on day D.
  - Marine: a 60-minute daytime dive by an experienced diver.
  - Birding: a 1-hour, ≤2 km checklist, matching eBird S&T.
  - A fixed unit makes forecasts comparable, evaluable and honest. Raw sighting counts mostly measure observer effort.
- **Presence** has two parts:
  - a slow **seasonal/spatial prior** (where and when the species usually is);
  - fast **modifiers** (conditions, prey signals, recent sightings).
- **Detection**, for divers, is dominated by visibility, surge, light and depth. It belongs in the *detection* part of the model, not the habitat part.
- **Show conditions as their own product.** A good "can I see anything?" forecast is useful by itself, is easier to get right, and covers for the species model while that is still immature.

## 3. Proposed model architecture: layers, each earning its place

| Layer | What | Initial method | Data |
|---|---|---|---|
| **A. Seasonal prior** | Zone × week-of-year baseline | Hierarchical GAM (cyclic DOY + zone effect); elicited priors for rare species | MBON/KFM/REEF/Reef Check; iNat/GBIF with target-group background; eBird EBD (birds) |
| **B. Conditions modifier** | Environmental effect on presence | Logistic GAM → GBM only if it wins; isotonic recalibration | SST + anomaly, clarity, swell, upwelling, lunar, squid-light index, ENSO |
| **C. Nowcast** | Boost from recent reports | Gamma-Poisson / exponentially decayed evidence; later Hawkes/LGCP; correct for "observer contagion" | Licensed fish counts, iNat, user logs, eBird notable, BirdWeather |
| **D. Detectability / conditions** | Can you see it? | Separate visibility & safety outlook (never a go/no-go verdict) | Swell, chl/Kd490, rain-runoff flag, wind |

**Evaluation gate (non-negotiable):**
- Use rolling, forward-in-time and spatial-block validation, never random CV.
- Score with Brier/log-loss and reliability diagrams.
- A species or feature ships only if it beats **climatology** (zone × week mean) and **persistence** (last week's reports).
- Otherwise the product shows the climatology, labeled as such.
- Store **as-of snapshots** of all covariates. MUR revises its last 7 days, OISST goes from preliminary to final, and ERA5T becomes ERA5; without snapshots, backtests leak future data.

**Output to users:**
- A categorical band (Low / Fair / Good / Excellent).
- A frequency phrasing: "~1 in 6 dives like this; typical for mid-Nov: 1 in 20".
- The top 2–3 drivers.
- A confidence badge and data timestamps.
- A public monthly calibration scorecard.

## 4. Data stack for a SoCal marine MVP

**Covariates (all free; US federal is public domain; Copernicus is free with attribution):**
- **Astronomy:** astronomy-engine (local).
- **Tides:** NOAA CO-OPS predictions for 4–6 harmonic stations, cached years ahead.
- **SST:** MUR 0.01° + Geo-polar Blended for latency + in-situ truth (CDIP, SCCOOS shore stations, NDBC); OISST for anomalies.
- **Temperature at depth / forecast:** Copernicus GLO PHY (10-day) + NOAA WCOFS (72 h).
- **Clarity:** VIIRS chl/Kd490 (750 m) + Sentinel-3 OLCI chl (300 m). OLCI keeps only a rolling 90 days on ERDDAP, so archive it daily ourselves.
- **Swell:** CDIP buoys/nowcast + ECMWF wave forecast.
- **Weather and rain:** NWS API (rain → runoff flag).
- **Context:** CUTI/BEUTI, RONI/PDO, Kelpwatch.
- **Squid-light index:** VIIRS Boat Detection, masked for oil platforms and harbors, filtered to sandy 20–100 m bottom, and adjusted for weekend closures and moonlight.

**Labels / presence:**
- **Training (best):** CPFV logbook block × date data from CDFW. Requires a data request; e-logs are due by the 10th of the following month.
- **Live:** licensed daily landing counts from the Fish Reports Network or the landings themselves.
- **Validation:** PIER / Dryad acoustic chorus logs; iNat/REEF for seasonal shape.
- **Moat:** our own structured dive logs (site, time, duration, depth, visibility, full presence/absence list), licensed to us by users.

**Defer:** HF radar, gliders, HABs, ERA5 (bring ERA5 in for historical training).

## 5. Birding vertical (later or parallel)

- **Value-add over eBird/Merlin:**
  - day-level timing driven by weather and migration;
  - a **rarity "chase-ability"** model (survival analysis: P(still present on day t+k));
  - a shorebird tide planner;
  - a seawatch/pelagic outlook built on the marine pipeline.
- **Open radar data makes migration forecasting feasible:**
  - The **Dark Ecology** dataset (CC BY 4.0) covers every US radar scan 1995–2025, enough to train migration models.
  - NEXRAD Level II is on AWS (`unidata-nexrad-level2`).
  - vol2bird/bioRad process the radar scans.
  - Start regional, with about 6 SoCal radars.
- **Blocker:** the eBird products are core and non-commercial. **Talk to Cornell (ebird@cornell.edu) before building.**
- **Possible eBird alternative:** eBird presence data on GBIF may be CC BY 4.0 (UNVERIFIED).
- **BirdWeather** (18k+ acoustic stations, GraphQL, no key) is a strong live-presence signal, but its terms are unknown.

## 6. Guardrails to adopt on day one

1. **Sensitivity tiers per taxon, each with a recorded reason and review date** (GBIF/Chapman practice):
   - **Tier 2 — no maps or forecasts:** giant sea bass during aggregation season, ESA/CESA-listed species, owl roosts/nests, rookeries.
   - **Tier 1 — zone × week only, sightings delayed ≥7 days, no nowcast boost:** spawning-season WSB (Mar 15–Jun 15), marine mammals.
   - **Tier 0 — everything else:** still ≥1 km resolution, and public sightings delayed ≥24 h (the Ocean Wise pattern).
2. **Never de-obscure.** Honor eBird sensitive species, iNat geoprivacy and provider embargoes. No exact points and no GPS export.
3. **Regulatory context in the product:** MPA boundaries and take rules, CDFW size/bag limits, NOAA marine-mammal approach distances.
4. **Photography-first:** no catch logging, harvest metrics or spear features. The terms of use prohibit using the service for illegal take.
5. **License ledger:**
   - Store the license per record.
   - Keep NC and eBird-derived data out of anything monetized.
   - Register GBIF derived-dataset DOIs automatically.
   - Show Copernicus/Sentinel attribution.
   - **Never scrape** sites whose terms prohibit it.
6. **Safety:** no "safe to dive" language. Show timestamps and sources, link to NWS marine forecasts, and use clickwrap assumption-of-risk terms.

## 7. Suggested next steps

**Spikes (each about 1–3 days):**
1. **Data-volume reality check:**
   - Count WSB (and giant sea bass, leopard shark) records in iNat, GBIF, OBIS, MBON and REEF for SoCal by month and year.
   - This decides how much the photo-sighting path matters.
2. **Conditions dashboard for ~20 named SoCal dive sites:**
   - Tides, moon/sun, SST (satellite + in situ), swell, clarity and rain flag, with forecasts.
   - Useful on its own from day one, and it builds the as-of covariate store.
3. **Squid-light index prototype:**
   - VIIRS boat detections over the Bight, 2015–present.
   - Eyeball against public seasonal squid landings and against WSB catch seasonality.
4. **Climatology baseline:** zone × week WSB baseline from whatever labels are available. Every later model must beat it.

**Outreach (start early; partnerships take months):**
- Fish Reports Network / SoCal landings: licensed daily counts.
- CDFW: CPFV logbook data request.
- PIER: acoustic WSB data.
- REEF: survey data.
- UCSB Benioff Ocean Science Lab: Whale Safe and Spotting Giant Sea Bass.
- Cornell (eBird): only if the birding vertical proceeds.

**Before code:** settle the open product decisions in section 8, especially commercial vs. non-commercial.

## 8. Open decisions for the founder

1. **Commercial or not?** This drives the eBird, iNat and Open-Meteo usage and the partnership approach.
2. **MVP scope:** WSB only, or a SoCal marine set (WSB + giant sea bass + leopard sharks + gray whales)? Leopard sharks at La Jolla and giant sea bass aggregations are far more predictable "wins" than WSB.
3. **Audience:** photographers and divers only, or anglers too? This sets acceptable precision and the guardrail tiers.
4. **Founder access:** dive, spearo, charter or dive-shop relationships for early labels.
5. **Tech stack preferences.**

## 9. Verification gaps

The research session could not reach several hosts and ran out of web-search budget. Allowing these hosts in a future session would let us smoke-test endpoints and confirm terms:

- `api.inaturalist.org`, `www.inaturalist.org`, `help.inaturalist.org`
- `api.gbif.org`, `api.obis.org`
- `api.tidesandcurrents.noaa.gov`, `mjacox.com`
- `www.birds.cornell.edu`, `science.ebird.org`, `ebird.github.io`, `documenter.getpostman.com`
- `app.birdweather.com`, `cran.r-project.org`, `fisherybulletin.nmfs.noaa.gov`

**Highest-priority manual reads** (humans should read the actual text): the eBird API, EBD and S&T terms; the iNaturalist Terms (commercial and AI-training clauses); the Open-Meteo pricing/terms; and the CDIP/SCCOOS data policies.
