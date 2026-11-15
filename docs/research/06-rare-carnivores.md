# Rare and cryptic terrestrial carnivores (mountain lion, gray wolf): data sources, signals, ethics and estimands for wildlife-scanner

**How this was checked.** This session could not reach nps.gov, wildlife.ca.gov or api.inaturalist.org; direct fetches were blocked by the network allowlist. Every "current status" claim below therefore comes from web-search results, which include agency PDFs, news and law-firm summaries. Claims I could not confirm are marked **UNVERIFIED**. Claims from my own knowledge of the literature that I did not re-check here are marked *(lit., not re-verified)*.

## 0. Bottom line
- **Seeing a mountain lion or wolf is not a predictable quantity in Southern California.** Three things can be modelled usefully:
  - territory-scale occupancy;
  - the probability of detecting *sign* (tracks, scat) or getting a camera detection;
  - "awareness" risk context for safety.
- **Sighting probability is a valid estimand only in managed viewing systems.** Examples are Lamar Valley, Torres del Paine, Porto Jofre and Sierra de la Culebra. These all have high density, long sightlines, low persecution (habituation), a network of human spotters, and some form of governance.
- **Agencies publish carnivore locations coarsened and/or delayed, for conflict awareness only.** No agency publishes them to help people find the animals. Wildlife Scanner needs its own species × region sensitivity policy. It should not rely on upstream obscuring: iNaturalist status for *Puma* in CA is UNVERIFIED, and Wildlife Insights fuzzes only IUCN CR/EN/VU species, which excludes both of these LC species.

## Summary table of data sources

| Source | What it provides | Spatial resolution | Latency | Access | License / commercial use | Relevance |
|---|---|---|---|---|---|---|
| NPS Santa Monica Mtns NRA puma study ([puma profiles](https://www.nps.gov/samo/learn/nature/puma-profiles.htm), [news](https://www.nps.gov/samo/learn/news/mountain-lion-p-104-killed-by-vehicle-strike.htm)) | Narratives on individual lions (P-numbers), mortality, crossings; papers built on 128k GPS fixes ([JWM 2021](https://bvbvf1.bib-bvb.de/vufind/PrimoRecord/cdi_proquest_journals_2580660693)) | Narrative and general-area maps only; raw GPS not public (no Dryad or Movebank record found) | Days to months | Public web pages | Text is US-gov; data restricted | Priors on home range and behaviour; validation anecdotes |
| UC Davis Mountain Lion Project (Santa Ana / Peninsular Ranges) ([genetics](https://www.ucdavis.edu/news/southern-california-mountain-lions-genetic-connectivity-dangerously-low), [VoiceOC 2026](https://voiceofoc.org/2026/08/from-backcountry-to-museums-oc-mountain-lions-at-the-brink-of-extinction/)) | Mortality causes, genetics, crossing hotspots (I-15, Ortega Hwy) | Papers and press | Months to years | Publications | Per paper | Mortality and connectivity priors |
| CDFW mountain lion pages ([attacks](https://wildlife.ca.gov/Conservation/Mammals/Mountain-Lion/attacks), [FAQ](https://wildlife.ca.gov/Conservation/Mammals/Mountain-Lion/FAQ)); [WIR reporting](https://apps.wildlife.ca.gov/wir) | Verified-attack list; annual depredation stats; WIR is an intake system | Attacks: locality text. Depredation: county or annual | Annual | Public pages; WIR has no public dashboard or export found | Gov info; bulk depredation data by request (UNVERIFIED) | Conflict and awareness layer |
| CDFW CESA status review (Dec 2025) and Fish and Game Commission listing ([CBD summary](https://biologicaldiversity.org/w/news/press-releases/wildlife-department-urges-protections-for-californias-most-imperiled-pumas-2025-12-10/), [status review PDF mirror](https://www.indybay.org/uploads/2025/12/10/16._mountain_lion_esu_status_review_dec_9_2025_ada.pdf)) | Six genetic populations, threats, abundance | Population polygons | One-off | Public | Gov | Sensitivity tiering; regional boundaries |
| UC Davis CROS roadkill ([program](https://roadecology.ucdavis.edu/research/projects/cros), [15-yr paper](https://roadecology.ucdavis.edu/conference-proceedings-and-papers/fifteen-years-largest-us-wvc-reporting-system-california-roadkill), [hotspots 2024](https://roadecology.ucdavis.edu/sites/g/files/dgvnsk8611/files/files/CROS-CHIPs_Hotspots_2024_fin.pdf)) | About 213k wildlife-vehicle-collision records; puma hotspots on about 15k mi of state highway; about 70 lions/yr hit on state highways | Point locations | Public map shows the last 90 days | Map public; bulk data by request (UNVERIFIED) | Unclear; data held in "a private, non-University system" | Hard-evidence presence near roads; dispersal signal |
| CDFW gray wolf program ([main](https://www.wildlife.ca.gov/Conservation/Mammals/Gray-Wolf), [tracker](https://www.wildlife.ca.gov/Conservation/Mammals/Gray-Wolf/Location-Map), [tracker launch](https://wildlife.ca.gov/News/Archive/cdfw-releases-new-wolf-location-mapping-system)) | (a) Territory ("known wolf activity") map; (b) Wolf Location Automated Mapping System, the last fix of each collared wolf; (c) "Known Wolves" PDF; quarterly updates; annual report | (a) Approximate territory polygons, dispersers excluded. (b) Hexagon of about 4.5 mi² (~11.7 km²) | (a) Quarterly or "as warranted". (b) Daily | Public | Gov; intent is livestock-conflict avoidance | Coarse priors only. Do **not** redistribute the tracker |
| ODFW wolves ([updates](https://dfw.state.or.us/Wolves/updates.html), [packs/AKWA](https://www.dfw.state.or.us/Wolves/Packs/), [2025 report](https://dfw.state.or.us/Wolves/docs/oregon_wolf_program/2025_Annual_Wolf_Report_FINAL_260417.pdf)) | AKWA polygons ("documented repeatedly over a period of time"); county maps; annual counts | AKWA polygons | Periodic; annual report each April | Public PDFs | Gov | Territory priors |
| WDFW wolves ([pack polygons REST](https://geodataservices.wdfw.wa.gov/arcgis/rest/services/WP_Statewide/Wolf_PackPolygons/MapServer), [monthly reports](https://wdfw.wa.gov/species-habitats/at-risk/species-recovery/gray-wolf/updates/monthly-wolf-report-april-2025)) | Pack range polygons, or generic circles where locations are few; monthly reports | Polygon or circle | Annual (map), monthly (text) | ArcGIS REST, public | Gov | Machine-readable territory prior |
| Colorado CPW wolf map ([CPW](https://cpw.state.co.us/news/04242024/cpw-releases-updated-collared-gray-wolf-activity-map-launches-depredation-report), [CBS](https://www.cbsnews.com/colorado/news/colorado-parks-and-wildlife-new-wolf-activity-map)) | Watersheds with at least one collar fix in about the last 30 days; buffered during sensitive periods; no GPS released | Watershed | Monthly | Public | Gov | Reference pattern for publishing policy |
| Yellowstone Wolf Project ([2025 report](https://www.nps.gov/yell/learn/upload/2025-YELL-Wolf-Cougar-Elk-Project-Annual-Report-508.pdf), [FOIA](https://www.nps.gov/aboutus/foia/upload/YELL_1155M_Wolf_ForWeb.pdf)) | Annual pack counts and demography. Wolf UTM locations and collar frequencies are **withheld** under FOIA exemption (b)(3) | Pack and park level | Annual | Public reports | Gov | Viewing-context priors |
| Montana FWP harvest ([regs](https://fwp.mt.gov/hunt/regulations/wolf), [2026 coverage](https://idahocapitalsun.com/2026/08/24/repub/montana-fish-and-wildlife-commission-takes-middle-ground-on-wolf-hunting-quotas/)) | Quotas and harvest by wolf management unit | WMU | In-season | Public | Gov | Risk layer (boundary harvest) |
| Wildlife Insights ([FAQ](https://wildlifeinsights.org/faq), [sharing](https://wildlifeinsights.org/get-started/share-data/sharing-preferences)) | Camera-trap images and detections | Exact coordinates, except fuzzing for IUCN CR/EN/VU species | Per project; embargoes allowed | Public download plus Terms of Use | Images CC0, CC BY or CC BY-NC; metadata CC BY or CC BY-NC, set per project; **NC blocks commercial use** | Core detection data. Puma and wolf (LC) are probably **not** auto-fuzzed |
| Snapshot USA ([2024 on Dryad](https://datadryad.org/dataset/doi:10.5061/dryad.bnzs7h4qf), [2019–23](https://www.conservationgateway.org/collections/biodiversity/snapshot-usa-camera-trap-mammal-dataset-2019-2023/)) | Coordinated national camera survey: 2024 has 377k sequences and 3,127 deployments, released June 2026 | Deployment points | About 18 months | Open | Dryad standard is CC0 (verify on the record) | Calibrating camera detection rates |
| eMammal ([FAQ](https://emammal.si.edu/faq)) | Legacy repository; data entry moved to Wildlife Insights | — | — | — | — | Historical only |
| Zooniverse projects ([Wildlife of LA](https://www.zooniverse.org/projects/lawildlife/wildlife-of-los-angeles), [Crystal Cove](https://www.zooniverse.org/projects/crystalcoveconservancy/crystal-cove-critter-cams)) | Volunteer-classified camera images | Held by project teams | — | Not bulk-public | Per project | Partnerships, not ingestion |
| Movebank ([permissions](https://www.movebank.org/cms/movebank-content/permissions-and-sharing)) | GPS tracks | Fix-level | — | Owner-controlled; most carnivore studies are restricted; owners can make a study discoverable with no locations shown | CC for public studies; custom terms otherwise | Research partnerships only |
| iNaturalist / GBIF ([geoprivacy](https://help.inaturalist.org/support/solutions/articles/151000169938)) | Community observations | Obscured cell is 0.2°×0.2° (≈22×18 km, ~400 km² at 34°N) | Near real time | API | Mostly CC BY-NC | Presence-only and awareness. CA status of *Puma* is UNVERIFIED |
| Panthera / Torres del Paine guidelines ([Panthera](https://panthera.org/blog-post/paving-way-human-puma-coexistence-chilean-patagonia)) | Viewing protocol that became a municipal ordinance (Aug 2025) | — | — | Public | — | Policy template |

## 1. Mountain lions in Southern California

- **NPS SMM study.** Running since 2002.
  - The population is about 10–15 adult and subadult lions in the Santa Monica Mountains.
  - Adult male home ranges average about 372 km² (144 mi²) and adult females about 134 km² (52 mi²). Fragment-bound males use far less: P-22 used 9 mi² ([NPS home range](https://www.nps.gov/samo/learn/nature/mtlion-homerange.htm), [15-yr analysis](https://www.nps.gov/samo/learn/news/analysis-of-first-15-years-of-mountain-lion-locations-reveals-they-thrive-in-shrublands-and-rarely-enter-residential-areas.htm)). The 15-year analysis found lions "thrive in shrublands and rarely enter residential areas."
  - P-104 was the 25th lion killed by a vehicle since 2002 ([NPS](https://www.nps.gov/samo/learn/news/mountain-lion-p-104-killed-by-vehicle-strike.htm)).
  - The current collared count and latest P-number are **UNVERIFIED**; the NPS pages could not be fetched. Raw GPS is not public. Publicly you get narratives, occasional after-the-fact maps, and papers.
- **Santa Ana Mountains (UC Davis).**
  - About 20 adults, with the lowest puma genetic diversity recorded outside the Florida panther. Of 7 males that crossed I-15 over 20 years, only 1 bred ([UC Davis](https://www.ucdavis.edu/news/southern-california-mountain-lions-genetic-connectivity-dangerously-low)).
  - Vehicle strikes cause about half of collared-lion deaths. Ortega Hwy remains a hotspot in 2026 ([VoiceOC](https://voiceofoc.org/2026/08/from-backcountry-to-museums-oc-mountain-lions-at-the-brink-of-extinction/)).
  - A population viability analysis gives a 16–21% chance of demographic extinction in 50 years for the Santa Ana population. Inbreeding risk is higher in the Santa Monica population. Modest immigration sharply cuts extinction risk ([Benson et al. 2019](https://www.sciencedaily.com/releases/2019/03/190320102158.htm)).
  - Physical inbreeding signs (kinked tails, cryptorchidism): **UNVERIFIED** this session.
- **Legal status (as of Nov 2026).**
  - Lions statewide have been a "specially protected mammal" since Prop 117 (1990), so there is no hunting *(lit.)*. The SC/CC populations had full CESA *candidate* protection from 2020.
  - On **Feb 12, 2026** the Fish and Game Commission voted unanimously to list the **Southern California/Central Coast DPS** as **threatened**. The DPS covers six genetic populations: Santa Cruz Mtns, Central Coast, Santa Monica Mtns, San Gabriel/San Bernardino, Santa Ana Mtns, and Eastern Peninsular ([NatLawReview](https://natlawreview.com/article/mountain-lion-listed-threatened-species-central-and-southern-california-under), [Allen Matkins](https://www.allenmatkins.com/real-ideas/mountain-lion-listed-as-threatened-species-in-central-and-southern-california-under-the-california-endangered-species-act.html), [MLF](https://mountainlion.org/2026/02/12/why-threatened-status-matters-for-southern-and-central-coast-mountain-lions/)).
  - Some outlets wrongly say "endangered." Adoption of the formal findings appeared still pending in late Oct 2026: **UNVERIFIED**.
  - Exemptions for lethal removal (public safety, depredation) remain.
- **Conflict data.**
  - In 2025 CDFW received **518 depredation reports** and issued **220 permits, 72% of them non-lethal** (SB 1397 analysis: [Assembly analysis](https://awpw.assembly.ca.gov/media/1254), [bill tracker](https://calmatters.digitaldemocracy.org/bills/ca_202520260sb1397)). The bill passed the Senate 39-0; its final outcome is **UNVERIFIED**.
  - Verified attacks: fewer than 50 since 1890, 6 fatal, including the 2024 El Dorado County death ([AccuWeather](https://www.accuweather.com/en/weather-news/first-fatal-mountain-lion-attack-in-california-in-20-years-leaves-one-man-dead-brother-injured-authorities-say/1634629)).
  - An attack on a child in Malibu was reported in Aug 2025 ([ABC7](https://abc7.com/post/11-year-old-attacked-injured-mountain-lion-malibu/17502490/)).
  - CDFW says more sightings do not mean more lions ([FAQ](https://wildlife.ca.gov/Conservation/Mammals/Mountain-Lion/FAQ)). WIR is intake-only; I found no public sighting dataset.
- **Wallis Annenberg Wildlife Crossing (US-101, Liberty Canyon).** Ribbon-cutting is set for **Dec 2, 2026**; the project was "on track for completion in December" ([Spectrum News](https://spectrumnews1.com/ca/la/environment/2026/04/23/the-wallis-annenberg-wildlife-crossing-is-in-full-bloom-and-on-track-for-completion-in-december-2026)). A first animal visitor was reported May 31, 2026 (species **UNVERIFIED**). Measurable effects on lion connectivity or genetics will take years.
- **Roadkill.** CROS has about 213k records statewide, and puma road deaths fell about 10% from 2015 to 2022 ([CapRadio](https://www.capradio.org/articles/2023/10/10/what-roadkill-can-tell-us-about-californas-deer-and-mountain-lion-populations/)). Roadkill records are high-certainty presence data, but heavily biased toward roads.
- **iNaturalist obscuring.** iNat obscures by taxon or place conservation status into a 0.2° cell, or the observer can obscure manually. *Puma* records **are** obscured in parts of Brazil ([example](https://ala-hub.sibbr.gov.br/ala-hub/occurrences/f2dff911-a945-4a7b-b916-f76e5bb47bfb)). Whether *Puma concolor* carries a CA status that triggers auto-obscuring is **UNVERIFIED**. Puma is G5/LC, and the CESA listing is a DPS rather than a taxon, so it is plausibly *open* by default. Assume precise CA lion coordinates may be public, and apply our own controls.

## 2. Gray wolves

- **California.**
  - State endangered under CESA since 2014. California is in "Phase 2" of its 2016 wolf plan (at least 4 breeding pairs for 2 consecutive years).
  - The 2025 annual report counted 9 packs at year-end. Secondary coverage of the March 2026 update says **12 packs** ([edhat](https://www.edhat.com/california/news/californias-gray-wolf-population-grows-to-12-packs-new-report-shows/), [CFBF](https://www.cfbf.com/ag-advocacy/advocacy-updates/newsletter-content/may-22-2026/california-department-of-fish-and-wildlife-issues-2025-gray-wolf-annual-report)). There is a "Known Wolves – July 2026" PDF; its total is **UNVERIFIED**.
  - The southernmost resident pack is the Yowlumni pack (Tulare County). The disperser **BEY03F** entered LA County on Feb 7, 2026, returned north, and reached Sequoia NP in May 2026 ([LAist](https://laist.com/news/a-gray-wolf-was-found-in-la-county-for-the-first-time-in-100-years), [AccuWeather](https://www.accuweather.com/en/weather-news/gray-wolf-travels-to-los-angeles-county-marking-southernmost-track-in-modern-california-history/1862895)).
- **CDFW publishing practice.**
  - The territory map shows "approximate boundaries of known resident wolf territories… dispersing wolves are not included," updated quarterly or as warranted.
  - **Separately**, since May 15, 2025 the Wolf Tracker shows each collared wolf's last fix in a hexagon of about 4.5 mi², updated **daily**. It launched with 14 collared wolves and is meant for livestock producers ([CBD](https://biologicaldiversity.org/w/news/press-releases/new-california-wolf-map-aims-to-prevent-conflict-2025-05-15/), [WLJ](https://www.wlj.net/cdfw-releases-new-wolf-tracking-system/)).
  - That is far finer than any responsible consumer output. Wildlife Scanner should not ingest it for redistribution.
- **Federal status.**
  - Wolves outside the Northern Rockies DPS have been endangered since the 2022 vacatur. The Northern Rockies (MT, ID, WY, eastern OR/WA) remain state-managed.
  - A House delisting bill passed in Dec 2025; I found no Senate action. An executive order on **Sept 4, 2026** directed Interior to make a final listing determination ([TWS](https://wildlife.org/gray-wolf-listing-reinstated-under-endangered-species-act/), [Bloomberg Gov](https://news.bgov.com/environment-and-energy/trumps-removal-of-wolf-protections-seen-as-ripe-for-challenges)).
  - Ninth Circuit oral arguments in three appeals were heard **Oct 13, 2026** ([Spokesman](https://www.spokesman.com/stories/2026/oct/14/should-wolves-lose-endangered-species-status-trump/)). I found no ruling and no proposed rule as of Nov 11.
  - CESA protection in CA is independent of the federal outcome.
- **Oregon and Washington.**
  - Oregon, end of 2025: minimum **230 wolves, 30 packs, 23 breeding pairs**, and 106 confirmed livestock attacks ([ODFW report](https://dfw.state.or.us/Wolves/docs/oregon_wolf_program/2025_Annual_Wolf_Report_FINAL_260417.pdf)).
  - Washington, end of 2025: **270 wolves, 49 packs, 23 breeding pairs**. The count is pack minimums plus 12.5% for lone wolves ([Spokesman](https://www.spokesman.com/stories/2026/apr/17/washington-wolf-numbers-up-17/), [CNW](https://conservationnw.org/news-updates/new-state-report-shows-continued-wolf-recovery-in-washington/)).
  - Both publish territory-level polygons, not points.
- **Yellowstone.**
  - End of 2025: **84 wolves in 7 packs plus 1 group**, down from 108, with poor pup survival and distemper ([NPS 2025 report](https://www.nps.gov/yell/learn/upload/2025-YELL-Wolf-Cougar-Elk-Project-Annual-Report-508.pdf)).
  - How people actually find wolves:
    - Winter in Lamar, Slough Creek and Little America; dawn and dusk; spotting scopes at half a mile or more; "find the scopes and you've found the wolves"; carcasses and ravens ([Nat Hab](https://www.nathab.com/articles/us-national-parks/yellowstone/how-to-see-wolves/), [TNC](https://blog.nature.org/2017/05/23/tips-seeing-wolves-bears-yellowstone-national-parks)).
    - Watchers coordinate on a shared radio channel ([RadioReference](https://wiki.radioreference.com/index.php/Yellowstone_National_Park)).
    - Collar frequencies are officially withheld, but some watchers use receivers ([Outside Bozeman](https://outsidebozeman.com/culture/conservation/pack-mentality)).
  - Boundary harvest:
    - About 20–25 park wolves were killed outside the park in 2022–23 ([CBS](https://www.cbsnews.com/amp/news/yellowstone-wolves-20-killed-hunters-outside-park)), and Junction Butte wolves have since been shot ([ABC](https://abc7.com/post/poacher-illegally-kills-prominent-wolf-yellowstones-most-viewed-pack-officials/18501428/)).
    - Montana's 2025–26 season: quota 452, harvest 247 ([Idaho Capital Sun](https://idahocapitalsun.com/2026/08/24/repub/montana-fish-and-wildlife-commission-takes-middle-ground-on-wolf-hunting-quotas/)).
    - Visitor sighting odds were **45% higher** in years with no harvest of road-associated packs, and more than 2× higher in Denali when a no-hunting buffer existed ([NPS/Borg et al. 2016](https://www.nps.gov/dena/learn/news/wolf-harvest-affects-viewing-opportunities.htm)).
- **Sierra de la Culebra (Spain).**
  - Viewing happens from elevated viewpoints at dawn and dusk with telescopes, led by about 16 operators ([Picuco](https://www.picuco.com/en-es/activities/iberian-wolf-watching-in-sierra-de-la-culebra), [TERRA paper](https://ojs.uv.es/index.php/TERRA/article/download/16822/15846)).
  - Policy has been volatile. Wolves were added to Spain's nationwide strict-protection list (LESRPE) in 2021. Spain reopened hunting north of the Duero, which includes Zamora, in spring 2025 ([Murcia Today](https://m.murciatoday.com/controversial-decision-wolves-can-be-hunted-again-north-of-the-duero-river_1000198581-a.html)). Conflicting court rulings followed (**UNVERIFIED**).
  - The EU moved the wolf to "protected" (Bern Convention change effective Mar 7, 2025; Habitats Directive Annex IV→V on June 5, 2025) ([EP](https://www.europarl.europa.eu/news/en/press-room/20250502IPR28221/wolves-meps-agree-to-change-eu-protection-status)).
- **Product implication.** Wolf-finding in these places is a social sensor network: scopes, radios, guides and carcass knowledge. A product that scales or broadcasts real-time pack locations removes the friction that currently limits crowding and the risk of animals being targeted.

## 3. Puma viewing tourism and other managed cryptic-carnivore viewing

- **Torres del Paine and neighbouring estancias (e.g., Laguna Amarga).**
  - Trackers posted on ridges scan with binoculars, read guanaco alarm behaviour, and call guides by radio; viewing peaks at dawn and dusk ([Cascada](https://www.cascada.travel/blog/all-you-need-to-know-about-puma-spotting-in-patagonia), [EcoCamp](https://www.ecocamp.travel/blog/tracking-pumas-in-torres-del-paine)).
  - Density is about 5.1 independent pumas per 100 km² (CI 2.2–10.3) ([Panthera](https://panthera.org/blog-post/cougar-calculator-counting-chiles-cats)). Habituation is widespread, and puma presence declines near trails and roads in peak season.
  - Operators claim 80–90% success over 3 days; this is marketing.
  - The municipal good-practice ordinance (Aug 2025) grew out of the Panthera/TNC draft guidelines ([Panthera](https://panthera.org/blog-post/paving-way-human-puma-coexistence-chilean-patagonia), [Sierra](https://sierraclub.org/sierra/puma-population-patagonia-booming-now-what)).
- **Pantanal jaguars (Porto Jofre).** Daily sighting odds are near 100%, but more than 30 boats can crowd one jaguar, and researchers are calling for boat caps ([Mongabay 2025](https://news.mongabay.com/2025/09/in-brazils-pantanal-too-many-tourists-may-be-the-jaguars-new-predator/)).
- **Hemis snow leopards.** Winter trips rely on paid local spotters ([Adventure.com](https://adventure.com/snow-leopard-trackers-ladakh-india)).
- **Finnish bait hides for wolves and wolverines, and Indian leopard sites.** Established but **UNVERIFIED** this session.
- **The pattern.** Viewing works only with high density, open terrain, habituation, spotters and some governance. None of these holds for pumas in SoCal chaparral.

## 4. Data types for cryptic mammals

- **Camera traps.**
  - Wildlife Insights licenses per project, and NC licenses block commercial use. It fuzzes deployment coordinates only for IUCN CR/EN/VU vertebrates ([FAQ](https://wildlifeinsights.org/faq)), so puma and wolf are probably exact in public downloads (**verify**).
  - Fuzzing can be defeated: heuristics plus satellite imagery cut the candidate area by 87% under 1 km obfuscation ([Beery & Bondi 2021](https://arxiv.org/abs/2106.11236)). The images themselves leak location.
  - Placement dominates detection. On-trail cameras raise detection for nearly all mammals ([2025](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12329709/)), and pumas follow trails more closely than jaguars do (Harmsen 2010, [WCS](https://library.wcs.org/en-us/doi/ctl/view/mid/33065/pubid/PUB13953.aspx)).
  - Snapshot USA gives standardized multi-year rates. eMammal is legacy. Zooniverse projects are partnership-only.
- **Track and sign surveys, snow, eDNA.**
  - Scandinavian snow-tracking plus DNA monitoring re-detected territorial wolves in 94% of cases and caught 97% of reproduction events ([Åkesson 2022](https://openpolar.no/Record/crwiley:10.1002%2Fjwmg.22206)).
  - Finnish track indices follow wolf trends ([Kojola 2014](https://bioone.org/journals/wildlife-biology/volume-20/issue-5/wlb.00042/Tracks-in-snow-and-population-size-estimation--the-wolf/10.2981/wlb.00042.full)).
  - Snow surveys show strong serial and spatial correlation in detection ([Whittington 2015](https://datadryad.org/stash/dataset/doi:10.5061/dryad.v4p20)).
  - eDNA from snow tracks detects lynx at a few cells per liter. Individual genotyping from snow-track eDNA succeeded for 7 of 10 wolf samples ([Franklin](https://www.sciencedaily.com/releases/2018/11/181127111055.htm)).
  - Scat-detection dogs and water or air eDNA are viable *(lit., not re-verified)*.
- **GPS collars (Movebank).** Owner-controlled. Carcass and collar studies are typically restricted, and owners can make a study discoverable without showing locations ([Movebank](https://www.movebank.org/cms/movebank-content/permissions-and-sharing)).
- **Roadkill.** CROS (CA). Data is road-biased but high-certainty presence.
- **Conflict and depredation.** CDFW lion depredation permits (annual); state wolf depredation investigations (ODFW, WDFW, CDFW reports).
- **Harvest.** Montana, Idaho and Wyoming wolves. Puma harvest in other western states is not relevant to CA.
- **Community sighting reports and misidentification.**
  - Missouri: under 1% of thousands of reports since 1994 yielded physical confirmation ([MDC](https://mdc.mo.gov/wildlife/report-wildlife-sightings/mountain-lion-reports)).
  - Oklahoma: about 75 reports a month but about 25 confirmations in 15 years ([HPPR](https://www.hppr.org/post/mountain-lions-kansas-possible-not-likely)).
  - Mountain Lion Foundation estimate: up to 90% false alarms ([Felidae](https://felidaefund.org/news/general/mistaken-mountain-lion-sightings-have-major-consequences)).
  - Common confusions: dogs, bobcats, coyotes and house cats; for wolves, dogs, coyotes and hybrids.
  - These rates come from areas *outside* lion range. The in-range misidentification rate in CA is **UNVERIFIED** but non-trivial.
  - Media events (P-22, BEY03F) cause reporting spikes, and one lion produces many duplicate reports.

## 5. Predictive signals: strength of evidence

| Signal | Puma evidence | Wolf evidence | Best use |
|---|---|---|---|
| Diel (crepuscular/nocturnal) | **Strong.** Near people, lions are more active and move farther at night ([Wang 2017](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5636101/)). In high-recreation LA areas they are less active at dawn and dusk and shift to mid-night ([Bolas 2025](https://wildlife.org/mountain-lions-change-timing-of-activity-in-response-to-recreation/)) | **Strong.** Crepuscular where undisturbed, nocturnal with human pressure ([Theuerkauf 2009](https://agris.fao.org/search/en/records/65df85dd90674e46e653ce95), [Iberia 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11494153)) | Availability and awareness timing |
| Season / prey phenology | **Moderate, system-dependent.** Kill rates rise in summer and autumn with fawns in one black-tailed deer system; no seasonal change in S. Yellowstone or NE Washington; lions follow migratory deer upslope ([PLoS 2013](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3861499/)). Subadults (1–3 yr) disperse ([UNL](https://newsroom.unl.edu/announce/snr/19555/105019)); the seasonal peak of dispersal is **UNVERIFIED** | **Strong.** Breeding Jan–Feb, dens Apr–May, summer rendezvous sites, late-winter/spring dispersal *(lit.)*. Winter snow concentrates elk, which drives Lamar viewing | Prior on use intensity; den and rendezvous periods are when **suppression** is most needed |
| Snow / substrate | **Strong for detecting sign**, but rare in SoCal outside high elevations. Days since rain matters for mud tracks (**UNVERIFIED**) | **Strong.** The basis of the Nordic monitoring programs | Sign-detection model |
| Moon | **Weak.** Meta-analysis: moonlight on average suppresses carnivore activity ([Prugh & Golden 2014](https://uaf.edu/news/archives/news-archives-2010-2021/death-moonlight.php)); prey avoid brighter hours ([EurekAlert](https://www.eurekalert.org/news-releases/564481)) | Weak to moderate: wolves hunted almost twice as successfully on moonlit nights (Theuerkauf 2003, cited above) | Low-weight covariate |
| Weather | Weak to moderate; heat pushes activity into the night (**UNVERIFIED**) | Weak to moderate | Detectability (rain or wind erases sign) |
| Human activity | **Strong.** Lions avoid within about 30 m of busy trails in the Santa Cruz Mtns (Current Biology, [GearJunkie](https://gearjunkie.com/outdoor/strava-data-mountain-lions-avoid-people)); temporal shifts | Strong (roads, harvest). Yellowstone wolves are habituated to roads | Spatial and temporal avoidance term |
| Cover / water | Moderate: lions select shrubland, avoid residential areas (NPS 15-yr). Water: **UNVERIFIED** | Moderate | Habitat model |
| Prey | Moderate: puma occupancy tracks prey *vulnerability* more than abundance ([Wildlife Biology 2020](https://bioone.org/journals/Wildlife-Biology/volume-2020/issue-1/wlb.00540/Predictors-of-puma-occupancy-indicate-prey-vulnerability-is-more-important/10.2981/wlb.00540.short)) | Moderate to strong | Occupancy covariates |
| Home range / territory scale | **Structural.** About 134–372 km² in SMM | Hundreds of km² *(lit.)* | Sets the minimum meaningful output scale |
| Fire | Woolsey Fire changed lion movement ([Blakey 2022](https://blumsteinlab.eeb.ucla.edu/wp-content/uploads/sites/104/2022/10/Blakey_etal_2022_CB.pdf)) | — | Disturbance covariate |

## 6. Ethics, safety and policy

- **Risks.**
  - Persecution and poaching: the illegally shot collared wolf OR-59 in CA ([CBD](https://biologicaldiversity.org/w/news/press-releases/reward-increased-7500-info-killing-endangered-california-wolf-2020-01-09/)); legal and illegal killing of Yellowstone wolves at the boundary; "Do not publish" ([Lindenmayer & Scheele 2017](https://science.anu.edu.au/news-events/news/scientists-urged-keep-rare-species-habitat-secret)).
  - Harassment and crowding (Porto Jofre).
  - Habituation and food conditioning, leading to lethal removal.
  - Fear-driven removals of lions (depredation and public-safety take).
  - Disturbance of dens and kittens.
  - In CA lion country, attacks are extremely rare. The product's safety role is awareness: dawn/dusk, keep pets and livestock secured, supervise children, behave correctly if an encounter happens.
- **Awareness vs. finding.** Every agency product reviewed is built for awareness, not finding: CDFW territory maps and the tracker, ODFW AKWA, WDFW polygons, CPW's monthly watershed map with sensitive-period buffering, Yellowstone withholding locations under FOIA, and NPS lion stories told after the fact.
- **Recommended policy: a species × region × season sensitivity registry with tiers.**
  - **T3 suppress.** Dens, rendezvous sites, kittens, named or collared individuals, dispersers (e.g., BEY03F), anything derived from collars, the Wolf Tracker feed, and any re-identification of obscured records (iNat warns obscured points can be inferred from nearby observations).
  - **T2 awareness-only.** SC/CC mountain lions; wolves in CA. Output "you are in occupied lion/wolf range" at territory scale or coarser (at least about the 0.2° cell or a watershed). Show seasonal and diel risk context and conduct guidance. No "where/when to see," no point maps, no freshness better than about 30 days, and suppress small counts.
  - **T1 managed viewing.** Yellowstone in-park; Culebra, Torres del Paine and Pantanal through licensed guides. Provide general areas the agencies already publish, season and time-of-day guidance, and etiquette (keep about 100 yd from wolves: **UNVERIFIED** on the NPS site). No real-time pack positions, and nothing near boundary hunting units during the season.
  - Policy is regional. The same species can be T1 inside Yellowstone and T2/T3 in CA, and Spanish tiers may change with hunting law.
- **Upstream data obligations.** Honour NC licenses and upstream obscuring. Never claim absence or say "safe" (false negatives are dangerous). Add abuse detection: repeated fine-grained queries on a sensitive taxon, rate limits, no export of sensitive layers.

## 7. Synthesis: estimands and framework features

**What can realistically be predicted.**
- Occupancy at range or territory scale (seasonal).
- Probability of finding sign on a given route and date.
- Camera detection rate per 100 trap-nights at a given site type.
- A relative awareness or conflict index.
- P(sighting) only in managed viewing systems, calibrated against watcher or operator logs.

**Estimands.**
1. ψ(cell, season): occupancy, with cells sized near a home-range fraction (e.g., H3 res 5–6 for pumas).
2. λ_sign(route, day): expected sign detections per km, conditional on ψ, substrate, days since snow or rain, and trail type.
3. λ_cam(site, period): expected camera detections.
4. P(≥1 sighting | n days, guided): only for T1 sites.
5. An awareness index: relative and never absolute.

**Framework features.**
- **Multi-scale latent state:** range (years) → territory occupancy (season) → use intensity (weeks: prey, fire, recreation) → availability (diel, weather) → method-specific detection. Individual-level states stay internal.
- **False-positive-aware multi-method occupancy:** Royle-Link and Miller-style models *(lit.)*, with a misidentification matrix (bobcat, cat, coyote, dog → puma; dog, coyote, hybrid → wolf).
- **Evidence grading** on the SCALP C1/C2/C3 scheme *(lit.)*: C1 hard evidence (DNA, carcass, verified georeferenced photo); C2 expert-verified sign; C3 unverified reports.
- **Bias handling:** de-duplicate reports of the same individual; model media-driven reporting spikes; account for preferential sampling (roads, trails, backyard cameras) and serial correlation in snow surveys.
- **Agency maps as priors:** ingest coarse agency layers (ODFW AKWA, WDFW polygons, CPW watersheds) as priors or C1-equivalent evidence at territory resolution.
- **Sensitivity policy engine** with spatial coarsening, delay, small-count suppression, provenance and license tracking, and an awareness-mode UI. Partner-only tiers for researchers.

## Open questions and risks
- Whether the CESA findings were formally adopted, the outcome of SB 1397, the current NPS collared count, and CDFW's July 2026 pack total: all UNVERIFIED (wildlife.ca.gov and nps.gov could not be fetched).
- The federal wolf status could change through a Ninth Circuit ruling or Interior rulemaking. CA status would not change with it.
- iNaturalist's CA geoprivacy for *Puma* and *Canis lupus*, and whether Wildlife Insights applies any regional fuzzing: UNVERIFIED. Need checks via API or support.
- The terms of use for CDFW's tracker and CROS bulk data, and their suitability for commercial use, are unknown.
- No CA-specific, in-range misidentification rate exists. We would need an expert-verification pipeline to estimate one.
- Ground truth for validating sighting probability is essentially absent outside T1 sites. Presence-only data are heavily biased.
- Reputational and legal exposure: a lion attack or a poaching event linked to our outputs. Hunters in states where puma or wolf harvest is legal could use the outputs for targeting, which needs an explicit policy decision.
- How effective the Wallis Annenberg crossing will be is unknown for years. Model the 101 barrier as time-varying.
