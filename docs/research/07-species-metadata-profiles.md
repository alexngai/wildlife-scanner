# wildlife-radar: building species profiles automatically (metadata, traits, ranges, status, taxonomy)

Checked on 2026-11-11, mostly through WebSearch. Direct fetches were blocked for wikidata.org, iucnredlist.org, data-blog.gbif.org, esapubs.org, cran.r-project.org and arxiv.org. To check those primary pages directly, those hosts need to be allowed in the session's network settings. Only github.com could be fetched. Several license claims therefore rest on search snippets of the primary pages and are marked as such. **UNVERIFIED** means I could not see the primary terms. "(memory)" means it comes from prior knowledge and was not re-checked.

## 0. Summary table

✅ = commercial use OK (CC0, public domain or CC BY). ⚠ = conditional or unclear. ❌ = non-commercial only, or needs permission or a paid license.

| Source | Fields | Coverage | Access | License / commercial | Relevance |
|---|---|---|---|---|---|
| **Wikidata** | ID crosswalk, names, rank/parent, P141 status, images, range-map image | Millions of taxon items (exact total UNVERIFIED) | SPARQL (WDQS), REST v1, weekly JSON dumps | CC0 ✅ | Crosswalk hub |
| **Catalogue of Life XR / ChecklistBank** | Accepted names, synonyms, classification | 2.48M spp (XR, May 2026) | ChecklistBank API (no key), monthly releases | CC BY 4.0 ✅ ([COL](https://www.catalogueoflife.org/data/download)) | Canonical backbone |
| GBIF legacy Backbone | Names, numeric taxonKeys | Global | GBIF species API | CC BY 4.0 ✅ ([forum](https://discourse.gbif.org/t/linking-to-the-gbif-backbone-taxonomy-under-an-incompatible-license/4084)) | Legacy key mapping |
| ITIS | TSNs, NA-centric names | Global, US focus | JSON/SOAP/Solr ([itis.gov](https://itis.gov/web_service.html)) | US federal; public domain UNVERIFIED ✅ | Matches US agency data |
| iNaturalist taxonomy + statuses | Taxa, names, place-scoped conservation statuses with geoprivacy | Global | API (~1 req/s), monthly DwC-A | Taxonomy license UNVERIFIED; terms of use ban commercial AI training ⚠ | Crosswalk, sensitivity |
| eBird/Clements v2025; AviList v2025 | Bird taxonomy, species codes | ~11.1k bird spp | CSV/XLSX downloads | AviList CC BY 4.0 ✅; Clements download license UNVERIFIED; eBird API non-commercial ❌ | Birds |
| Avibase | Taxon-concept IDs | Birds | Web only; no documented public API | UNVERIFIED ⚠ | Mapping splits and lumps |
| WoRMS | Marine taxonomy, environment flags, attributes | Marine | REST | Text CC BY ✅; images CC BY-NC-SA ([record](https://metadatacatalogue.lifewatch.eu/srv/api/records/3b402aca-5241-47e8-a96b-02eeeb97fec5)) | Marine backbone |
| EltonTraits 1.0 | Diet %, foraging stratum, activity, body mass | 15,393 birds + mammals | figshare / ESA archive | UNVERIFIED ⚠ | Activity, diet |
| **AVONET** | Morphology; habitat, habitat density, migration, trophic level/niche, primary lifestyle (variable names from memory); range size | 11,009 birds | figshare | CC BY 4.0 ✅ | Core bird traits |
| **TetrapodTraits 1.0** (v2.0 Sep 2025) | Body size, activity (Diu/Noc + nocturnality score), micro/macrohabitat, imputation flags | 33,281 tetrapods | Zenodo | v1 CC BY 4.0 ✅ ([Zenodo](https://zenodo.org/records/11303604)); v2 UNVERIFIED | Best single activity source |
| PanTHERIA | Activity cycle, home range, habitat and diet breadth, trophic level, mass | ~5.4k mammals (memory) | ESA archive | CC0 ✅ ([docs](https://ecologicaltraitdata.github.io/traitdataform/reference/pantheria.html)) | Mammals |
| COMBINE | 54 traits: activity cycle, home range, habitat breadth, dispersal, phenology | 6,234 mammals | figshare | "No copyright or proprietary restrictions; cite" ✅ ([PubMed](https://www.pubmed.gov/33742448/)) | Mammals |
| Amniote life-history DB | Mass, longevity, clutch size, etc. | 9,802 birds / 4,953 mammals / 6,567 reptiles | ESA archive | CC0 per R docs; primary page UNVERIFIED ✅ | Life history |
| AmphiBIO | Habitat, diet, diel/seasonal activity, size, breeding (field list from memory) | Amphibians | figshare | CC BY ✅ ([Sci Data](https://www.nature.com/articles/sdata2017123)) | Amphibians |
| ReptTraits | 40 traits: habitat, behaviour, etc. | 12,060 reptiles | figshare | UNVERIFIED ⚠ | Reptiles |
| AnimalTraits | Body mass, metabolic rate, brain size | ~2,000 spp | Website, Zenodo | UNVERIFIED (authors: "without restrictions") ⚠ | Minor |
| LepTraits 1.0 | Phenology, voltinism, hostplants, habitat | Butterflies | GitHub (no LICENSE file) | UNVERIFIED ⚠ | Butterfly seasonal timing |
| FishBase / SeaLifeBase | Depth range, temperature, habitat, spawning, diet, length | ~35k fishes plus non-fish (memory) | rfishbase 5 (parquet on Source Cooperative) | CC BY-NC (3.0 vs 4.0 conflicting) ❌ | Marine core, needs a license |
| AquaMaps | Modelled native ranges, environmental envelopes | 33,500 spp | aquamapsdata (~2 GB) | CC BY-NC 3.0 ❌ ([terms](https://www.aquamaps.org/main/TermsConditions.php)) | Marine ranges |
| EOL TraitBank | Aggregated traits | Broad | API | License set per record (CC BY / BY-SA / BY-NC) ⚠ | Gap filler, after filtering |
| TRY | Plant traits | Plants | Registration and request | Public data CC BY ✅ (2019 announcement) | Plants |
| BIEN | Plant ranges and traits | Plants of the Americas | R package | CC BY-NC-ND ❌ ([policy](https://bien.nceas.ucsb.edu/bien/biendata/data-use-policy/)) | Avoid |
| IUCN Red List API v4 + spatial | Category, criteria, trend, habitats, threats; range polygons | ~all assessed spp | Token API | Non-commercial; commercial via IBAT ❌ | Status, habitat |
| BirdLife range maps | Bird ranges | Birds | Request form | Non-commercial; commercial via IBAT ❌ ([terms](https://datazone.birdlife.org/info/dataterms)) | Bird ranges |
| Map of Life | Expert ranges | Global vertebrates+ | Web | CC BY-NC 4.0 ❌ ([ToS](https://mapoflife.ai/policies/tos-mol)) | — |
| eBird Status & Trends | Weekly abundance and ranges | Birds | ebirdst | Commercial needs written permission ❌ ([terms](https://ebird.org/about/products-access-terms-of-use)) | — |
| **iNat Open Range Maps** | Geomodel range polygons, monthly | iNat taxa | BigQuery / Earth Engine | **CC BY 4.0 ✅** ([catalog](https://developers.google.com/earth-engine/datasets/catalog/iNaturalist_MULTI_SPECIES_LATEST)) | Commercial-usable range prior |
| USFWS ECOS | ESA status, ranges, critical habitat | US | Data Explorer REST, ArcGIS ([ECOS](https://ecos.fws.gov/ecp/services)) | US federal; public domain presumed ✅ | Status |
| NatureServe Explorer | G/S ranks | Americas | [API](https://explorer.natureserve.org/api-docs) | Conflicting: current page says CC BY, older pages say no commercial redistribution ⚠ | Status |
| CDFW Special Animals List / CNDDB | California status; element occurrences | California | Quarterly PDFs; CNDDB subscription ($600 first year, then $400/yr) | Lists are public (no license stated); CNDDB under license, commercial edition suppresses ~1% of data ⚠ | Southern California sensitivity |
| CITES Species+ | Appendix listings | Global | Token API | Commercial use needs UNEP written permission ⚠ ([terms](https://speciesplus.net/terms-of-use)) | Sensitivity |
| eBird sensitive species list | Hidden taxa | 325 taxa per Audubon (date not checked) | Web | Use as a policy input ⚠ | Sensitivity |
| Wikipedia | Taxobox fields, prose (description, habitat, behaviour, diet, breeding) | ~1.27M taxonomic articles in 11 languages → ~752k GBIF taxa | Dumps, REST, Wikimedia Enterprise | Text CC BY-SA 4.0 ⚠ | LLM extraction; display text |
| BHL | Historic literature, OCR | Large | API v3 (key) | Metadata CC0; public-domain scans OK commercially; in-copyright items CC BY-NC-SA ⚠ | Literature |
| OpenAlex | Literature metadata, open-access links | ~All scholarly works | API key required since Feb 2026 | CC0 ✅ | Finding papers |
| Semantic Scholar / S2ORC | Literature, full text | Large | API | Non-commercial; S2ORC CC BY-NC ❌ ([license](https://api.semanticscholar.org/license)) | — |
| Plazi TreatmentBank | Taxonomic treatments | Growing | HTTP API; also harvested by GBIF | Site CC0; treatments "no known copyright restrictions" ⚠ | Literature extraction |

## 1. Taxonomy backbones and ID crosswalks

**Wikidata as the hub.** Taxon ID properties confirmed in search results:

| Source | Property |
|---|---|
| iNaturalist | P3151 |
| GBIF | P846 |
| eBird | P3444 |
| IUCN | P627 |
| ITIS | P815 |
| NCBI | P685 |
| WoRMS | P850 |
| FishBase | P938 |
| Avibase | P2026 |

Sources: [Taxonbar](https://en.wikipedia.org/wiki/Template:Taxonbar), [P685](https://www.wikidata.org/wiki/Property:P685).

Other properties, UNVERIFIED or from memory: P225 (taxon name), P105 (rank), P171 (parent), P141 (IUCN status), P1843 (vernacular name), P181 (range map image), P10585 (COL ID), P5257 (BirdLife), P9566 (diel cycle). Don't hard-code the list. Pull the authoritative set from Wikipedia's `Module:Taxonbar/conf`.

**Wikidata access:**
- **SPARQL limits.** Per user-agent + IP: 60 s of processing per 60 s, a 60 s query timeout, about 5 parallel queries, and about 30 erroring queries per minute. These come from older docs ([R client manual](https://search.r-project.org/CRAN/packages/WikidataQueryServiceR/WikidataQueryServiceR.pdf)).
- **Graph split.** Since 9 May 2025, scholarly articles have moved to `query-scholarly.wikidata.org`. Taxon queries stay on the main graph ([FAQ](https://meta.wikimedia.org/wiki/WikiCite/WDQS_graph_split)).
- **REST API.** v1 has been complete since mid/late 2024 ([REST API](https://www.wikidata.org/wiki/Wikidata:REST_API_feedback_round)).
- **Global API rate limits.** Wikimedia rolled these out in 2026: low limits for anonymous traffic from March, and identified bots also limited from April ([announcement](https://www.mail-archive.com/wikitech-l@lists.wikimedia.org/msg97263.html), [changelog](https://www.mediawiki.org/wiki/Wikimedia_APIs/Changelog)).
- **Recommendation.** Build from the weekly JSON dumps into a local store, and send a descriptive User-Agent.
- **Crosswalk errors.** Wikidata crosswalks contain stale or wrong IDs. Check each ID both ways against the source API (name and rank must match).

**Backbones:**
- **GBIF → COL XR.** GBIF.org switched its default taxonomy to Catalogue of Life eXtended Release on about 23 June 2026. The legacy backbone build is discontinued ([techdocs](https://techdocs.gbif.org/en/data-processing/taxonomy-interpretation)). The occurrence API still defaults to the legacy backbone unless you pass `checklistKey`. COL XR keys are alphanumeric, and rgbif 3.9.0 switched its default ([migration guide](https://docs.ropensci.org/rgbif/articles/col_migration_guide.html)).
- **COL releases.** COL publishes monthly. Annual releases are kept permanently; monthly releases are kept for one year ([COL usage](https://catalogueoflife.org/about/colusage)). Pin profiles to an annual release and track monthly diffs.
- **ITIS** is useful because US agency data (ECOS) aligns to TSNs.
- **iNaturalist** taxonomy is curated by its community. Its DwC-A export has no synonyms ([forum](https://forum.inaturalist.org/t/download-taxonomy-with-synonyms/38699)).
- **Birds:**
  - eBird/Clements v2025 (31 Oct 2025): +40 species from splits, −18 from lumps, 11,167 species ([eBird](https://science.ebird.org/en/use-ebird-data/the-ebird-taxonomy/2025-ebird-taxonomy-update)).
  - AviList v2025 (11 June 2025): 11,131 species, CC BY 4.0 ([AviList](https://www.avilist.org/?p=374)).
  - eBird expected full alignment with AviList by October 2026. Whether the 2026 update shipped is UNVERIFIED (a forum post says it did).
  - Avibase concept IDs are adopted by the AOS checklist ([Avibase](https://en.wikipedia.org/wiki/Avibase)).
- **Marine:** use WoRMS AphiaIDs (OBIS is keyed to WoRMS).

**Reconciling synonyms and splits/lumps over time:**
1. Model **taxon concepts**, not names: name → usage in a specific checklist version → concept. Record concept relationships (equal, includes, included-in, overlaps), following Avibase's approach.
2. Ingest change events: eBird's annual change tables, iNat taxon changes (swap/split/merge), COL release diffs, WoRMS status changes.
3. Handle each change type:
   - **Swap (rename only):** move the pointer.
   - **Lump:** union of ranges; recompute traits.
   - **Split:** each child inherits the parent's profile, marked "inherited, needs review". Reassign historical occurrences to children by range. Children inherit the parent's sensitivity tier or higher (splits often create narrow-range endemics).
4. Use Global Names Verifier for fuzzy name matching ([data sources](https://verifier.globalnames.org/api/v1/data_sources)).
5. Stamp every profile field with the taxonomy version it was asserted under.

## 2. Trait databases

Which trait fields each source covers. FB = FishBase, SLB = SeaLifeBase.

| Field | Sources |
|---|---|
| **Activity pattern** | TetrapodTraits (Diu/Noc + nocturnality; imputed values flagged); EltonTraits (mammals: nocturnal/crepuscular/diurnal flags; birds: nocturnal flag; memory); PanTHERIA ActivityCycle (1 nocturnal, 2 mixed/crepuscular, 3 diurnal; memory); COMBINE activity cycle; AmphiBIO (memory). Fish and invertebrates: mostly missing, so use LLM extraction. |
| **Home range** | PanTHERIA, COMBINE (mammals only); others via literature extraction |
| **Migration** | AVONET (1 sedentary / 2 partial / 3 migratory; memory); FB diadromy (NC); otherwise derive from occurrence seasonality |
| **Habitat** | AVONET, TetrapodTraits, AmphiBIO, ReptTraits, COMBINE habitat breadth, WoRMS environment flags, IUCN habitats (NC), FB/SLB (NC) |
| **Diet / trophic** | EltonTraits, AVONET, COMBINE, FB (NC) |
| **Seasonality** | LepTraits phenology/voltinism, COMBINE phenology, AmphiBIO (memory), FB spawning (NC). Best to compute in-house from occurrence phenology. |
| **Depth / temperature** | FB/SLB depth ranges and temperature preferences, AquaMaps envelopes. Both are NC. The commercial-safe alternative is computing envelopes yourself from OBIS records + environmental layers. |

License notes:
- **FishBase.** The API docs say "CC BY-NC 3.0; commercial users contact maintainers" ([docs](https://fishbaseapi.readme.io/docs/license)). The citation page says CC BY-NC 4.0 ([FishBase](https://fishbase.ca/summary/citation.php)). The rfishbase package code is CC0, but the data is not.
- **EOL TraitBank** licenses are set per record ([EOL](https://media.eol.org/info/eol_licensing_policy)).
- **TRY** public data is CC BY ([MPI](https://www.bgc-jena.mpg.de/5451834/1554881196)).
- **Open Traits Network:** I found no 2025 status update. Use the traits.build / Ecological Trait-data Standard (ETS) / Darwin Core MeasurementOrFact data model ([traits.build](https://traitecoevo.github.io/traits.build-book/database_standard.html)).

## 3. Range maps

- **Commercial-safe:**
  - iNat Open Range Maps: CC BY 4.0, monthly. The catalog's availability window shows 2025, so currency is UNVERIFIED.
  - USFWS ECOS species ranges (ArcGIS REST).
  - Your own ranges computed from CC0/CC BY occurrences (drop CC BY-NC records), for example H3 occupancy or alpha hulls plus the other team's SDMs.
- **Non-commercial or permission needed:**
  - IUCN spatial data: non-commercial; commercial via IBAT ([mapme docs](https://rdrr.io/cran/mapme.biodiversity/man/iucn.html)).
  - BirdLife: commercial via IBAT.
  - Map of Life: CC BY-NC.
  - AquaMaps: CC BY-NC.
  - eBird Status & Trends: written permission required.
- IBAT pricing for commercial use is UNVERIFIED and needs a quote.

## 4. Conservation status and sensitivity

**Sources and terms:**
- **IUCN API v4.** Base `apiv4.iucnredlist.org/api/v4` (third-party code). v3 is dropped in rredlist 1.0.0 ([NEWS](https://docs.ropensci.org/rredlist/news/index.html)). "Use for commercial purposes is strictly forbidden… consider IBAT" ([IUCN R pkg](https://cran.r-project.org/web/packages/redlist/readme/README.html)).
- **NatureServe:** conflicting terms ([current, CC BY](https://natureserve.org/terms/data) vs [older guidelines](https://natureserve.org/nsexplorer/about-the-data/use-guidelines-citation)).
- **USFWS ECOS:** federal data.
- **CDFW:**
  - The Special Animals List is updated quarterly; the July 2025 edition exists and a 1/2026 edition is indexed ([CDFW](https://wildlife.ca.gov/Data/CNDDB/News/rarethreatenedendangered-species-and-special-plants-and-animals-lists-quarterly-update-july-2025)).
  - CNDDB requires a subscription and license. The commercial edition suppresses ~1% of records, and suppressed records are released per project on request ([FAQ](https://wildlife.ca.gov/Data/CNDDB/FAQ), [subscribe](https://www.Wildlife.ca.gov/Data/CNDDB/Subscribe)).
  - The Data Use Guidelines PDF, which holds the display and suppression rules, is UNVERIFIED.
- **CITES Species+:** commercial use is broadly defined and needs written permission. Access can be cut off without notice ([terms](https://speciesplus.net/terms-of-use)).
- **iNaturalist:** conservation statuses are scoped to a place and can carry `obscured` or `private` geoprivacy, which then applies automatically ([help](https://help.inaturalist.org/en/support/solutions/articles/151000233080)). Per forum reports, the API returns this but can't filter taxa on it.
- **eBird sensitive species:** hidden from checklists and site-level outputs; maps aggregate them at 20×20 and 100×100 km ([All About Birds](https://www.allaboutbirds.org/sensitive-species-in-ebird/)).
- **GBIF best-practice guide on generalizing sensitive data** (Chapman 2020; CC BY-SA) ([GBIF](https://docs.gbif.org/sensitive-species-best-practices/master/en/)).

**Proposed sensitivity tiers.** The tier is the maximum over all triggers, scoped to place.

| Tier | Output rule | Triggers |
|---|---|---|
| S0 Open | Full resolution | No triggers, taxon resolved, and all lookups fresh |
| S1 Generalize | ≥1–5 km cells; no "seen N hours ago here" | IUCN NT/VU without disturbance threats; NatureServe G3/S3; CDFW Species of Special Concern |
| S2 Coarse | ≥20–100 km cells; month-level timing; no real-time | iNat geoprivacy = obscured; eBird sensitive list; ESA or CESA Threatened/Endangered; IUCN EN/CR; CITES Appendix II; G1–G2 or S1–S2; CNDDB sensitive flag. **Also the default when anything is unknown or stale.** |
| S3 Withhold | Region-level presence only; vetted partners only | iNat geoprivacy = private; CITES Appendix I; status ≥ VU and IUCN threats include hunting/collecting or persecution; known poaching targets (e.g., *Dudleya*, an example from memory); nest/roost/den/hibernaculum or lek/spawning-aggregation context |

**Fail-closed rules:**
1. Missing data, unresolved taxonomy, a failed source call, or data past its freshness window means S2, not S0.
2. Upgrades happen automatically and immediately. Downgrades need two people, a written rationale and an expiry date.
3. At species level, use the highest tier of any subspecies or distinct population segment present in the place. For example, coastal California gnatcatcher is ESA-listed at subspecies level (memory).
4. Seasonal context can raise the tier (breeding windows).
5. Enforce tiers in the serving/API layer, including model hotspots and "best time" hints. Use fixed grids to block differencing attacks.
6. Never let an LLM set or lower status or tier.
7. Log the inputs behind every tier decision.

## 5. Wikipedia

**What can be extracted per species:**
- Speciesbox/Taxobox fields: `status`, `status_system`, `status_ref`, `range_map`, authority, image ([parameters](https://en.wikipedia.org/wiki/Wikipedia:Automated_taxobox_system/all_parameters)).
- Taxonbar IDs (these come from Wikidata).
- Prose sections: Description, Distribution and habitat, Behaviour/Ecology, Diet, Reproduction.
- Categories.

**Access:**
- Dumps.
- REST/Action APIs, subject to the 2026 rate limits.
- Wikimedia Enterprise. The free tier now includes Structured Contents snapshots (infoboxes, sections, abstracts, QIDs) ([blog](https://enterprise.wikimedia.com/blog/structured-contents-snapshot-api/)). Free-tier quotas conflict between pages (e.g., 30 snapshot requests per month vs "10,000 requests") ([API](https://enterprise.wikimedia.com/api/)). Paid tiers are custom-priced; one page says from ~$100k/yr (UNVERIFIED).

**License:** CC BY-SA 4.0 since June 2023; older revisions are 3.0 ([CC](https://creativecommons.org/2023/06/29/wikipedia-moves-to-cc-4-0-licenses/)).
- **(a) Extracting facts into structured fields.** Bare facts aren't copyrightable in the US (*Feist*). EU/UK database rights restrict systematic extraction ([Wikilegal](https://meta.wikimedia.org/wiki/Wikilegal/Database_Rights)). Store facts plus a revision-ID citation, never the sentences.
- **(b) Displaying text.** Attribution (a link) and a license notice are required, and share-alike applies to the excerpt and adaptations. Treat close LLM paraphrases as adaptations. Keep displayed text in a separately licensed component. Images carry their own per-file licenses.

**Coverage:**
- BioWikiNet: 1.27M taxonomic articles in 11 languages map to ~752k GBIF taxa (Jan 2025 dumps) ([BioWikiNet](https://tagteam.harvard.edu/hub_feeds/4358/feed_items/17187441)).
- The long tail of invertebrates and plants is thin. Swedish and Cebuano bot-made stubs hold little beyond taxonomy (memory).
- LLMs hallucinate more about entities without a Wikipedia page ([WildHallucinations](https://arxiv.org/pdf/2407.17468)).

## 6. LLM-based extraction

**Reported results:**
- **Gougherty & Clipp 2024** (npj Biodiversity): >90% accuracy on categorical data, poor on some quantitative fields, 50× faster than a human reviewer ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11332232)).
- **Castro et al. 2024** (Ecol. Informatics): GPT-4 often >90% correct on species-distribution extraction; LLaMA-2-70B far worse. This comes from a search summary; I did not see the paper.
- **Marcos et al. 2025** (Appl. Plant Sci.): web text → categorical traits. Values for >50% of species–trait pairs, F1 >75%. A "Not Available" option was allowed, and precision exceeded recall ([arXiv](https://arxiv.org/html/2409.17179v2)).
- **Plant-trait NLP pipeline 2025:** precision 90.8% / recall 88.6% on categorical traits; normalized mean absolute error 10.3% on numeric traits ([PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12188621/)).
- **Dorm et al. 2026** (Ecol. Informatics): GPT-4o and Gemini 1.5 Pro tested on AVONET/COMBINE traits. Threat classification was only about 10 percentage points above random ([bioRxiv](https://www.biorxiv.org/content/10.1101/2025.02.10.637097v2.full)). **Do not use zero-shot LLMs for status.**
- **trAIt 2026 preprint:** recovered 47.1% of frog trait–species pairs versus 62.4% for an expert; only 70.9% of recovered entries were confirmed accurate ([Sciety](https://sciety.org/articles/activity/10.64898/2026.06.19.732660)).
- **ARETE** (occurrence extraction): baseline precision 0.917 / recall 0.764; fine-tuned F1 0.958 ([arXiv](https://arxiv.org/pdf/2511.04573v1)).
- **Microbial phenotypes:** self-reported confidence was informative; models hallucinated on fake species names ([bioRxiv](https://www.biorxiv.org/content/10.1101/2025.11.24.690272v1.full.pdf)).
- **Cost reference:** GPT-4o over 83,910 articles cost about $582 in batch mode ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC13713224)).

**Failure modes:**
- Hallucination where literature is sparse.
- Mixing up congeners or synonyms.
- Values that apply to a population or region being stated as global.
- Unit and range errors.
- Defaulting to what is "typical for the group".
- Status stated in text being out of date.

**Best practices:**
1. Extract only from retrieved text, never from the model's own knowledge.
2. Use schema-constrained output with controlled vocabularies and a "not stated" option.
3. Require a verbatim evidence span plus source revision ID per field. Machine-check that the span exists and names the taxon or a synonym.
4. Build confidence from: agreement between two models or prompts, agreement with trait databases, source quality, and self-reported confidence.
5. Measure accuracy per field on the overlap with trait databases, then calibrate acceptance thresholds.
6. Bound numeric values by the observed range in the genus or family.
7. Send items to human review ranked by uncertainty × impact.
8. Log the model and prompt hash, and re-run when the source revision changes.

**Literature APIs:**
- **BHL:** API v3 with a key. Metadata CC0; public-domain scans reusable commercially; in-copyright items CC BY-NC-SA ([BHL](https://about.biodiversitylibrary.org/?p=2894)).
- **OpenAlex:** CC0. Keys required since Feb 2026; free usage is about $1/day with a key ([docs](https://developers.openalex.org/api-reference/authentication)).
- **Semantic Scholar:** non-commercial; S2ORC is CC BY-NC ([GitHub](https://github.com/allenai/s2orc)).
- **Plazi:** site CC0 ([disclaimer](https://plazi.org/disclaimer)); open HTTP API ([API](https://plazi.org/data-apis-tools/treatmentbank-api/)).
- Text-and-data-mining exceptions (US fair use, EU DSM Directive Art. 4) are a legal question to confirm.

## 7. Recommended pipeline

**Steps:**
1. **Resolve the name.** Match with GN Verifier and COL XR, map to an internal concept ID, harvest the Wikidata crosswalk, and verify each ID.
2. **Status and sensitivity first.** Pull ECOS, CDFW, NatureServe, CITES, iNat statuses and the eBird list, then compute the tier with fail-closed rules before anything is published.
3. **Route to curated trait databases by group:**
   - Birds → AVONET, TetrapodTraits, EltonTraits
   - Mammals → COMBINE, PanTHERIA, TetrapodTraits
   - Herps → TetrapodTraits, AmphiBIO, ReptTraits
   - Marine → WoRMS (+ FishBase/SeaLifeBase only if licensed)
   - Butterflies → LepTraits
   - Plants → TRY
4. **Compute priors from occurrence data:** phenology, time of day (flag observer bias), ranges, and marine depth/temperature envelopes.
5. **Fill gaps with LLM extraction** from Wikipedia, then Plazi/BHL/open-access papers, with evidence spans.
6. **Taxonomic imputation** (genus mode), flagged.
7. **Score confidence and route to review.**
8. **Publish a versioned draft.**

**Source precedence (highest first):**
1. Human-verified override
2. Authoritative source for that scope (ECOS for ESA, CDFW for California, eBird/AviList for bird names)
3. Measured values in curated databases
4. Imputed values in curated databases
5. Wikidata statements with references
6. LLM extraction with evidence
7. Taxonomic imputation
8. LLM knowledge without a source, used only as a hint for reviewers

**Conflict rules:**
- Local scope beats global for local display.
- Newer assessment beats older.
- When categorical sources disagree, keep all values and flag the field.
- For numeric fields, keep per-source values, use the median, and flag if they differ by more than 2×.

**Per-field provenance record:** value, vocabulary/unit, source + version, retrieval date, license, method (import / extracted / imputed / computed / human), evidence URL + span, confidence, taxonomy version, review state.

**Community layer:**
- Changes are proposed as diffs with a required citation; reputation-weighted review.
- Field-level locks; sensitivity fields only editable by privileged reviewers.
- Contributor agreement with CC0 (or CC BY) output, so commercial use stays possible.
- Reject text pasted from NC or BY-SA sources.
- Upstream re-syncs never overwrite verified fields; they raise conflicts instead.
- Contribute non-sensitive facts back to Wikidata.

**License "taint tracking":** every value carries its source license. A commercial build excludes values derived from ❌ sources, including LLM extractions that read those sources.

**Licensing summary:**
- **Green (commercial OK):** Wikidata, COL, GBIF backbone, ITIS*, ECOS, AviList, AVONET, TetrapodTraits v1, AmphiBIO, PanTHERIA, Amniote*, COMBINE, TRY public data, WoRMS text, iNat Open Range Maps, OpenAlex, BHL metadata and public-domain scans, Plazi*. (* = primary page not seen.)
- **Yellow (conditional or unclear):** Wikipedia text (facts OK; displayed text is share-alike), NatureServe, CDFW/CNDDB, CITES, iNaturalist taxonomy and terms, EOL, EltonTraits, AnimalTraits, LepTraits, ReptTraits, TetrapodTraits v2, Clements download.
- **Red (non-commercial or permission/paid):** IUCN (API and spatial), BirdLife, FishBase/SeaLifeBase, AquaMaps, Map of Life, BIEN, eBird API and Status & Trends, Semantic Scholar/S2ORC, in-copyright BHL items.

## Open questions / risks

1. **IUCN categories via Wikidata.** P141 is CC0 but derived from IUCN. Whether a commercial product can use it at scale needs legal review or an IBAT license.
2. **EU database rights** on systematic extraction from Wikipedia/Wikidata matter for global expansion.
3. **iNaturalist terms of use** ban commercial AI training, and whether that reaches GBIF/AWS copies is disputed ([forum](https://forum.inaturalist.org/t/can-i-use-inaturalist-aws-open-data-to-train-commercial-ai-model/77663)). This affects the prediction models; clarify with iNat in writing.
4. **Marine traits.** With FishBase/SeaLifeBase non-commercial, marine fields need a FishBase commercial license or envelopes computed in-house.
5. **Taxonomy churn.** The GBIF API default is still the legacy backbone; COL IDs are alphanumeric; the eBird–AviList 2026 alignment is UNVERIFIED.
6. **Coverage.** LLM extraction is weakest for invertebrates and plants and wherever literature is sparse (trAIt: only ~71% of recovered entries were accurate).
7. **Sensitive-data rules.** CNDDB display and suppression rules need CDFW consultation.
8. **Licenses to confirm on primary pages before launch:** EltonTraits, ReptTraits, LepTraits, AnimalTraits, ITIS, Clements, NatureServe, IUCN, iNat taxonomy.
9. **Wikimedia rate limits.** The 2026 limits mean production should use dumps or Wikimedia Enterprise, not live scraping.
