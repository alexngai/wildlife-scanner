# White seabass (WSB, *Atractoscion nobilis*): case study for a "wildlife-scanner" forecast

**How this was researched, and the limits.** The session's network policy blocked WebFetch and curl to `api.inaturalist.org` and `fisherybulletin.nmfs.noaa.gov`, so I stopped trying other hosts as the tool told me to. Partway through, the shared WebSearch budget for this turn ran out. As a result, everything below comes from search-result abstracts and snippets, not full-text reads of the papers. Facts I could not confirm are marked **UNVERIFIED**. Evidence strength is labelled **strong**, **moderate** or **anecdotal**. To re-run the iNaturalist count, `api.inaturalist.org` has to be added to the session's allowed network hosts.

---

## 1. Ecology

**Range and stock.** WSB range from Baja California into California. They are common south of Point Conception, and the centre of abundance and larval production is off central Baja. A CDFG status review places larval concentrations in the inshore areas of Bahía Sebastián Vizcaíno and San Juanico, "indicating major spawning occurs off central Baja California" ([CDFG review](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=34417)).

The stock crosses the border:
- Fish tagged in Baja moved into California ([Aalbers et al. 2021/22, Env Biol Fish 105](https://link.springer.com/article/10.1007/s10641-021-01091-x)).
- 3 of 41 recaptures from California tagging came from Mexican waters ([Aalbers & Sepulveda 2015, Fish Bull 113:1–14](https://spo.nmfs.noaa.gov/content/seasonal-movement-patterns-and-temperature-profiles-adult-white-seabass-atractoscion)).

The last stock assessment was in 2016 and used data through 2013. It estimated female spawning biomass at about 627 t in 2015 ([OPC draft species report](https://opc.ca.gov/webmaster/_media_library/2019/08/Draft_Marine-Species-Report_WhiteSeaBass-1.pdf)). Seafood Watch rates the stock "not overfished" but notes the assessment is more than 10 years old and Mexican catch is unknown ([Seafood Watch](https://www.seafoodwatch.org/recommendation/seabass/white-seabass-54526)).

The 2017 evaluation of the OREHP hatchery program concluded it has **not substantially increased** the abundance of legal-sized WSB ([OREHP evaluation](https://caseagrant.ucsd.edu/sites/default/files/OREHP_EvalReport_12Dec2017.pdf)).

**Movements, depth and temperature (strong; electronic tags).**
- **Southern California Bight (Aalbers & Sepulveda 2015):** 173 depth/temperature data-storage tags deployed 2008–2011. 41 fish (24%) were recaptured between Baja and Half Moon Bay. Tagged fish made seasonal moves both up and down the coast and up and down the water column, and went deeper in December–February. About 95% of depth records were shallower than 50 m (maximum 245 m). Water temperature ranged 8.7–23.6 °C, mean 15.2 ± 1.4 °C. Fish moved widely during the spawning season, "consistent with limited residency periods at distinct spawning sites."
  - Implication: fish do **not** sit on one spawning reef all season. Aggregations are transient.
  - 77% of recaptures from fish tagged in the spawning season (March–July) were female.
- **Baja (Aalbers et al. 2021):** 89 fish tagged with internal data-storage tags (66–152 cm). They spent 95% of their time shallower than 60 m (maximum 158 m), went deeper in winter, and spent 73% of winter time at 13–16 °C.

**Spawning: season, time of day, moon and sound (strong for season and time of day).**
- **Season.** Spawning happens near shore from March to September, peaking in late spring to early summer ([OPC draft](https://opc.ca.gov/webmaster/_media_library/2019/08/Draft_Marine-Species-Report_WhiteSeaBass-1.pdf)). CDFG gives April–August ([CDFG](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=34417)).
- **Net-pen study, Catalina Harbor** ([Aalbers 2008, Fish Bull 106:143–151](https://spo.nmfs.noaa.gov/content/seasonal-diel-and-lunar-spawning-periodicities-and-associated-sound-production-white)). The study recorded 297 spawning events from 15 males and 47 females in a 526 m³ pen.
  - Spawning was consistent from March to July (2001–03) and peaked in May at a 14-hour day length.
  - **Most spawning occurred in the 2 hours after sunset (about 19:00–20:00 PST).**
  - Water temperature was about 15–18 °C.
  - Spawning occurred at **every lunar phase**. There was only a modest increase in back-to-back spawning nights after the new moon.
  - **No apparent correlation with tides.**
  - Sound rate, intensity and variety rose with the seasonal and daily spawning peaks.
  - One secondary summary says sound production was lower "for several days around the full moon." **UNVERIFIED**: secondary summaries conflict and I could not read the paper.
- **Sound types** ([Aalbers & Drawbridge 2008, TAFS](https://pier.org/userdocs/images/files/scientific_publications/Aalbers%20&%20Drawbridge%202008.pdf)). There are five sound types. Gamete release comes with "spawning chants" of overlapping drumrolls and thuds lasting 7–55 s.
- **Wild acoustic recorders** ([Aalbers & Sepulveda 2012, J Fish Biol](https://pubmed.ncbi.nlm.nih.gov/23130687)). Three long-term acoustic recorders sat off Camp Pendleton, sampling 2 hours around sunset, April–June 2009.
  - Courtship sounds were heard on 89%, 28% and 45% of days at the three sites.
  - Most spawning chants came **within 30 min of sunset in May–June**.
  - No consecutive-day spawning was apparent.
  - PIER has kept a passive acoustic array running since 2008, including recorders inside Southern California MPAs ([PIER](https://pier.org/project/white-seabass/)).
- **Sanctuary recordings.** Kim et al. 2025 (MEPS 764:135–159) analysed 18.3 recording-years from 9 sites in Monterey Bay, Chumash Heritage and Channel Islands sanctuaries (2018–2022). WSB chorused "day and night, with less consistency" than other species, in the midwater ([NOAA summary](https://sanctuaries.noaa.gov/news/2025/passive-acoustic-monitoring-fish.html)). The **manually logged chorus events are public on Dryad** ([doi:10.5061/dryad.q2bvq83sw](https://datadryad.org/dataset/doi:10.5061/dryad.q2bvq83sw)). This is a ready-made, fishery-independent presence/spawning label for a few sites.
- **Captive temperature cue.** Hatchery spawning is induced by raising water from 14 to 18 °C. That is a captive cue, not a confirmed wild one.

**Maturity (2026).** A new CDFW journal paper found **less than 1% of females are mature at the 28-inch legal size**. About 15% of recreational catch from 2008–2025 was under legal size ([CDFW Journal, Oct 2026](https://journal.wildlife.ca.gov/2026/10/08/maturity-of-white-seabass-in-california-waters/)).

**Habitat.** Adults use kelp-bed edges and nearby pelagic water. The forum and blog consensus is 15–80 ft for diver encounters ([SpearFactor](https://www.spearfactor.com/post/white-sea-bass-california-data-analysis-thousands-reports), anecdotal). Juveniles use shallow nearshore drift-algae habitat (**UNVERIFIED this session**; standard CDFW account).

**Diet (moderate; old and only qualitative).** A CDFG Fish Bulletin (1968) "cursory examination" found squid (*Loligo/Doryteuthis opalescens*), sardines and anchovies were eaten most often, plus pelagic red crabs when available. It also noted that "a night fishery occasionally develops when squid come close to shore to spawn" ([via eScholarship](https://escholarship.org/content/qt3t10h9kr/qt3t10h9kr.pdf); exact citation **UNVERIFIED**). I found **no modern quantitative WSB diet study**. One lead is a 2024 stable-isotope or diet paper on resource partitioning among weakfishes ([ResearchGate](https://www.researchgate.net/publication/384195079_Evidence_for_resource_partitioning_in_weakfishes_from_a_coastal_upwelling_ecosystem)); its contents are **UNVERIFIED**.

**Moon and tide: evidence versus folklore.**
- **Lunar effect: weak.** The only controlled data (the net pen) show spawning at all phases, with at most a small new-moon bump.
- The "squid spawn on the new moon, so WSB follow" story is **anecdotal**. Examples are SpearFactor's "June 14 new moon spawn window" post ([link](https://www.spearfactor.com/post/wsb-squid-bed-tactics-how-to-hunt-the-june-14-new-moon-spawn-window)) and captains' columns saying best catches come "near full and new moon" with strong current ([Noozhawk](https://www.noozhawk.com/captains-log-effects-of-moon-tides-and-currents-on-fishing)).
- **Tide: no evidence.** The net-pen study found no correlation. Current may affect bite or feeding (anecdotal), but for divers, tide mostly matters for visibility and current safety.

---

## 2. Market squid as a signal

**Biology.**
- Spawning beds are on **sand at about 20–93 m in Southern California** and 13–61 m in central California. Temperature and substrate appear to be stronger spawning cues than depth ([Zeidberg et al. 2012, Marine Ecology](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1439-0485.2011.00498.x)).
- Most squid presence, mating and egg-laying occur at night, though daytime spawning has been seen by ROV in Monterey (moderate; garbled snippet).
- Squid crash after strong El Niños (1982–83, 1997–98) but not after weak ones, and they shift north in warm years ([Zeidberg et al. 2006, CalCOFI](https://swfsc-publications.fisheries.noaa.gov/publications/CR/2006/06Zei.pdf); [CWPA 2020–21](https://californiawetfish.org/s/2020-21-SQUID-UPDATE.pdf)).
- The Southern California fishery is mainly a winter fishery (about Oct/Nov–Mar), while Monterey's runs spring–summer (**UNVERIFIED this session**; standard CDFW account).
- **Seasonal mismatch to note:** the main Southern California squid season is winter, but WSB peak in spring. The spring link is probably with *residual or late* squid spawning at the islands and in La Jolla canyon. Fishing lore strongly asserts this; it is quantitatively unproven.
- **Lunar effect on squid: anecdotal for California.** The "dark nights / new moon" claims come from anglers. A Japanese *Todarodes* study found higher new-moon catch, but it is a different species and fishing method. The more defensible mechanism is about the **fleet**, not the squid: moonlight weakens light attraction, so light-boat effort and catch probably fall at full moon (**UNVERIFIED** for California).

**Management features that bias any squid signal** ([MSFMP](https://wildlife.ca.gov/Conservation/Marine/MSFMP); [14 CCR §149](https://law.cornell.edu/regulations/california/14-CCR-149)):
- Lights are capped at 30,000 W per vessel, with shielding rules.
- **Weekend closures** give squid uninterrupted spawning time each week (noon Friday to noon Sunday per standard description; exact hours **UNVERIFIED**).
- The seasonal catch limit is 118,000 short tons (April–March season). After it is reached, landings are limited to 2 t/day; the 2025 amendment may have changed details.
- Seiners work with light boats.
- Consequence: **no squid fleet on weekends or after the limit is reached does not mean no squid.**

**Squid data sources**

| Source | What it contains | Spatial resolution | Time resolution and delay | Access |
|---|---|---|---|---|
| [CDFW Market Squid Landing Receipt page](https://wildlife.ca.gov/Conservation/Marine/Pelagic/Market-Squid-Landing) | Season tables (1999–2000 to 2021–22 seen); link to "weekly squid landings"; maps | Port/region; seasonal block maps hide blocks with fewer than 3 vessels per season | Weekly in-season tracking (current-season columns **UNVERIFIED**) | Public |
| [Marine Fisheries Data Explorer (MFDE)](https://cdfwmarine.wordpress.com/2023/10/05/new-commercial-fishing-data-explorer-now-available/) ([guide](https://wildlife.ca.gov/Conservation/Marine/Data-Management-Research/MFDE/User-Guide)) | Landings 1980–present: lbs, value, port, **3- and 4-digit block summaries**; e-tickets are "near real time" | Block (about 10×10 nm; new block chart from 1 Jan 2025, [metadata](https://filelib.wildlife.ca.gov/Public/BDB/GIS/BIOS/metadata/DS3093.html)) | Probably monthly or annual summaries (**UNVERIFIED**) | Public, but anything with fewer than 3 vessels/fishers/businesses is suppressed (Fish & Game Code §8022) |
| Squid vessel and light-boat logbooks | Set-level locations | Fine | — | **Confidential**; data request only. SB 609 (2025–26) would loosen confidentiality; status **UNVERIFIED** ([analysis](https://billtexts.s3.amazonaws.com/ca/ca-analysishttps-leginfo-legislature-ca-gov-faces-billAnalysisClient-xhtml-bill-id-202520260SB609-ca-analysis-391218.pdf)) |
| [CALFISH database](https://repository.library.noaa.gov/view/noaa/46659) / [ERDDAP fedCalLandings](https://upwell.pfeg.noaa.gov/erddap/tabledap/fedCalLandings.html) | Century-long non-confidential landings | Port/region | Annual/monthly, historical | Public |
| **VIIRS Boat Detection** ([NOAA EOG](https://eogdata.mines.edu/products/vbd/)) | Nightly detections of lit vessels; a single lit boat is detectable | About 750 m pixel | **Nightly, about 1 day delay** | Public |
| GFW night-light layer ([availability table](https://globalfishingwatch.org/global-fishing-watch-data-availability/), [tech doc](https://globalfishingwatch.github.io/GFW_technical_documentation/files/viirs-boat-detections.html)) | VBD matched to AIS where possible | — | Near real time, about 72 h delay | Data table shows map view only; API/download "not yet available" (re-check) |
| Paralarval surveys (CDFW/SWFSC/CWPA, CalCOFI) | Paralarval density | Survey station | Quarterly to annual, months of delay | Reports |

**Assessment.** VIIRS boat detections are the best low-latency proxy for "squid aggregated nearshore tonight." Squid light boats at 30 kW are among the brightest things in the Bight, and AIS coverage of the small California squid fleet is likely poor (**UNVERIFIED**). Processing needs:
- mask the static lights of Santa Barbara Channel oil platforms and harbours;
- filter by bathymetry (sand, about 20–100 m);
- account for weekend closures, moonlight and cloud cover;
- watch for double counting from two satellite passes per night.

---

## 3. Fishery-dependent WSB data

- **CRFS / RecFIN.** CRFS produces **monthly estimates by 6 districts × fishing mode**. "South" and "Channel" districts cover Southern California ([CRFS design](https://wildlife.ca.gov/Conservation/Marine/CRFS/Survey-Design); [methods](https://recfin.org/wp-content/uploads/2024/04/CRFS_Methods_2022.pdf)). The data are in RecFIN's `COMPREHENSIVE_REC_CATCH_EST` table ([InPort](https://www.fisheries.noaa.gov/inport/item/55977)), and the biological table carries a WSB tag field. They are too coarse for site forecasting but useful as a sanity check and for regional climatology. Delay is months (exact **UNVERIFIED**).
- **CPFV (party boat) logbooks.** These are mandatory. Each record has location fished (block), port, number of anglers, hours, species and number kept ([InPort](https://www.fisheries.noaa.gov/inport/item/2325)). Monthly e-logs are **due by the 10th of the following month** ([MFSU](https://wildlife.ca.gov/Conservation/Marine/MFSU)). Public summaries are annual by port and species, with records from fewer than 3 CPFVs suppressed. **Block × date × WSB-per-angler-hour data would be the best training label** but needs a CDFW data request or research agreement.
- **Commercial landings (PacFIN / CDFW).** Commercial WSB catch is mostly hook-and-line plus gillnet. Block-level data are in MFDE, subject to the 3-vessel rule.
- **Annual FMP reviews** of the recreational and commercial fishery have run since 2002 ([WSFMP](https://wildlife.ca.gov/Conservation/Marine/WSFMP); [FMP pdf](https://caseagrant.ucsd.edu/sites/default/files/wsfmp.pdf)).
- **Fish-count websites.**
  - [Sportfishingreport.com](https://sportfishingreport.com/ytd/202/white-seabass.php) publishes per-boat, per-date WSB tallies: fish, anglers, fish per angler. Example: *Apollo*, 61 WSB on 2 July 2025, 3.39 per angler. Its [terms](https://sportfishingreport.com/terms.php) **prohibit commercial use, redistribution, republication, syndication and automated access without written authorization.**
  - SoCalFishReports / SanDiegoFishReports (the "Fish Reports Network", [network page](https://www.socalfishreports.com/network.php)) say "All Rights Reserved." They also power the landings' own count pages ("Fish Count publishing service by SoCalFishReports.com", e.g. [22nd Street](https://www.22ndstreet.com/fishcounts.php)). I found no explicit terms page.
  - 976-TUNA terms: **UNVERIFIED**.
  - Landings' own pages, e.g. [Davey's Locker](https://daveyslocker.com/fish-count/), list date, boat, anglers, trip type and species counts.
  - **Location is only landing + trip type** (e.g. "3/4-day Catalina"); captains don't publish spots.
  - **Conclusion: license the data. Don't scrape.** A data partnership with landings or the Fish Reports Network is realistic and gives the lowest-delay label (same day).
- **Spearfishing and freediving community.** Spearboard forum posts, dive-shop reports, Instagram and blogs (e.g. SpearFactor's "data" posts, unsourced) are sparse, deliberately vague about location ("spot burning" is taboo), and legally and ethically messy to harvest. Spearboard's terms and Instagram's API limits (hashtag search is restricted to business accounts) are **UNVERIFIED**. Use them for qualitative validation, or invite users to submit reports with coarse location and a delay.

---

## 4. Non-fishery sightings

- **iNaturalist.** I could not query it (the host is blocked in this session). Run `https://api.inaturalist.org/v1/observations?taxon_name=Atractoscion%20nobilis&per_page=0`, and the same with `&quality_grade=research&nelat=34.6&nelng=-117&swlat=32&swlng=-121`. My **UNVERIFIED** expectation is high hundreds to low thousands of records in total, many of them angler catch photos rather than underwater sightings, clustered at La Jolla, Catalina and the Channel Islands. iNat also offers obscured coordinates and observation-date fields that are useful for a presence-only seasonal check.
- **REEF** (volunteer roving-diver surveys, with sighting frequency and abundance codes), **Reef Check California**, the **Channel Islands NP Kelp Forest Monitoring** roving-diver fish counts, and **PISCO / SBC LTER** kelp fish surveys. Whether each lists WSB, and how many records exist, is **UNVERIFIED**. Expect a **low sighting frequency**: WSB are midwater and wary, so transect divers rarely record them. Good for a seasonal or regional prior; useless for weekly prediction.
- **Acoustic presence data** (PIER array; the Kim et al. Dryad logs; NOAA SanctSound recordings) are the strongest fishery-independent presence and spawning series. Partnering with PIER is the highest-value scientific relationship.

---

## 5. Regulations and the risk of enabling targeting

- **Recreational:** open year-round. Minimum size 28 in total length (20 in or 20.5 in alternate length, depending on version). Bag limit is 3 fish, **except 1 fish south of Point Conception from 15 March to 15 June**, an explicit spawning-season protection ([CDFW Southern Region](https://www.wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/southern); [14 CCR §28.35](https://regulations.justia.com/states/california/title-14/division-1/subdivision-1/chapter-4/article-1/fin-fish-minimum-size-limits-bag-and-possession-limits-and-seasons/section-28-35)).
- **Commercial:** closed south of Point Conception 15 March–15 June. The exception is 1 fish ≥28 in per day taken incidentally in permitted gill or trammel nets ([§155](https://regulations.justia.com/states/california/title-14/division-1/subdivision-1/chapter-6/section-155)).
- **Possible change:** the 2026 maturity finding (above) and a possible size-limit increase are under discussion ([Saltwater Sportsman](https://www.saltwatersportsman.com/news/potential-downsides-of-increasing-the-minimum-size-limit-for-white-seabass/)).
- **MPAs:** the South Coast network (in force since 2012) includes no-take reserves (e.g. La Jolla's Matlahuayl) and some conservation areas that allow spearing of pelagic finfish including WSB. Per-MPA rules are **UNVERIFIED** here.

**Risk.** A forecast tuned to spring, dusk and squid beds is essentially a guide to **transient spawning aggregations**. That is exactly when managers already cut the bag limit, and when 99% of legal-size females are still immature. Aggregation fishing also creates hyperstability: catch rates stay high while the stock declines.

**Mitigations:**
- forecast at zone × week resolution, never GPS points;
- no point-level or same-day maps from 15 March to 15 June;
- show the spawning-season bag limit and MPA boundaries;
- frame the product around observation and photography;
- never publish user-submitted locations at better than zone resolution or without a delay.

Agencies and PIER are unlikely to share data with a product seen as a targeting tool.

---

## 6. Synthesis and MVP

**Strength of each signal**

| Signal | Expected value | Evidence |
|---|---|---|
| Season (day of year) × region | High: spawning-season nearshore, inshore March–July, deeper in winter | Strong |
| Recent WSB reports in the same or neighbouring zone, last 1–2 weeks | Highest short-term skill (fish move between sites, but runs persist for days to weeks) | Strong (logic and fishery practice); not quantified |
| Water temperature (SST and anomaly; roughly 14–18 °C window; warm or El Niño years shift fish north) | Moderate to high | Moderate (tags, captive cues) |
| Squid aggregation index (VIIRS light boats within about 10 km over 20–100 m sand; CDFW weekly squid landings) | Moderate. Plausible; diet support plus heavy fishing lore; untested quantitatively. Confounded by weekend closures and moon | Moderate / anecdotal |
| Time of day (dusk, 0–2 h after sunset; dawn) | High for *when* within a day, especially in spawning season | Strong (net pen plus wild acoustics) |
| Lunar phase | Weak direct effect; indirect via squid-fleet effort | Weak |
| Tide | No direct evidence; affects current and visibility | Anecdotal / none |
| Upwelling (CUTI/BEUTI), ENSO (ONI) | Seasonal-to-yearly modifier, also of squid | Moderate |

**Recommended MVP**
- **Unit:** about 10 zones × ISO week. Zones: Point Conception/Santa Barbara Channel; Santa Rosa & San Miguel; Santa Cruz & Anacapa; Malibu & Santa Monica Bay; Palos Verdes; Catalina; San Clemente Island; Orange County; North San Diego County; La Jolla to Point Loma; Coronado Islands (Mexico).
- **Label:** CPFV daily counts licensed from the landings. Map landing + trip type to zone(s), define y = any WSB, and use log(trips or anglers) as an effort offset. Replace with **CPFV logbook block data** via a CDFW request when it arrives (monthly, 10-day delay; best label).
- **Independent validation:** PIER and Dryad acoustic chorus logs; iNat and REEF presence for the seasonal shape.
- **Model:** a logistic GAM (or penalized logistic regression):
  `logit P = zone + s(day-of-year, cyclic) + SST anomaly + s(SST) + lagged reports (zone, neighbours) + squid-light index + lunar illumination + ONI + offset(log effort)`
  Move to gradient-boosted trees only if they beat it.
- **Evaluation:** temporal holdout (e.g. train through 2022, test 2023–2025), Brier score, log loss and calibration. **The model must beat two baselines: climatology (zone × week mean) and persistence (last week's reports).** Use ablations to show whether squid and moon add anything; that is how the founder's hypothesis gets tested honestly.
- **Diver-facing output:** a weekly relative-likelihood map by zone, a best window within the day (dusk/dawn), and a separate visibility forecast (swell, rain runoff, chlorophyll). Fishing data measure hook-and-line catch, not whether a diver will see fish.

**Good second species**
- **Giant sea bass (*Stereolepis gigas*).**
  - Highly predictable summer aggregations (about June–September) at known kelp sites: La Jolla, Catalina, Anacapa.
  - Courtship and spawning just after dusk ([Copeia 2018](https://bioone.org/journals/copeia/volume-106/issue-1/CE-17-620/Field-Observations-on-Courtship-and-Spawning-Behavior-of-the-Giant/10.1643/CE-17-620.full)).
  - Photo-ID citizen science exists ("Spotting Giant Sea Bass"; **UNVERIFIED** current status).
  - Protected from take, so a forecast is less of a harvest risk, though diver harassment needs guidelines.
- **Leopard sharks at La Jolla Shores.** Dependable warm-water aggregation from about July to October, made up mostly of pregnant females. It is shallow and easy for snorkelers, with abundant iNat records. Details **UNVERIFIED** this session.
- **Gray whales** are the most data-rich alternative (daily census counts December–May), but they are a different, simpler product.
