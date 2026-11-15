# Effort models and profile generation: first real-data runs (2026-11)

Follow-up to [`08-real-data-run-2026-11.md`](08-real-data-run-2026-11.md). Same data: San Diego County, GBIF snapshot 2026-11-01, records from 2010 on (12.6 M records). Two changes are tested here:

1. method-specific **effort models** (recommendation 2 of note 08);
2. the first runs of the Phase 2 **profile-generation pipeline**.

## 1. Effort models

### Design

Every record gets an **effort class** from its dataset. Baselines are estimated per **effort group** (taxon group × effort class), so a dive survey's p and a casual photo's p are never mixed.

| Class | Where it comes from | Effort unit | Seasonality |
|---|---|---|---|
| `checklist` | eBird Observation Dataset (via GBIF), registry entries such as eButterfly | outing (observer × day × place) | weekly kernel |
| `casual` | everything else, including iNaturalist | outing | weekly kernel |
| `sensor` | machine observations | outing | weekly kernel |
| `dive_survey`, `intertidal_survey`, `survey` | monitoring programs that **record absences for the taxon** | each present/absent record (a trial) | **flat** (see below) |

The region's `datasets.yaml` registry assigns classes and excludes datasets that aren't encounter data (plankton tows, eDNA, trawls, dredges, deep-sea samples). Heuristics cover the rest. `annotate-datasets` fetches GBIF dataset metadata to help curate the registry.

### Results (split 2025-01-01; taxa with ≥ 5 test detections)

| Effort group | Taxa | Pass | Median BSS | Pooled (note 08) |
|---|---|---|---|---|
| birds:checklist | 367 | 81% | 0.083 | 78% / 0.048 (all birds) |
| birds:casual | 269 | 72% | 0.013 | ″ |
| plants:casual | 813 | 67% | 0.009 | — |
| fishes:casual | 54 | 61% | 0.009 | 52% / 0.001 (all fishes) |
| mammals:casual | 28 | 68% | 0.029 | — |
| herps:casual | 39 | 72% | 0.025 | — |
| insects:casual | 317 | 50% | 0.000 | — |

Separating eBird checklists from casual bird records gives the clearest gain: median Brier skill roughly doubles for checklist birds. The pooled "birds" group mixed two very different observation processes.

### Survey groups: three data problems found

Survey groups were scored on their own split (train before 2021, test 2021–2023), because the survey datasets have no 2025 records. The first run gave strongly *negative* skill for several kelp-forest invertebrates and algae (southern sea palm −0.28, giant keyhole limpet −0.48, giant sea star −0.47). Diagnosing them cell by cell found three problems in the data, not the model:

1. **Placeholder dates.** In the MLPA kelp-forest monitoring dataset (`154d6192…`), about 250,000 records (mostly absences) carry `eventDate` 2023-11-30, while their `eventID` holds the real survey date (e.g. `SAN_MATEO_KELP_20201008_OUTER_2_swath`). Kelp surveys are summer fieldwork, so "week 48" was an artifact. It also put most of the test set on one fake date.
   → `placeholder_dates` in the dataset registry drops such records, and `annotate-datasets` now reports date spikes (one date holding ≥ 20% of a dataset). Recovering the true dates from `eventID` needs a re-extract with that column. That is future work, and worth reporting to the publisher.
2. **Absences only for some taxa.** Once the placeholder records were removed, invertebrates in that dataset had no absences left: every test trial was a detection. The program records fish absences but only invertebrate presences.
   → A taxon gets survey (trial) effort only if it has recorded absences **in that dataset**. Otherwise its records use casual (outing) effort.
3. **Campaign dates aren't seasonality.** Surveys sample in a fixed field season, so their week-of-year pattern measures the field schedule.
   → Survey effort groups use a flat seasonal kernel: a per-site annual rate.

After the fixes, the survey groups are internally consistent: 10/31 pass. Fishes in dive surveys have modest skill (median −0.005, top +0.16 for rock wrasse). With few sites, a Level-0 site rate adds little over a range map. The main value of survey data will come in Phase 3, as a detection and abundance observation process (`ObservationProcess`), not as a Level-0 encounter rate.

## 2. Profile generation

### Identity crosswalk

`profilegen` resolves a name through the GBIF matcher, then Wikidata (SPARQL, CC0; batched 100 names per query), then verifies the iNaturalist id against iNaturalist itself.

| Query | Result | Notes |
|---|---|---|
| *Atractoscion nobilis* | white seabass; GBIF, iNat, NCBI, ITIS, WoRMS, IUCN, COL ids | fish class missing in the GBIF v1 classification → filled from iNaturalist's iconic taxon |
| *Charadrius nivosus* | snowy plover | **Wikidata pointed at an inactive iNaturalist concept** (144485). The resolver follows it to the current one (1505663, *Anarhynchus nivosus*), so its 8 conservation statuses are found. In note 08 this lookup failed and fell back to COARSE |
| *Felis concolor* | → *Puma concolor* | synonym resolved through GBIF |
| *Puma concolor*, *Canis lupus*, *Stereolepis gigas*, *Triakis semifasciata*, *Limosa fedoa* | all resolved and verified | Wikidata's English common names (P1843) are arbitrary ("red tiger", "timber wolf"), so iNaturalist's preferred name is used |

Authorities disagree on names: the GBIF backbone and base Catalogue of Life accept *Charadrius nivosus*, while iNaturalist and the snapshot's interpretation use *Anarhynchus*. The store therefore splits the plover across two ids (8,217 and 341 records). Identities carry every known name (`alias_ids`), and occurrence lookups use all of them. Merging aliases inside the baseline is future work.

### Traits and occurrence-derived priors

- **TetrapodTraits** (CC BY 4.0) gave body size, activity time, habitat use and IUCN habitat classes for the tetrapods. It has no fishes, and no match for the plover under its current name. Measured and imputed values are ranked separately.
- **Seasonality from the baseline** (per unit effort, region-wide) looks right on known cases:
  - rufous hummingbird: spring passage, weeks 12–17
  - yellow-rumped warbler: winter visitor
  - Caspian tern: summer peak
  - Anna's hummingbird and California scrub-jay: year-round
  - white seabass: summer–autumn
- **Diel patterns** need records with times. The GBIF snapshot keeps only dates, so diel priors require ingesting timed records from the iNaturalist or GBIF APIs.

### LLM extraction: wired, not yet run live

- Extraction uses structured outputs with a controlled vocabulary and an explicit "not stated" option.
- Each value's verbatim evidence is checked against the article text, along with numeric bounds and vocabulary.
- Profiles cite the revision and character range; quoted evidence stays in git-ignored audit files.

Two things block a live run from this environment, and both are operator settings:

- **Wikipedia requires a contact in the User-Agent** (Wikimedia robot policy); the default `wildlife-scanner/<version>` is refused with HTTP 403. Set `WILDLIFE_SCANNER_USER_AGENT`.
- **An Anthropic API key and an extraction model** (`--model` or `WILDLIFE_SCANNER_EXTRACTION_MODEL`).

The next step is to measure per-field accuracy on the overlap with TetrapodTraits and set acceptance thresholds from it (framework.md §4.3 step 5).

## 3. Status tiers with the crosswalk

Note 08 couldn't reach iNaturalist, so its tiers were a local stand-in. This run used the real lookups:

1. `profilegen crosswalk` resolved all 5,386 baseline taxa in about 6–12 minutes: Wikidata first, GBIF only for misses, then iNaturalist verification.
2. `build-tiers` looked up iNaturalist statuses by verified id, 30 per request.

| | First pass | After fixes |
|---|---|---|
| Taxa with a verified iNaturalist id | 4,975 (92%) | **5,263 (97.7%)** |
| Status lookups failed (fail closed → COARSE) | 136 | **67** |
| Tiers: OPEN / GENERALIZED / COARSE | 4,951 / 218 / 217 | **5,015 / 219 / 152** |

The first pass found two problems and one improvement:

1. **Curated statuses were silently skipped (fail-open).** `build-tiers` only looked for `regions/<id>/statuses.yaml`. With the ad-hoc `sandiego` region they were never read, so **mountain lion (CESA T, Southern California/Central Coast) and coastal California gnatcatcher (ESA T) came out OPEN**. iNaturalist has no statewide status for either.
   → `--statuses`, a lookup next to the region file, and a loud warning when no curated file is found. Both are now COARSE.
2. **Curated statuses keyed by an old name didn't reach a renamed concept.** The curated ESA entry is keyed `charadrius-nivosus`; the store has `anarhynchus-nivosus`. Wikidata has a separate new item for *Anarhynchus nivosus*, linked to the old name only through "original combination" (P1403).
   → The crosswalk now collects Wikidata synonyms and original combinations, and tier inputs carry those aliases. The snowy plover is now COARSE (ESA T, Pacific coast population).
3. **Name matching against iNaturalist** improved in two ways:
   - Epithets now match up to Latin gender agreement (*Bacillaria paxillifer* / *paxillifera*).
   - The search accepts an exact synonym match (`matched_term`), e.g. *Aeorestes cinereus* is filed under *Lasiurus cinereus*.

The 67 lookups that still fail are mostly plants (34) and insects (25): hybrids, names iNaturalist places at another rank, or names it doesn't have. They fail closed to awareness-only, as designed.

Validation species after the fixes:

| Taxon | Tier | Why |
|---|---|---|
| Mountain lion | COARSE | CESA T (curated, regional population) |
| Snowy plover | COARSE | ESA T (curated, Pacific coast population); iNaturalist VU/NT equivalents |
| Giant sea bass | COARSE | IUCN CR; iNaturalist obscures it; profile default |
| California least tern, Ridgway's rail, coastal California gnatcatcher | COARSE | ESA (curated, subspecies) |
| Marbled godwit | GENERALIZED | iNaturalist VU equivalent |
| White seabass, leopard shark | OPEN | no triggers |

Lesson: **the policy layer needs end-to-end checks on real data.** None of these problems raised an error. Two listed species came out OPEN, and the plover came out one tier lower than intended. Tests now cover the alias matching. Cross-checking against the crosswalk, **no OPEN taxon has a threatened IUCN category (VU, EN or CR) on Wikidata**. A pre-publication audit should run checks like this routinely: every OPEN taxon with any status signal anywhere (Wikidata, curated file, iNaturalist at any scope) goes to human review.

## 4. Recommendations

1. Add the pre-publication tier audit described in §3, and run it before any public deployment.
2. Re-extract the kelp-forest dataset with `eventID` and recover the true survey dates; report the placeholder dates to the publisher.
3. Merge alias ids inside the baseline once the crosswalk is complete, so renamed concepts aren't split.
4. Run live LLM extraction on the validation species with an operator key and User-Agent, and score it against TetrapodTraits before trusting any extracted field.
5. Add timed records (iNaturalist API) for diel priors, and more trait databases (AVONET, COMBINE) for birds and mammals.
6. Model surveys as an observation process (detection and abundance) in Phase 3.
