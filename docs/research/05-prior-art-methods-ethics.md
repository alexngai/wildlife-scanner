# wildlife-radar: prior art, modeling methodology, and ethics/legal constraints

**How this was checked.** I confirmed claims with WebSearch on 2026-11-11. WebFetch could not reach `www.birds.cornell.edu` or `help.inaturalist.org` because the session's network allowlist blocks them, so I never read the full eBird or iNaturalist terms. Those points come from search-result excerpts. The web-search budget shared across agents also ran out before I had finished, so some citations come from my own knowledge and are marked **UNVERIFIED**. Before anything ships, a person should read the eBird Data Access Terms and the iNaturalist Terms directly.

---

## 1. Prior art and competitors

### Birding: dominated by free Cornell tools

| Product | What it does | Strengths | Weaknesses for "where + when" |
|---|---|---|---|
| **eBird Explore / Bar Charts / Illustrated Checklist** | For a region or hotspot, shows what share of *complete checklists* report each species, week by week. The Illustrated Checklist adds Macaulay Library media ([bar charts](https://support.ebird.org/en/support/solutions/articles/48001255130-ebird-bar-charts-and-graphs), [explore](https://support.ebird.org/en/support/solutions/articles/48000961496)). | Built on detection/effort data, so it measures frequency correctly. Huge volume. | Historical climatology only. No environmental conditions, no forecast, no uncertainty shown. Hotspot-centric. "Community Targets" lists species seen around this date in past years but not yet this period. A standalone Targets tool is **UNVERIFIED** in what I could check. |
| **Merlin "Likely Birds"** | Ranks species by eBird likelihood for a chosen location and date, with rarity markers ([AllAboutBirds](https://www.allaboutbirds.org/news/?p=39902), [Merlin FAQ](https://support.ebird.org/en/support/solutions/articles/48000961587-merlin-bird-id-faqs)). | Very easy to use; works offline. | Seasonal prior only. Gives no recommendations where data are sparse. |
| **eBird Status & Trends** | Weekly relative-abundance maps from an ensemble of 100 machine-learning models, standardized to a 2 km, 1-hour traveling count by an expert observer ([ebirdst vignette](https://cran.ma.ic.ac.uk/web/packages/ebirdst/vignettes/status.html)). | The best-in-class effort-standardized species distribution model. | Annual product; not a nowcast. Commercial use needs written permission. |
| **BirdCast** | Radar-based forecasts of nocturnal migration 3 days ahead, plus live radar maps updated every 10 minutes, for the lower 48 states ([live maps](https://birdcast.info/migration-tools/live-migration-maps/)). | Real forecasting with real-time sensors. | Gives total bird biomass, not species. Runs seasonally. |
| **BirdFlow** (research) | Infers movement and forecasts from S&T weekly maps ([Fuentes et al. 2023, MEE](https://doaj.org/article/9d9f602b26264134aaff6cb99542679f)). | A probabilistic model of where birds move next. | Research code only. |

**iNaturalist / Seek** are tools for identifying species, not for forecasting. Seek shows range and seasonality ([overview](https://medium.com/@jbbernardin/seek-ml-mobile-app-for-wildlife-identification-70cc386d2100)). iNat's "expected nearby" geomodel is reportedly based on SINR ([Cole et al. ICML 2023](https://arxiv.org/pdf/2306.02564)), but that link is **UNVERIFIED**. The SINR authors themselves note that their model ignores time and does not correct spatial bias. **Map of Life** shows species near you, drawn from expert range maps and public databases ([Yale 2015](https://news.yale.edu/2015/05/12/map-life-s-new-app-world-s-biodiversity-palm-your-hand)). It is about which species are present, not when.

### Fishing: many layers and folklore, little real prediction

- **FishTrack** offers cloud-free sea-surface-temperature (SST) maps, chlorophyll, sea-surface height, current overlays and saved waypoints ([fishtrack.com](https://fishtrack.com/sst-chart/southern-california)). It is strong on oceanography, but users must read the maps themselves; it makes no species prediction. Reviews mention gaps in the chlorophyll data ([App Store](https://apps.apple.com/app/id952022603)).
- **Omnia / Navionics** provide depth-range "Fishing Mode", water temperature, water clarity, solunar "best times" and weather ([Omnia layers](https://help.omniafishing.com/en/articles/7967451-available-map-layers)). I found no species-level forecast.
- **Fishbrain** is a social catch log that was once nicknamed the "spot burner". It now sets a privacy level per catch ([Fishbrain blog](https://fishbrain.com/blog/fishbrain/fishbrain-the-spot-burner-app)). This is a direct lesson in what happens when crowd-sourced location data exposes spots. **Fishidy**: features **UNVERIFIED**.
- **Solunar "best times" tables** (Omnia, Windy.app and many others): the most rigorous recent test found *no* relationship between solunar values and catch rates in a recreational trout fishery ([SN Applied Sciences 2023](https://doaj.org/article/90e34b295b8a4d1b833e9a0fac84f226)). Lunar *phase* can matter for particular species. Solunar *scores* should be treated as unvalidated.

### Marine mammals and conservation: the best fusion systems that already exist

- **Whale Safe** (UCSB Benioff Ocean Science Lab) covers the Santa Barbara Channel and San Francisco. It fuses acoustic detections, trusted-observer sightings and a daily blue-whale habitat model (10 km cells, scored 0–100% suitability, *not* presence) into a categorical Whale Presence Rating ([methodology](https://whalesafe.com/methodology/), [BOSL](https://bosl.ucsb.edu/project/whale-safe)). **This is the closest design template for wildlife-radar.**
- **EcoCast** (NOAA/Hazen et al. 2018, *Science Advances*) produces daily satellite-driven predictions for swordfish and bycatch species, with weights managers can adjust, served through ERDDAP ([NOAA CoastWatch](https://coastwatch.noaa.gov/cwn/news/2019-02-15/ecocast-tool-help-fishers-minimize-bycatch-us-west-coast.html)).
- **Whale Alert** (IFAW/Conserve.IO) combines sightings, acoustic and aerial data to warn ship operators away from whales ([IFAW](https://www.ifaw.org/uk/campaigns/whale-alert)). **Ocean Wise Whale Report** deliberately **delays recent sightings by 24 hours for mariners who are not authorized** ([appadvice](https://appadvice.com/app/whale-report/6654889441)), which is a mitigation pattern worth copying. "Ocean Alert": **UNVERIFIED** (not found).
- **Happywhale** does photo-ID of individual animals. Its public data are mostly CC-BY-NC, and some data are open only to collaborators ([OBIS-SEAMAP record](https://seamap.env.duke.edu/dataset/1723/html)).

### Divers and freedivers: a crowded field arriving in 2025–2026

- **DiveSight** (launched around mid-2026) is the most direct competitor. It claims a 0–100 marine-life index and 7-day forecasts at more than 28,000 dive sites, plus a "Wildlife Finder" that shows where and when a species is most likely. It uses two proprietary ML models and claims more than 80% accuracy, a figure it reports itself ([Scuba News, 2026-06-17](https://www.thescubanews.com/2026/06/17/new-app-claims-to-predict-marine-life-encounters-and-underwater-visibility-at-dive-sites-worldwide/), [divesight.ai](https://divesight.ai/), [review](https://maldives-magazine.com/diving/divesight-app-predict-marine-life-encounters-visibility.html)). It is global and opaque, with no published calibration.
- **SoCal visibility apps:** SeaThrough (iOS, built for Southern California), Submarius (visibility informed by divers' reports), Marla Blue (AI plus satellite) and Element (Copernicus data plus solunar, San Diego) ([search summary](https://apps.apple.com/us/app/seathrough/id6758314434), [Submarius](https://apps.apple.com/app/id6762419192)).
- **SpearFactor Conditions** is a web dashboard covering more than 30 California spots. It claims *per-species fish-activity forecasts for yellowtail, white seabass and halibut*, refreshed every 30 minutes ([page](https://fishing-dive-conditions.pages.dev/sitemap.xml)). Its operator and accuracy are **UNVERIFIED**. This confirms that white seabass forecasting already exists, aimed at **spearfishers**.

### Is there a gap?

Yes, but it is narrower than "nobody does this." Birding is well served by Cornell for free, and Cornell's terms limit how its data can be reused. Divers now have DiveSight, which is global and generic, and SpearFactor, which is aimed at spearfishers. What is still open:

1. **Transparent, calibrated, explainable forecasts.** Show "why" for each forecast (squid, moon, SST anomaly), give a reliability record, and compare against a "typical for this week" baseline. No competitor publishes its calibration.
2. **Structured, effort-aware dive logs that include species *not* seen.** This would be the marine equivalent of eBird's complete checklists. It is the real data moat, and the data are licensed to you (see §3).
3. **Photography-first, conservation-aligned framing**, with visible guardrails. This differentiates the product from spearfishing tools and earns trust from agencies and NGOs.
4. **Multi-taxa fusion in the style of Whale Safe** (sensors + sightings + habitat model → a categorical rating) for recreational users.

---

## 2. Modeling methodology

### 2.1 Choose the target quantity before the model
Predict an **encounter rate standardized for effort**: "probability of seeing species X on a standard 60-minute daytime dive at site S on day D, by an experienced observer." This is the same framing as eBird Status & Trends, which standardizes to a 2 km, 1-hour count. It makes predictions comparable across sites and days, and it can be evaluated. Raw sighting counts mostly measure how much effort observers spent.

### 2.2 Data reality and bias correction
- **Presence-only data** (iNat, GBIF, fishing reports) mix up observer effort with species presence. The standard fix is **target-group background**: draw background points from all records of related taxa that are observed in the same way, such as every iNat fish observation by divers in SoCal. This copies the sampling bias into the background ([Phillips et al. 2009, *Ecol. Appl.*](https://www.whoi.edu/cms/files/Phillips_EcolApp_2009_53454.pdf)). One caveat: target-group background cannot tell "unvisited" apart from "visited but the species was absent" ([Fithian et al., arXiv 1403.7274](https://arxiv.org/pdf/1403.7274)). Fithian et al. also pool survey and presence-only data across many species to estimate the bias directly.
- **eBird best practice** ([Johnston et al. 2021, *Divers. Distrib.*](https://par.nsf.gov/servlets/purl/10332329)):
  - Use complete checklists only, so that missing records count as non-detections.
  - Filter on effort: duration ≤ 5 h, distance ≤ 5 km, ≤ 10 observers. These exact thresholds come from the book's guidance and are **UNVERIFIED** this session.
  - Include effort covariates: duration, time of day, number of observers, observer expertise.
  - Subsample spatiotemporally on a grid stratified by detection, to balance classes and reduce spatial clumping.
- **Integrated SDMs** combine structured presence/absence data (your dive logs, Reef Check and PISCO surveys) with opportunistic presence-only data (iNat), giving each its own observation submodel ([Isaac et al. 2020, *TREE*](https://minerva-access.unimelb.edu.au/server/api/core/bitstreams/81df9210-88f9-5780-9b91-7e9d21547d0d/content)). Warning: integration *alone* did not correct spatial bias in simulation ([Simmonds et al. 2020](https://nora.nerc.ac.uk/id/eprint/528191/)). The bias must also be modeled explicitly.
- **Occupancy and detection.** Divers miss fish. Visibility, depth and time of day strongly affect detection. Occupancy models separate presence ψ from detection p using repeat visits (MacKenzie et al. 2002, **UNVERIFIED citation**; `spOccupancy`/`unmarked` in R, **UNVERIFIED**). At minimum, put visibility into the *detection* part of the model, not the habitat part.

### 2.3 Model families, from simplest to most complex
1. **Climatology baseline:** smoothed week-of-year × site frequency (what eBird bar charts and Merlin do). Ship this first; every later model must beat it.
2. **GAMs or gradient-boosted trees with environmental covariates.** In a 225-species benchmark, tuned ensembles, down-sampled random forests, MaxEnt and boosted regression trees were among the top methods. Default biomod ensembles were *not* ([Valavi et al. 2022, *Ecol. Monogr.*](https://minerva-access.unimelb.edu.au/server/api/core/bitstreams/579c6e64-d414-4f20-9f2d-3c9dcdefb73b/content)). For white seabass, candidate covariates are:
   - SST and SST anomaly, chlorophyll / water clarity, swell and surge, tide phase.
   - Lunar phase and illumination, days since new moon.
   - Day of year, kelp canopy, and market-squid spawning or landings as an index of prey.
   - Plausible priors come from [Aalbers 2008](https://fisherybulletin.nmfs.noaa.gov/sites/default/files/pdf-content/2008/1062/aalbers.pdf): white seabass spawned at all lunar phases but more often after the new moon, from March to July with a May peak, mostly within 2 hours of sunset. The squid link comes from angler lore and has not been validated (**UNVERIFIED** in the literature).
3. **Bayesian hierarchical spatio-temporal models** (INLA/`inlabru` with SPDE spatial fields, log-Gaussian Cox processes; **UNVERIFIED citations**). Use these when you need honest uncertainty and partial pooling across sites. Presence-only data are naturally a point process (Warton & Shepherd 2010; Renner et al. 2015, **UNVERIFIED**).
4. **Deep or global species models** (SINR) are useful as *priors* for broad range and seasonality across thousands of taxa. They are not good for daily timing.

### 2.4 Nowcasting: combining a seasonal prior with real-time evidence
- **Simple and robust:** Gamma-Poisson or Beta-Binomial updating, where the climatology/covariate model supplies the prior and recent sightings are discounted exponentially (half-life fitted on historical data, likely 2–7 days for transient pelagic fish).
- **Self-exciting (Hawkes) process:** λ(s,t) = μ(s,t) + Σᵢ α·g(t−tᵢ)·h(‖s−sᵢ‖). The baseline μ is the covariate model, and the sum is the boost from recent sightings. `stelfi` fits Hawkes and LGCP models in R ([Jones-Todd & van Helsdingen 2024, *Ecol. Evol.*](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10864691/)). A self-exciting model has also been used for camera traps ([NZSA 2024](https://sms.wgtn.ac.nz/Events/NZSA2024/AbstractAlecvanHelsdingen)). Caveat: much of the "excitation" in sighting data is **observer contagion**: a post goes up and everyone dives there. Model reporting effort, or the forecast will feed on itself.
- **Fusion template:** Whale Safe combines a habitat model, real-time sensors and trusted sightings into a categorical rating ([methodology](https://whalesafe.com/methodology/)).

### 2.5 Rare species and cold start
- **Hierarchical pooling:** share covariate effects across a guild (pelagic kelp-forest predators: white seabass, yellowtail, barracuda) with species-level random deviations. Joint or multi-species occupancy models do this; Hmsc and `spOccupancy` are **UNVERIFIED** tool names.
- **Expert-elicited priors:** encode published spawning seasonality (Aalbers), CDFW and fisher knowledge, and expert range maps as constraints. Expert maps improved SDM predictions in 92.5% of hummingbird cases ([Merow et al. 2017, *GEB*](https://jetzlab.yale.edu/node/220) and follow-up).
- **Ensembles of small models** (Breiner et al. 2015, **UNVERIFIED**) handle species with fewer than about 20 records.
- **Show an explicit "insufficient data" state** instead of a confident-looking map.

### 2.6 Evaluation and calibration
- **Split by time and space, never randomly.** Random cross-validation badly underestimates error on structured data ([Roberts et al. 2017, *Ecography*](https://www.biometrie.uni-freiburg.de/mitarbeiter/dormann/roberts-et-al-2017-ecography.pdf)). Train on data up to year Y and test on year Y+1, and use spatial blocks larger than the residual autocorrelation range.
- **Avoid leakage:**
  - Use covariates *as they were available at forecast time*: forecast products, not later reanalysis.
  - Deduplicate group sightings, where several divers report one encounter.
  - Never use the label event's own reports as nowcast features.
  - Watch for obscured iNat coordinates landing in the wrong cells.
- **Metrics:** use proper scoring rules (Brier score, log-loss) and **reliability diagrams**. Use AUC or PR-AUC only for ranking. Report **skill relative to climatology and to persistence** ("same as last week"). If the model cannot beat the bar chart, it adds nothing.
- **Recalibrate:** boosted and random-forest probabilities are often off by about 0.2. Recalibrate with a flexible calibration regression before showing or averaging them ([Dormann 2020, *GEB*](https://www.biometrie.uni-freiburg.de/mitarbeiter/dormann/dormann2020geb.pdf)).
- **Publish a public scorecard:** each month, compare forecast probabilities with logged outcomes.

### 2.7 Communicating uncertainty to non-experts
- **Use frequency formats tied to a reference effort:** "About 1 in 6 dives like this sees white seabass (typical for mid-November: 1 in 20)."
- **Show a categorical band plus confidence:** Low / Fair / Good / Excellent, with a "low confidence – few reports" badge, as Whale Safe does with categories rather than raw numbers.
- **Show the top 2–3 drivers** ("new moon in 2 days; squid reported at Catalina; SST +1.2 °C").
- **Show a forecast horizon and stale-data warnings.** Never show more precision than the evidence supports. Use coarse cells and day-level timing for anything below "Good" confidence.

---

## 3. Ethics, legal, and licensing

### 3.1 Disturbance, targeting, and harm
- **The core dual-use risk is real.** Whatever filters you apply, a white seabass "where/when" forecast doubles as a spearfishing tool. White seabass is a legal, managed target: 28-inch minimum, 3-fish bag limit, **cut to 1 fish south of Point Conception from March 15 to June 15** ([CDFW](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central), [14 CCR §28.35](https://regulations.justia.com/states/california/title-14/division-1/subdivision-1/chapter-4/article-1/fin-fish-minimum-size-limits-bag-and-possession-limits-and-seasons/section-28-35)). That window matches the spawning season, so the product's peak-signal months are the months regulators protect. SpearFactor already serves spearfishers.
- **Giant sea bass:** take has been prohibited in California since 1982. Summer courtship and spawning aggregations happen at Catalina and similar sites. The population may be fewer than 500 breeding adults by one genetic estimate (about 1,200 adults by another) ([Aquarium of the Pacific](https://www.aquariumofpacific.org/reportcard/info/giant_sea_bass), [UCSB MSI](https://msi.ucsb.edu/news/uncovering-mysteries-giant-sea-bass)). Pinpointed aggregation forecasts invite crowding, harassment and poaching.
- **Precedents for withholding locations:**
  - eBird hides sensitive species from public outputs (325 taxa) and shows them only on coarse grids. Sources disagree on the grid size (20 km, 100 km or 400 km), so it is **UNVERIFIED** ([eBird](https://www.allaboutbirds.org/sensitive-species-in-ebird/), [Audubon](https://www.audubon.org/magazine/ebird-now-censoring-sightings-325-risk-species)).
  - eBird asks observers to delay reporting nests and roosts until the birds leave ([eBird guidelines](https://ebird.org/news/sensitive_species)).
  - iNat automatically obscures taxa whose disclosed locations could invite poaching or disturbance, based on conservation status, and lets curators adjust this by jurisdiction ([iNat curator guide](https://inaturalist.ala.org.au/pages/curator+guide)). The 0.2°×0.2° obscuring cell is **UNVERIFIED**; the help page was blocked.
  - "Do not publish" (Lindenmayer & Scheele 2017, *Science*) documents poaching that followed published locations ([ScienceDaily](https://sciencedaily.com/releases/2017/05/170525141549.htm)).
  - GBIF's *Best Practices for Generalizing Sensitive Species Occurrence Data* says each generalization should record a reason and a review date ([Chapman 2020](https://docs.gbif.org/sensitive-species-best-practices/master/en/)).
  - Ocean Wise delays whale sightings by 24 hours ([Whale Report](https://appadvice.com/app/whale-report/6654889441)).
- **Marine mammals:** the MMPA prohibits harassment. NOAA guidance is 100 yards for whales and 50 yards for dolphins (100 in some places). For pinnipeds, NOAA's own pages differ: 50 yards on one, 100 yards under "Share the Shore" on another ([NOAA](https://www.fisheries.noaa.gov/topic/marine-life-viewing-guidelines/guidelines-and-distances), [West Coast](https://fisheries.noaa.gov/west-coast/outreach-and-education/how-close-too-close)). Freedivers swimming toward animals is a known harassment risk.
- **MPAs:** many SoCal sites are no-take, such as Casino Point and Lover's Cove ([CDFW](https://wildlife.ca.gov/Conservation/Marine/MPAs/Casino-Point)). A forecast that marks "fish inside an MPA" can draw poachers. Overlay MPA boundaries with their take rules.

### 3.2 Data licensing

| Source | Key constraint | Implication |
|---|---|---|
| **eBird (API and raw data)** | The API license covers **non-commercial use only**. Commercial use needs prior written permission from Cornell. API keys may not be shared. Derived works need full attribution and citation. "Commercial" includes use that informs or assists a for-profit entity ([search summary of API terms](https://www.birds.cornell.edu/home/ebird-api-terms-of-use/), [Data Access Terms](https://www.birds.cornell.edu/home/ebird-data-access-terms-of-use)). Status & Trends products need permission for commercial use too ([S&T terms](https://ebird.org/about/products-access-terms-of-use)). Full text **UNVERIFIED** (fetch blocked). | A birding vertical that makes money in any way, including ads, subscriptions or affiliate links, needs a Cornell agreement. Ask early (ebird@cornell.edu). |
| **iNaturalist** | The default license is **CC-BY-NC**, and it covers most observations. Data shared to GBIF are CC0, CC-BY or CC-BY-NC, and GBIF labels mixed records with the most restrictive license ([iNat](https://www.inaturalist.org/posts/30692-tech-tip-tuesday-understanding-licensing), [GBIF](https://data-blog.gbif.org/post/gbif-occurrence-license-processing/)). The Terms (revised July 11, 2023) reportedly **ban using iNat content to train commercial AI/ML models, even CC0 content** (secondhand from a [forum](https://forum.inaturalist.org/t/can-i-use-inaturalist-aws-open-data-to-train-commercial-ai-model/77663); **verify**). API practice is about 60 requests per minute or less. | Training a forecast model for a commercial product on iNat data may breach the Terms whatever the record license. Keep a per-record license ledger and exclude NC records from monetized outputs. |
| **CC "NonCommercial"** | Defined as "not primarily intended for or directed towards commercial advantage or monetary compensation." Whether ads count is decided case by case, but CC's own survey found that both creators and users see advertising as commercial ([CC wiki](https://wiki.creativecommons.org/4.0/NonCommercial)). | Treat ads, subscriptions and freemium as commercial. |
| **GBIF** | Cite the download DOI. For filtered or API-derived data, register a **derived dataset** to get a DOI. Follow each publisher's license ([citation guidelines](https://gbif.org/citation-guidelines), [derived datasets](https://www.gbif.org/derived-dataset/about)). | Automate DOI registration in the pipeline. |
| **Copernicus Marine** | Free, including commercial use. Attribution is mandatory: "Generated using E.U. Copernicus Marine Service Information" plus DOIs ([licence](https://marine.copernicus.eu/user-corner/service-commitments-and-licence), [citation](https://help.marine.copernicus.eu/en/articles/4444611-how-to-cite-copernicus-marine-products-and-services)). The free service runs to 2028 under the current agreement. | Low risk. |
| **US federal (NOAA, NWS, NDBC)** | Works of the US government are generally public domain under 17 USC §105 (not re-verified this session). University-run partners in IOOS/SCCOOS may carry their own terms (**UNVERIFIED**). | Check each partner dataset. |
| **Happywhale / OBIS-SEAMAP** | Mostly CC-BY-NC. Some data are open only to collaborators ([OBIS](https://seamap.env.duke.edu/dataset/1723/html)). | Partner with them; do not scrape. |

**Scraping fishing-report and community sites** (976-TUNA, forums, charter logs): in *hiQ v. LinkedIn* the court found the anti-scraping and fake-profile terms in a site's user agreement enforceable as a contract. The case ended with a $500k judgment against hiQ and an order to delete the scraped data ([Morgan Lewis](https://www.morganlewis.com/blogs/sourcingatmorganlewis/2022/12/linkedin-v-hiq-landmark-data-scraping-suit-provides-guidance-to-data-scrapers-and-web-operators), [Proskauer](https://newmedialaw.proskauer.com/2022/11/11/court-finds-hiq-breached-linkedins-terms-prohibiting-scraping-but-in-mixed-ruling-declines-to-grant-summary-judgment-to-either-party-as-to-certain-key-issues/)). The 2024 *Meta v. Bright Data* ruling, which reportedly held that scraping by logged-out users did not breach the terms, is **UNVERIFIED**. Report text is also copyrighted. Prefer licensed feeds, partnerships, or linking out with short factual extracts, and get legal review.

### 3.3 Liability and safety for divers
In *Winter v. G.P. Putnam's Sons* (9th Cir. 1991, California law), an erroneous mushroom guide was held **not** to be a "product." The court distinguished **charts**, which other courts have treated as products for strict liability because they are "highly technical tools like a compass" ([Justia](https://law.justia.com/cases/federal/appellate-courts/F2/938/1033/294363)). A map-based conditions forecast that divers rely on may sit closer to a chart than to a book. Mitigations:
- Never issue a "safe to dive" or go/no-go verdict.
- Show data timestamps and sources, and link to NWS marine forecasts.
- Use clickwrap terms covering assumption of risk, no warranty and limitation of liability.
- Exclude conditions and visibility from any "Excellent" wildlife rating, or show them separately.

Section 230 likely protects user-posted sightings but not your own model outputs (**UNVERIFIED legal analysis**; get counsel).

---

## 4. Recommendations

### Positioning
- Make the product **"the transparent, conservation-aligned encounter forecast for underwater photographers"**, starting in SoCal kelp forests.
- **Differentiate from DiveSight** with published calibration, per-forecast explanations and regional depth.
- **Differentiate from SpearFactor** with a photography and ethics framing and the guardrails below.
- The moat is **your own structured dive logs**: site, entry time, duration, max depth, visibility, and full species presence/absence. These are licensed to you under your terms (ask users for a CC-BY or broader grant), effort-aware, and free of NC restrictions.
- **Hold birding** until you have a Cornell agreement. For birding, add value on top of eBird (weather and migration fusion) rather than rebuilding it.

### MVP modeling approach
1. **Unit of prediction:** encounter probability per standard dive, for a region-level cell (about 5–10 km of coastline), per day.
2. **Layer A, the seasonal prior:** a hierarchical GAM (cyclic day-of-year, region random effect). Fit it on structured surveys (Reef Check, PISCO and your logs; availability per the other agents' catalogue) plus iNat/GBIF presence-only data with target-group background. Seed rare species with elicited priors (Aalbers spawning curve).
3. **Layer B, conditions:** LightGBM or GAM with as-of-forecast covariates (SST anomaly, chlorophyll/clarity, swell, tide, lunar phase, squid index). Visibility goes in the *detection* part of the model. Recalibrate with isotonic or flexible calibration regression.
4. **Layer C, the nowcast:** Gamma-Poisson updating with exponentially decayed recent trusted sightings. Fit the decay on history, and add a correction for reporting effort to dampen observer contagion. Upgrade to a Hawkes/LGCP model once the data volume justifies it.
5. **Evaluation gate:** rolling forward-in-time plus spatial-block validation. Ship a species only if its Brier skill score against climatology is above 0 *and* its reliability diagram is acceptable. Otherwise show the climatology alone, labeled as such.
6. **Output:** categorical band, an "x in N dives" frequency, a comparison with what is typical for the week, the top drivers and a confidence badge.

### Day-one guardrails policy
1. **Sensitivity tiers per taxon:**
   - **Tier 2, no maps or forecasts at all:** giant sea bass (especially aggregation season), anything ESA- or CESA-listed, nesting or roosting owls, and seabird and pinniped rookeries.
   - **Tier 1, coarse region and week only, sightings delayed 7 or more days, no nowcast boost:** spawning-season white seabass (March 15–June 15), marine mammals.
   - **Tier 0:** everything else, still at ≥1 km.
   - Record the reason and a review date for each tier assignment, per GBIF/Chapman.
2. **Never de-obscure** inherited data. Honor eBird sensitive species, iNat taxon and user geoprivacy, and any embargo set by a data provider.
3. **No exact points or GPS export** for any wildlife record. Sightings become public only after a delay (24 h by default, as Ocean Wise does) and in aggregate.
4. **Regulatory context in the product:** show MPA boundaries and take rules, CDFW size and bag limits, and NOAA approach distances (100 yd whales; 50–100 yd others). Do not offer "fish here now" alerts inside no-take MPAs.
5. **Photography-first product choices:** no catch logging, harvest metrics or spearfishing features. Terms of use prohibit using the service for illegal take.
6. **License ledger and attribution:**
   - Store the license per record.
   - Segregate NC and eBird-derived data from any monetized feature.
   - Do not train commercial models on iNat content without written permission.
   - Register GBIF derived-dataset DOIs automatically.
   - Show Copernicus attribution.
   - Do not scrape any site whose terms prohibit it.
7. **Safety:** no go/no-go language, with timestamps, sources, links to NWS forecasts and clickwrap assumption-of-risk terms.
8. **Accountability:** a public calibration scorecard, a "report misuse" channel, and a standing invitation for review by CDFW, NOAA and NGOs (e.g., UCSB's giant sea bass project).
