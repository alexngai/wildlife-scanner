# wildlife-radar — framework design (draft v0.1)

Status: **draft for discussion**. Builds on [`../research/00-synthesis.md`](../research/00-synthesis.md).

## 0. Goals and decisions so far

**Goal.** A species-agnostic informatics framework that combines many signals into predictions of *where and when* a species can be encountered. It must handle species ranging from abundant ones to elusive white seabass to rare, hard-to-spot carnivores like mountain lions and wolves. Data sources and methods may be species-specific; the framework is not.

| Decision | Choice |
|---|---|
| Species coverage | **Any species.** Every species with data gets an automatic baseline. Featured species get deeper treatment. |
| Species profiles | **Generated automatically** from collected metadata (Wikidata, trait databases, Wikipedia and literature via LLM extraction), then refined by **community contributions** and review. |
| Query modes | **Both, first-class.** Species-first ("where/when can I find X?") and place-first ("what's likely, and what's *special*, near here?"). |
| Geography | Start in **Southern California**; design for **global**. |
| Stack | **Python** backend and data/ML; **TypeScript** web frontend later; API-first. |
| Licensing posture | **Exclusively non-commercial**: a free, educational service run by the founder as an individual; code under **AGPL-3.0**. See [`licensing.md`](licensing.md). |

**Non-goals for v1:** real-time tracking of individual animals; navigation or safety advice ("safe to dive/hike"); harvest or hunting tools.

**Design-validation species.** The core design must handle these five archetypes without special cases:

| Archetype | Species | What it stresses |
|---|---|---|
| Sparse, dynamic, fishery-labeled | White seabass | Few direct sightings; labels come from catch data; prey and temperature drivers; spawning sensitivity |
| Dense, strongly seasonal | Leopard shark (La Jolla) | Rich presence-only data; temperature-driven aggregation |
| Effort-rich, condition-driven | A shorebird or migrant songbird | eBird checklists that record misses; tide or weather-radar drivers |
| Rare, cryptic, territorial | Mountain lion | Evidence is mostly indirect (sign, cameras); tiny encounter probabilities; heavy sensitivity |
| Rare, policy depends on region | Gray wolf | Persecution risk in some regions; established managed viewing in others (e.g., Yellowstone) |

---

## 1. The estimand: what every prediction means

Every prediction answers the same question:

> **P(encounter)** — the probability of encountering evidence of taxon *X*, using **method M** with **standard effort E**, within **place P** during **time window T**, given information available **as of time A**.

- **The method generalizes to evidence modality.** This is what makes the framework work for rare species:
  - *see*: dive, snorkel, hike, boat, birding checklist
  - *hear*: listening, acoustic recorder
  - *sign*: tracks, scat, kills
  - *camera trap*
  - *catch*: used only as a source of observations, never as a product output
- **Different species, different headline methods.** For a mountain lion, the honest headline might be "probability of finding fresh sign on a 2-hour trail survey" or "camera-trap detection rate." The probability of seeing the animal can also be shown, but it will be tiny everywhere.
- **Each method has a standard effort unit:**
  - 60 min dive
  - 1 h / ≤2 km birding checklist
  - 2 h trail survey
  - 1 camera-trap-week
- **Every prediction carries:**
  - the probability
  - an uncertainty interval
  - a confidence grade
  - **per-signal contributions** (the "why")
  - the model version
  - the as-of time
  - the policy tier applied

**Relative framing for rare species.** When absolute probabilities are tiny, also report **lift**: the probability here and now relative to a regional baseline. For example: "8× the regional average; still uncommon."

---

## 2. Architecture

```
            ┌──────────── Profile generation (metadata → draft profiles; community review) ───────────┐
            ▼                                                                                          │
 Connectors ─► Canonical stores ─► Signal graph ─► Species models ─► Prediction store ─► Policy ─► API ─► Web app
 (global +     observations,       raw → derived    prior + signals   sparse indexes:     tiers,    species-first
  regional)    signals (as-of),    signals; other   + nowcast +       species→cells,      coarsen,  & place-first
               places, context     species' models  detectability     cell→species        delay,    queries
                                   as signals            │                                licenses
                          ▲                              │
                          └────── Evaluation harness ◄───┘  (backtests, baselines, calibration, maturity gates)
```

Two speeds:

- **Batch (nightly/weekly):**
  - ingest data
  - refresh signals
  - refit models
  - recompute priors and forecast tensors
  - run backtests
- **Incremental (minutes):**
  - new observation arrives
  - nowcast update for affected cells and species
  - prediction store patched

---

## 3. Core entities (canonical data model)

These schemas are the contracts. Connectors produce them, and models and products consume them.

### Taxon
```
taxon_id            internal stable id
scientific_name, rank, parent_id, common_names{lang: [..]}
crosswalk           {wikidata, gbif, inat, ebird, itis, worms, ncbi, iucn, fishbase, …, aliases: ["WSB", …]}
guilds              ["kelp-forest-pelagic-predator", "large-terrestrial-carnivore", …]
taxonomy_version    + synonym/split/lump history (so old observations map forward)
```
**Identity sources:**
- **Crosswalk hub:** Wikidata (CC0; carries iNat, GBIF, eBird, IUCN, ITIS, NCBI, WoRMS, FishBase and Avibase IDs). It is built from weekly dumps rather than live queries. Every ID is **verified both ways** against the source, because Wikidata has stale and wrong IDs.
- **Canonical backbone:** Catalogue of Life XR (CC BY), pinned to an *annual* release, with monthly diffs tracked. GBIF.org switched its default taxonomy to COL XR in June 2026.
- **Group-specific authorities:**
  - birds: AviList / eBird-Clements
  - marine: WoRMS
  - US agency alignment: ITIS

**We model taxon concepts, not names.** A name maps to a usage in a specific checklist version, which maps to a concept. Concepts are related by equal / includes / included-in / overlaps.

Change events (eBird annual tables, iNat swaps/splits/merges, COL diffs) are ingested and applied:

| Change | Handling |
|---|---|
| Swap (rename only) | Move the pointer |
| Lump | Union of ranges; recompute traits |
| Split | Each child inherits the parent's profile, marked *needs review*. Historical observations are reassigned by range. Children inherit the parent's sensitivity tier **or higher**, because splits often create narrow-range endemics. |

Every profile field is stamped with the taxonomy version it was asserted under.

### Place and Cell
- **Cell:** an H3 hexagon. Fields are stored at a small set of resolutions (e.g., res 5 ≈ 250 km², res 7 ≈ 5 km², res 9 ≈ 0.1 km²).
- **Place:** a named polygon (dive site, hotspot, trailhead, park, zone) with kind, access status and habitat tags, mapped to its covering cells. Users think in places; the math runs on cells.

### Source
```
source_id, kind (observation | signal | context), coverage (polygon + taxa), latency,
license (per-record or per-source), attribution, terms_url, commercial_ok, redistribution_ok,
observation_process (for observation sources — see below)
```

### Observation
```
taxon_id
footprint           geometry + positional uncertainty (point, obscured cell, fishing block, trip zone, radar footprint…)
time_window         start/end (+ timezone, + "date may be upload date" flags)
method, protocol    see / hear / sign / camera / catch; e.g., "eBird complete checklist", "CPFV trip"
effort              duration, distance, area, observers, angler-hours, trap-nights…
outcome             detected | not_detected | count | presence_only
evidence_grade      C1 hard evidence (photo/audio/specimen/DNA/carcass, verified) | C2 expert-verified sign
                    | C3 unverified report | M model detection (+score)   — SCALP-style C1–C3 grades used in carnivore monitoring
source_id, source_record_id, license, sensitivity flags (obscured, embargoed), ingested_at
```

### ObservationProcess (per source; the key to combining sources)
Each source declares how it observes the true state, so models can use it correctly:
```
type                presence_only | detection_nondetection | count | catch_rate | acoustic | camera
effort_model        how effort scales detection (e.g., 1 − exp(−λ·effort·q))
bias_model          e.g., target-group background, access/road proximity, observer density
false_positive      misidentification / classifier error rate (prior + learnable), plus a confusion
                    matrix of look-alike taxa (e.g., bobcat/house cat/coyote/dog → puma)
reporting_dynamics  duplicate reports of one individual; spikes after media coverage; preferential sampling
                    (roads, trails, backyard cameras)
spatial_support     how footprints map to cells (point / area integration)
latency, dedup_rule e.g., group checklists, multiple divers reporting one encounter
```
False-positive-aware observation models are needed in three places:
- misidentified mountain lions (bobcats and house cats reported as lions)
- acoustic classifier errors (BirdNET)
- species-name confusion in fishing reports

### Signal
```
signal_id, version, units, footprint (cell | station | region), valid_time, issue_time, value
(or quantiles / ensemble), source lineage
```
`issue_time` vs `valid_time` gives forecast semantics and leak-free backtests ("as-of" queries).

**Signals form a DAG:**
- raw → derived (anomalies, lags, rolling windows, hours-after-sunset, tide stage at dawn, snow-tracking conditions)
- **a species prediction can itself be a signal.** For example, a market squid aggregation forecast → white seabass; mule deer fawning → mountain lion; migration intensity → warblers.

### SpeciesProfile
See §4. A declarative, versioned document with a provenance record for every field.

### Prediction
```
taxon_id, cell|place, time_bin, method, effort_unit, as_of,
p, interval, lift_regional, anomaly_vs_norm, confidence_grade,
contributions{term: Δlog-odds}, maturity_level, model_version, policy_tier_applied
```

---

## 4. Species profiles: generated, inherited, reviewed

### 4.1 Inheritance
```
kingdom → class → order → guild template(s) → species profile → regional override
```
Templates supply defaults:
- the "large-terrestrial-carnivore" template supplies crepuscular activity, territory-scale state, sign- and camera-based methods and a conservative policy;
- the "shorebird" template supplies tide signals and checklist methods.

A species profile overrides only what differs. A **regional override** allows different behavior or policy per region. For example, wolves in Yellowstone (established managed viewing) vs. wolves in California (recolonizing, endangered).

### 4.2 Traits drive model defaults ("any species" gets sensible behavior)
| Trait (source: trait DBs / extraction) | Default it sets |
|---|---|
| Home range / territory size | Latent-state spatial scale, nowcast spatial kernel, **minimum display resolution** |
| Mobility / migratory status | Nowcast decay half-life; seasonal-prior structure (resident vs. migrant) |
| Activity pattern (diurnal / nocturnal / crepuscular) | Diel curve within a day |
| Habitat, depth range, elevation range | Habitat mask from land cover, bathymetry, DEM |
| Thermal range (ectotherms, marine) | Shape prior on temperature response |
| Breeding / spawning / migration timing | Seasonal prior shape; sensitivity windows |
| Conservation status, persecution risk | Policy tier (see §8) |
| Body size, detectability class | Detection-model priors per method |

### 4.3 Generation pipeline
Sources, licenses and the evidence on LLM extraction accuracy: [`../research/07-species-metadata-profiles.md`](../research/07-species-metadata-profiles.md).

1. **Resolve identity** (§3 Taxon): fuzzy name match (Global Names Verifier) → COL XR concept → Wikidata crosswalk → per-ID verification.
2. **Status and sensitivity first.** Pull status sources and compute the policy tier (§8) **before anything else is published**:
   - USFWS ECOS
   - state lists (CDFW Special Animals)
   - NatureServe
   - CITES
   - iNat place-scoped statuses
   - the eBird sensitive list

   **An LLM never sets or lowers status or tier.** Zero-shot LLM threat classification has been measured at only ~10 points above random.
3. **Route to curated trait databases by taxon group:**

   | Group | Databases |
   |---|---|
   | Birds | AVONET, TetrapodTraits, EltonTraits |
   | Mammals | COMBINE, PanTHERIA, TetrapodTraits |
   | Herps | TetrapodTraits, AmphiBIO, ReptTraits |
   | Marine | WoRMS (FishBase/SeaLifeBase only if licensed) |
   | Butterflies | LepTraits |
   | Plants | TRY |
4. **Compute priors from occurrence data:**
   - seasonal phenology
   - diel pattern (flagging observer bias)
   - commercial-safe ranges (H3 occupancy from CC0/CC BY records; iNat Open Range Maps, which are CC BY)
   - marine depth/temperature envelopes from OBIS records + environmental layers (a commercial-safe substitute for the NC-licensed FishBase/AquaMaps)
5. **Fill gaps with LLM extraction** from Wikipedia, then Plazi/BHL/open-access papers. Every extracted field must carry:
   - a **verbatim evidence span** plus source revision ID, machine-checked to exist and to name the taxon or a synonym
   - a confidence built from cross-model agreement, agreement with trait DBs, source quality and self-report
   - the extraction model + prompt hash

   Further rules:
   - Extract only from retrieved text, never from model memory.
   - Use controlled vocabularies with a "not stated" option.
   - Bound numeric values by genus/family ranges.
   - Measure accuracy per field on the overlap with trait DBs and calibrate acceptance thresholds from it.
6. **Taxonomic imputation** (e.g., genus mode) for remaining gaps, flagged as imputed.
7. **Reconcile.** Precedence (highest first):
   1. human-verified override
   2. the authoritative source for that scope (e.g., ECOS for ESA, CDFW for California)
   3. measured values in curated DBs
   4. imputed values in curated DBs
   5. referenced Wikidata statements
   6. LLM extraction with evidence
   7. taxonomic imputation
   8. unsourced LLM knowledge, as a reviewer hint only

   Conflict rules:
   - Local scope beats global for local display.
   - Newer assessments beat older.
   - Categorical conflicts are kept and flagged.
   - Numeric values that differ by more than 2× are flagged.
8. **Validate:**
   - schema checks
   - sanity checks against occurrence data (e.g., an extracted breeding season vs. the observed seasonal peak)
   - review routing ranked by **uncertainty × impact**
9. **Publish as a versioned draft profile** at maturity Level 0/1 (§5.4).

**Per-field provenance record:** value, vocabulary/unit, source + version, retrieval date, **license**, method (import / extracted / imputed / computed / human), evidence URL + span, confidence, taxonomy version, review state.

**License taint tracking.** Every value carries its source license, including LLM extractions, which inherit the licenses of the texts they read. The project is non-commercial ([`licensing.md`](licensing.md)), so NC sources are usable. Taint tracking now:
- labels each published product with its inherited license;
- produces a **fully open variant** from CC0/CC BY/public-domain inputs for unrestricted reuse;
- keeps restricted and partner inputs from being re-exposed.

Wikipedia facts may be stored as structured fields with a revision-ID citation, never the sentences. Displayed Wikipedia text is CC BY-SA and lives in a separately licensed component.

**Principle: generated metadata enters as weak priors and hypotheses, never as ground truth.** A profile's assumptions about how a species behaves only shape predictions until observed data overrides them. Every candidate signal is a hypothesis that the evaluation harness measures (§9).

**Implementation (Phase 2).** `src/wildlife_radar/profilegen/` implements steps 1, 3–5 and 7–9; step 2 is the existing tier table (`policy/statuses.py`), now fed verified iNaturalist ids from the crosswalk. Drafts are written to `data/profiles/generated/` (git-ignored) and enter `profiles/species/` only through `profilegen promote`, which records the reviewer and locks the checked fields. Not yet done: taxonomic imputation (step 6), trait databases beyond TetrapodTraits, Plazi/BHL sources, cross-model agreement, and calibrating per-field acceptance thresholds on the overlap with trait databases. Findings from the first runs: [`../research/09-effort-models-and-profiles-2026-11.md`](../research/09-effort-models-and-profiles-2026-11.md).

### 4.4 Community contributions
Contributions are typed, versioned and reviewed, like pull requests:

- **Observations with effort**, including **non-detections**: dive logs, trail surveys, checklists. These are the highest-value contribution.
- **Profile edits:** traits, seasonality, sources, with citations.
- **Hypotheses:** "species X responds to signal Y". These are queued for automatic ablation testing and get a public scorecard.
- **Place notes:** access, habitat, local regulations.
- **Verification:** confirming IDs and evidence grades.

Supporting mechanisms:
- a trust/reputation system
- reviewer roles (including invited experts)
- contributor license terms (CC BY 4.0 or CC0), so contributions are maximally reusable by science and education
- **field-level locks:** sensitivity and status fields are editable only by privileged reviewers
- upstream re-syncs **never overwrite verified fields**; they raise conflicts instead
- text pasted from NC or BY-SA sources is rejected
- non-sensitive verified facts are contributed back to Wikidata
- moderation of sensitive locations at submission time (§8)

### 4.5 Example profile (abridged)
```yaml
taxon: puma-concolor
extends: [guild/large-terrestrial-carnivore]
methods:
  headline: sign_survey            # 2 h trail survey for fresh tracks/scat/scrapes
  also: [camera_trap, see]
latent_state: {scale: territory, spatial_km: from_trait(home_range), dynamics: slow}
signals:
  diel_activity:   {from_trait: activity_pattern}           # crepuscular
  prey_index:      {signal: species/odocoileus-hemionus, direction: +, strength: weak, hypothesis: true}
  tracking_conditions: {signal: derived/substrate_or_snow_recent, applies_to: sign_survey}
sources:
  inaturalist:   {obs: presence_only, false_positive: elevated}
  camera_traps:  {obs: camera, effort: trap_nights}
  roadkill:      {obs: presence_only, bias: roads}
  user_surveys:  {obs: detection, method: sign_survey}
policy:
  default_tier: 2                   # awareness only: territory scale or coarser, no hotspots, no nowcast
  regions:
    ca-southern-central-coast: {tier: 2, note: "CESA threatened DPS (Feb 2026 vote)"}
    torres-del-paine:          {tier: 1, mode: viewing, via: licensed_guides}   # managed viewing
```

```yaml
taxon: canis-lupus
extends: [guild/large-terrestrial-carnivore]
policy:
  default_tier: 2
  regions:
    california:            {tier: 2}          # CESA endangered; recolonizing
    yellowstone-np:        {tier: 1, mode: viewing, exclude: [boundary_hunting_units_in_season]}
  always_suppress: [dens, rendezvous_sites, collared_individuals, dispersers]
```

---

## 5. Fusion model

### 5.1 Additive structure (the shared format)
```
logit P(encounter | cell, t, method) =
      prior(cell, season)                      # where/when it usually is (slow)
    + Σ_k f_k(signal_k(cell, t))               # conditions, prey, moon, weather… (fast)
    + nowcast(recent evidence near cell, t)    # decayed in space/time; contagion-corrected
    + detect(method, conditions, effort)       # can you detect it if present?
```
- **Explanations:** each term's contribution is the "why".
- **Expert/profile priors:** each `f_k` gets a shape and strength prior (e.g., "optimum 14–18 °C, moderate"). These priors are then learned from data.
- **Black-box terms allowed:** a GBM or neural term can fill any `f_k` where data are rich, wrapped so it still reports a contribution.

### 5.2 Linking data sources to the latent state
Each source's `ObservationProcess` ties its records to the same latent intensity λ, integrated over the record's footprint:

| Source type | Link to λ |
|---|---|
| Catch data | Poisson(λ·effort·catchability) |
| Checklists and dive logs | Bernoulli(1 − exp(−λ·q·effort)) |
| Presence-only | Thinned point process with a bias model |
| Acoustic and camera | Detection with false positives |

This is an **integrated species distribution model**. It is implemented in stages, with simple per-source models first and joint fitting later.

### 5.3 Multi-scale latent state
Species declare a characteristic spatial and temporal scale, from traits or overridden in the profile:

- **Kelp-forest fish:** km-scale, day-to-week dynamics.
- **Large carnivores:** a chain of nested states, from slow to fast:
  1. **range** (years)
  2. **territory occupancy ψ** (season; cells about a home-range fraction, e.g., H3 res 5–6 for pumas, whose SoCal home ranges run ~134–372 km²)
  3. **use intensity** (weeks: prey, fire, recreation pressure)
  4. **availability** (diel, weather)
  5. **method-specific detection**

  Fine-resolution outputs are derived products of the coarse state. That is both more honest and safer. Individual-level states (named or collared animals) stay internal.
- **Migrants:** a seasonal flow component driven by migration-intensity signals.

### 5.4 Maturity ladder (with gates)
| Level | Content | Built by | Gate to show |
|---|---|---|---|
| 0 Baseline | Seasonal × spatial prior from occurrences, bias-corrected; range/habitat masks | Automatic | Enough records; beats a range-only map |
| 1 Conditions | Plus guild/trait-default signals | Templates | Beats Level 0 out-of-sample |
| 2 Live | Plus nowcast from recent evidence | Automatic when a live source exists | Beats Level 1 and persistence |
| 3 Curated | Plus species-specific signals and observation models | Profile + review | Beats Level 2; calibration acceptable |

When a gate fails, the product shows the lower level, **labeled as such**. Species with too little data show range and seasonality only, with an explicit "insufficient data" state.

---

## 6. Rare and cryptic species

What changes for mountain lions, wolves and similar species, and how the framework absorbs it:

| Challenge | Framework answer |
|---|---|
| Direct sightings are vanishingly rare | Headline methods are **sign** and **camera**; report **lift** alongside absolute p |
| Few, biased, often misidentified reports | Evidence grading and false-positive-aware observation models; down-weight unverified reports |
| Key data held by agencies and researchers (collars, camera grids) | Partnership connectors with per-source embargo and resolution rules; never re-expose |
| Territory-scale ecology | Multi-scale latent state (§5.3); coarse occupancy + diel/seasonal activity |
| Detectability depends on conditions | `detect()` term, e.g., fresh snow or soft substrate for tracks, camera density |
| Persecution, harassment, habituation, public-safety risk | Tier 2–3 policy by default (§8): landscape-scale only, no hotspots, no nowcast, long delays |
| Region-dependent ethics | Policy is keyed by **(taxon, region)**: managed viewing destinations can get a different tier from recolonizing populations |

**What is realistically predictable** (see [`../research/06-rare-carnivores.md`](../research/06-rare-carnivores.md)):

| Estimand | Meaning | Where valid |
|---|---|---|
| ψ(cell, season) | Territory-scale occupancy | Everywhere with data |
| λ_sign(route, day) | Expected sign detections per km, given ψ, substrate, days since snow/rain, trail type | Everywhere |
| λ_cam(site, period) | Expected camera detections per 100 trap-nights | Everywhere |
| P(≥1 sighting \| n days, guided) | Calibrated against watcher or operator logs | **Only managed viewing systems** |
| Awareness index | Relative, never absolute; never claims "safe" or absence | Everywhere |

**Managed viewing systems share five traits:**
- high density
- open terrain with long sightlines
- habituated animals
- a human spotter network (scopes, radios, guides)
- governance

Examples: Yellowstone's Lamar Valley wolves, Torres del Paine pumas, Pantanal jaguars, Sierra de la Culebra wolves. Pumas in SoCal chaparral meet none of these conditions.

There is also evidence that **hunting next to viewing areas reduces viewing**: visitor sighting odds were 45% higher in years without harvest of road-associated Yellowstone packs. So in boundary hunting units during the season, viewing-mode outputs are suppressed.

**Agency data is used as coarse priors, never redistributed at fine scale.**
- Agencies publish carnivore locations for *conflict awareness*, coarsened or delayed. Examples: CDFW wolf territories; ODFW areas of known wolf activity; WDFW pack polygons via ArcGIS REST; Colorado's monthly watershed map.
- Fine-scale feeds (e.g., CDFW's daily collared-wolf tracker for livestock producers) are not ingested for redistribution.
- Wildlife-radar applies its own policy and does not rely on upstream obscuring. For example, Wildlife Insights fuzzes only IUCN CR/EN/VU species, so LC pumas and wolves may be exact upstream.

**Two product modes for these species:**

- **Awareness mode** (default):
  - "you're in mountain lion country"
  - typical activity times
  - safety and coexistence guidance (pets, livestock, children, encounter behavior)
  - what sign to look for
- **Viewing mode** (only where the (taxon, region) tier allows):
  - for established, managed viewing contexts
  - season and time-of-day guidance, plus etiquette
  - points users to official guidance and licensed guides rather than coordinates
  - never real-time pack or individual positions

---

## 7. Query model: species-first and place-first

Both query types read from the same **sparse prediction store**.

### 7.1 Storage
As built in Phase 1, the store holds **sparse sufficient statistics, not a dense prior tensor**. On the first real-data sample, a dense species × cell × week tensor was ~70× larger than the data that produced it.

- **What is stored:**
  - smoothed effort per group × level × cell × week;
  - smoothed detections per taxon × level × cell × week, only where non-zero;
  - the cells with effort and their H3 parents;
  - each taxon's range mask (context cells with records + one ring).
- **Estimates are computed on demand.** The hierarchical shrinkage runs only for the cells a query needs (`baseline/estimate.py`), so storage scales with the data rather than with taxa × cells.
- **Answering at the policy tier's level.** A query is answered at the finest level its policy tier allows: cell (res 6) for open, parent (res 5) for generalized, context (res 3) for coarse. A coarse answer is therefore a genuinely coarse estimate, not an average of fine ones.
- **Two access paths:**
  - species → cells, via the range mask, for species-first maps;
  - context cell → candidate taxa, via the mask, for place-first lists.
- **Consistent hierarchy.** Coarser cells are always H3 parents of the finest valid cell, so the store, the baseline hierarchy and the policy coarsening agree. Independent point lookups don't nest exactly.
- **Dynamic layers** (conditions, nowcast; Phase 3) will be computed on demand for the candidate set, with nightly precomputation for featured regions and species.

### 7.2 Species-first ("where/when can I find X?")
- **Inputs:** taxon, region or radius, date window, method.
- **Outputs:**
  - a map of p (or lift) by cell/place;
  - a **best-windows calendar** (days × time-of-day);
  - the top drivers;
  - confidence;
  - regulations and ethics notes.

### 7.3 Place-first ("what's here, and what's special here?")
- **Inputs:** location or place, date window, method(s), optional user life list.
- Four ranked lists, computed per (species, place, time):

| List | Metric | Meaning |
|---|---|---|
| **Most likely** | p | What you'll probably encounter |
| **Special to here** | lift = p_place / p_region (region = ~100–300 km neighborhood or ecoregion) | What this place offers that the surroundings don't. "TF-IDF for wildlife." |
| **Unusual right now** | anomaly = p_now / p_norm(place, week) | Seasonal peaks, irruptions, rarities, conditions-driven events |
| **New for you** | p × 1[not on life list] | Personal targets |

Interest weighting (global rarity, community "charisma" votes) is applied as a re-ranker, not baked into p.

Place-first output is the most exposed surface for sensitive species. Policy filtering runs **before** ranking, so tier-2+ species never leak through "special to here".

---

## 8. Policy layer (enforced at egress)

Policy is part of the framework, not a feature. All outputs (API, exports, tiles, alerts) pass through one enforcement point.

- **Tiers.** Each tier sets minimum spatial resolution, minimum delay before recent evidence is shown, whether nowcast and alerts are allowed, and whether the species appears in place-first lists.

  | Tier | Output rule | Automatic triggers (any one; the tier is the max over triggers, scoped to place) |
  |---|---|---|
  | 0 Open | ≥1 km; 24 h delay on public sightings | No triggers, taxon resolved, all lookups fresh |
  | 1 Generalized | ≥5 km or zone × week; ≥7-day delay; no nowcast boost | IUCN NT/VU without disturbance threats; NatureServe G3/S3; state Species of Special Concern; seasonal windows (e.g., spawning-season white seabass) |
  | 2 Coarse / awareness | ≥20–100 km; month-level; no real-time; excluded from "special to here"; carnivores in awareness mode | iNat geoprivacy *obscured*; eBird sensitive list; ESA/CESA threatened or endangered; IUCN EN/CR; CITES App. II; G1–G2 / S1–S2; CNDDB sensitive flag. **Also the default whenever anything is unknown or stale.** |
  | 3 Withheld | Region-level presence only; vetted partners only | iNat geoprivacy *private*; CITES App. I; status ≥ VU with hunting, collection or persecution threats; known poaching targets; nest, roost, den, hibernaculum, lek or spawning-aggregation context |

- **Fail-closed rules:**
  1. Missing data, unresolved taxonomy, a failed status lookup, or a stale source → tier 2, not tier 0.
  2. Tier **raises** happen automatically and immediately. **Lowering** a tier requires two reviewers, a written rationale and an expiry/review date.
  3. A species takes the highest tier of any subspecies or distinct population segment present in the place.
  4. Seasonal context can raise the tier (breeding and spawning windows).
  5. Tiers are enforced on *everything* derived: hotspots, "best time" hints and place-first rankings. Fixed grids block differencing attacks.
  6. LLMs never set or lower tiers.
  7. The inputs behind every tier decision are logged.
- **Seasonal and regional windows:**
  - (taxon, region, date range) → tier, for example spawning-season white seabass;
  - (taxon, region) overrides, for example managed viewing areas.
- **Always suppressed, whatever the tier:**
  - dens, rendezvous sites, nests, roosts
  - named or collared individuals and dispersers
  - anything derived from collar data
  - small counts, which are suppressed in aggregate outputs
- **Never de-obscure.** Honor source obscuring, embargoes and user geoprivacy. User-submitted sensitive locations are coarsened at submission time.
- **Re-identification resistance:**
  - Obscured points can be inferred from a user's nearby observations, and images leak location. Coarsening has to consider the whole output, not single records.
  - Abuse detection: rate limits, flagging repeated fine-grained queries on sensitive taxa, and no export of sensitive layers.
- **Never claim absence or safety.** A false negative ("no lions here") is a harm.
- **License ledger:**
  - per-record license carried through to predictions;
  - outputs tagged with the most restrictive license of their inputs;
  - published products labeled with their inherited license (NC in → NC out), plus a fully open variant;
  - restricted and partner inputs never re-exposed;
  - attribution strings generated automatically.
- **Public data products are always post-policy.** This covers the API, tiles, bulk dumps and released model artifacts. Unfiltered intermediates for tier ≥1 species are never published.
- **Context in outputs:** regulations (MPAs, take rules), approach distances, safety and coexistence guidance.

---

## 9. Evaluation harness

- **As-of backtesting:** predictions are recomputed using only signals with `issue_time ≤ as_of`.
- **Splits:** forward-in-time and spatial-block. Never random.
- **Baselines for every species:**
  - climatology (place × week);
  - persistence (last period);
  - range-only (Level 0's competitor).
- **Metrics:**
  - Brier score and log loss;
  - reliability diagrams;
  - skill vs. baselines;
  - for rare species, PR-AUC and calibration at the low end.
- **Hypothesis testing:** for each candidate signal, run an ablation (with/without) and record Δskill with an interval in a **public hypothesis scorecard**. This tests "squid → white seabass" and "moon → X" honestly.
- **Maturity gates:** §5.4 levels are granted or revoked automatically by the harness.
- **Monitoring:** data freshness (`time_coverage_end`), drift, connector health, and calibration on live outcomes (user logs with non-detections).

---

## 10. Global design, Southern California first

- **Global defaults:**
  - occurrence data: GBIF snapshots, iNaturalist, OBIS, eBird (subject to terms);
  - ocean and weather: Copernicus, ERA5/GFS/ECMWF, satellite SST and ocean color;
  - global land cover, bathymetry and DEM;
  - astronomy (local computation).
- **Region packs** bundle the region-specific pieces. The first is `socal`:
  - regional connectors, e.g., NOAA CO-OPS, CDIP, SCCOOS, CDFW datasets, fishing reports via partnership;
  - places (dive sites, hotspots, trailheads);
  - regulations (MPAs, take rules);
  - policy overrides;
  - local partners.

  A new region = a new pack. The core is untouched.
- Everything is keyed by H3 cells and ISO timestamps (UTC + local-time derivations), with units as SI internally.

---

## 11. Tech stack and repo layout (proposal)

**Backend (Python):**
- **Storage:**
  - xarray + Zarr for gridded signals;
  - Parquet + DuckDB for observations and predictions;
  - Postgres + PostGIS for places, profiles, users and contributions.
- **Spatial and orchestration:**
  - `h3` for indexing;
  - Dagster for orchestration (assets with partitions fit "as-of" signals well).
- **Modeling:** statsmodels/pyGAM/mgcv-via-rpy2 (TBD) for GAMs; LightGBM; NumPyro/PyMC for hierarchical and integrated models; scikit-learn calibration.
- **API:** FastAPI with an OpenAPI schema, so the TypeScript client is generated.

**Frontend (later):** TypeScript; MapLibre GL + deck.gl H3 layers.

The layout as built in Phase 0 is a single package with subpackages. It can be split into separate distributions later if needed.

```
wildlife-radar/
  src/wildlife_radar/
    core/          # entities & schemas, H3/time utils, licenses, methods (as-of semantics)
    connectors/    # one module per source: inaturalist, gbif, noaa_coops, astronomy
    signals/       # signal registry (DAG), as-of store, derived-signal helpers
    profiles/      # profile schema + inheritance loader (generation pipeline: Phase 2)
    models/        # additive log-odds structure (priors/terms/nowcast fitting: Phase 1+)
    policy/        # tiers, fail-closed assignment, windows/overrides, egress filter
    evaluation/    # scoring rules, calibration, baselines, forward-in-time splits
    storage/       # DuckDB observation store (multi-res cells, visits, dedupe)
    baseline/      # Level-0 builder (sparse statistics), on-demand estimates, backtests
    serving/       # policy-enforced species-first / place-first queries
    api/           # FastAPI service
    regions.py     # region-pack loader
    synthetic.py   # synthetic world with known truth (tests, offline demo)
    cli.py, cli_pipeline.py  # operator CLI
  profiles/        # versioned profile documents (templates/ + species/)
  regions/socal/   # region pack: places, tide stations, status scopes
  tests/
  docs/
```

---

## 12. Phased roadmap (proposal)

| Phase | Deliverable | Validates |
|---|---|---|
| **0 — Skeleton** ✅ | Core schemas; H3 and as-of utilities; connectors (GBIF search + snapshot-row parser, iNaturalist, NOAA tides, astronomy); policy tiers, assignment and egress filter; evaluation harness basics; draft profiles for the five validation species; `socal` region pack | The contracts |
| **1 — Baseline for everything (SoCal)** ✅ | Level-0 target-group baseline for every species with enough records; GBIF snapshot ingestion; sparse statistics store + on-demand estimates; backtest gates vs. range-only; fail-closed status/tier table (region file + iNaturalist statuses + observed geoprivacy); species-first map/calendar and place-first lists via a FastAPI service | "Any species" + both query modes |
| **2 — Profiles** ✅ | Generation pipeline (`profilegen`: GBIF + Wikidata identity crosswalk with iNaturalist verification → TetrapodTraits → occurrence-derived seasonality and diel priors → LLM extraction with verified evidence → reconciliation → drafts); group templates; crosswalk-backed auto policy tiering; review/promote with field locks. Also **effort models**: per-dataset effort classes (checklist, casual, sensor, dive/intertidal/structured survey) with trial-based survey effort. Live LLM extraction is wired but unvalidated (needs an operator API key and a contact User-Agent for Wikipedia) | Metadata-driven profiles |
| **3 — Conditions and live** | Signal DAG with ocean, weather and astronomy; Level 1–2 for the five validation species; hypothesis scorecard | Fusion + honest testing |
| **4 — Contributions** | Effort-aware logs (dives, surveys, checklists) incl. non-detections; trust and review | The data moat |
| **5 — Web app** | TypeScript frontend | Product |

Partnership outreach runs in parallel from Phase 0 (see the research synthesis §7).

---

## 13. Open questions

1. **LLM extraction:** which model and provider, the budget per species, and the human-review threshold. Which fields may be auto-published, and which need review?
2. **Community governance:** who can approve profile changes and policy downgrades? Invited experts only, or reputation-based?
3. ~~Commercial status~~ **Decided: open source, free, non-commercial, educational** ([`licensing.md`](licensing.md)). Still open:
   - ~~Code license~~ Decided: AGPL-3.0.
   - ~~Operator~~ Decided: the founder, as an individual for now. Revisit a fiscal sponsor or nonprofit if grants are needed.
4. **Global scale target for Level 0:** all taxa, or start with vertebrates?
5. **Identity and accounts:** needed for contributions and life lists. Build or buy?
6. **How much carnivore viewing mode is acceptable,** and in which regions? Should this be decided with agency input?
7. **IUCN data.** Non-commercial use is permitted. Check the IUCN terms on redistributing raw data and range polygons before serving them.
8. ~~Marine traits~~ Resolved by the non-commercial posture: FishBase/SeaLifeBase/AquaMaps (CC BY-NC) are usable with attribution.
9. **eBird for a public web service.** API caching, EBD-derived products and S&T map redistribution still need written confirmation from Cornell, even for non-commercial use.
10. **Wikimedia access at scale.** The 2026 API rate limits mean we use dumps or Wikimedia Enterprise, not live API calls. EU database rights matter for global expansion.
