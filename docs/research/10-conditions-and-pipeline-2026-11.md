# Conditions, nowcasts and the job graph: first real runs (2026-11)

Follow-up to [`09-effort-models-and-profiles-2026-11.md`](09-effort-models-and-profiles-2026-11.md). Same data: San Diego County, GBIF snapshot 2026-11-01, records since 2010. Plus:

- recent iNaturalist records from the `live` job;
- NOAA CO-OPS daily signals at La Jolla (Scripps Pier) and San Diego Bay, 2010–2026.

## 1. Level 1 (conditions) and Level 2 (recent sightings)

**Setup:**
- Split: trained on data before 2023, tested on 2023 onward.
- Level 1 adds the condition terms the species profiles declare and daily data can support (water temperature and its anomaly, daily low tide, moonlight) on top of the Level-0 baseline.
- Level 2 adds detections and outings in the same ~10 km cell over the previous 14 days, counted strictly before the day.

**Gates:** each level must beat the level below:
- the lower end of a 90% block-bootstrap interval (blocks = test days) must be above zero;
- the Brier improvement must be at least 0.5%;
- Level 2 must also beat persistence.

| Species, effort group | Test trials (detections) | Level 1 vs Level 0 | Level 2 vs best lower level | Shown |
|---|---|---|---|---|
| Leopard shark, casual fish records | 4,698 (235) | **+0.93%** [0.23, 1.61] ✓ | +0.77% [−0.73, 2.17] | Level 1 |
| Marbled godwit, eBird checklists | 62,215 (13,363) | +0.04% [−0.00, 0.09] | **+2.25%** [2.06, 2.40] ✓ | Level 2* |
| Marbled godwit, casual records | 19,232 (1,057) | +0.01% | +0.01% | Level 0 |
| Mountain lion, casual records | 3,255 (155) | +0.24% [−0.18, 0.60] | +1.17% [0.58, 1.75] (fails persistence) | Level 0 |
| White seabass, giant sea bass | too few detections with condition data | | | Level 0 |

\* Marbled godwit is GENERALIZED (iNaturalist reports a Vulnerable-equivalent status), so the
public never sees its daily forecasts. Day-level products are for OPEN taxa only.

**Hypothesis scorecard** (each term dropped in turn; Δ = held-out log-loss gain):

| Species | Term | Verdict | Expected → fitted direction |
|---|---|---|---|
| Leopard shark | water temperature | supported | + → **−** |
| Leopard shark | water-temperature anomaly (optimum) | supported | — |
| Marbled godwit (casual) | lowest daily tide | supported (tiny) | − → **+** |
| Marbled godwit (checklists) | lowest daily tide | inconclusive | − → + |
| Mountain lion | moonlight | inconclusive | ? → + |

**Reading the results:**
- **Leopard sharks:** the famous summer aggregation at La Jolla Shores is already in Level 0's seasonality. Within the season, the anomaly term finds an optimum, and once the anomaly is included, raw temperature enters with a negative sign. The profile's "+" hypothesis is about the season, not daily variation. The profile should say so.
- **Marbled godwits:** days with *higher* lowest tides have slightly more records. A plausible reading is that birds crowd onto fewer exposed flats and roosts near observers. The effect is tiny either way.
- **Recent sightings matter most for flocking birds:** a godwit flock seen nearby in the last two weeks predicts the next checklist far better than tides do.
- **The scorecard works as intended.** It caught two hypotheses whose fitted direction contradicts the profile: those terms improve predictions, but not for the reason the profile gave.

### Three gate fixes from the real data

1. **Recalibrated Level 0.** Level 1 refits an intercept, which alone recalibrates Level 0 to recent years. Godwit checklists "passed" Level 1 only through that. The gate now compares against a Level 0 with only its intercept refitted.
2. **Practical effect.** Godwit casual records passed with a 0.02% gain (a tight interval on a negligible improvement). Levels now need ≥0.5%.
3. **Level 2 builds on the best passing level.** Recent sightings help godwit checklists even though tides don't, so Level 2 may sit directly on (recalibrated) Level 0.

## 2. The job graph on real data

`wildlife-radar run publish` ran the whole graph from scratch:

| Job | Result |
|---|---|
| snapshot | 12.6 M records registered |
| crosswalk | 9,719 names resolved (now against the Catalogue of Life) |
| repairs | 250,943 kelp-survey records re-dated earlier (none left) |
| aliases | 66 merges across 62 concepts |
| baseline | 5,391 taxa; 407,411 survey trials (up from 176,858 with the re-dated records) |
| backtest | 1,472 of 5,464 taxon × effort groups beat the range-only map |
| tiers | 5,011 OPEN / 219 GENERALIZED / 161 COARSE |
| conditions | 6 species fitted |
| live | 5,512 recent iNaturalist records |
| publish | **blocked by the audit** on the first run; published after the fixes below |

After a code change, a rerun re-executes only the affected jobs: 7 minutes instead of about
45. The API then serves the bundle and switches to new versions as they are published.

### What the first run caught

- **The audit blocked publishing (6 high findings).** The `live` job brought in recent iNaturalist records whose taxon geoprivacy is obscured for six OPEN species, including **bighorn sheep**. The Peninsular population in San Diego County is federally endangered, and nothing else in the pipeline had raised it. Tiers ran before `live` in the graph, so the new signal never reached them. Two fixes:
  - tiers now depend on `live`;
  - the curated SoCal statuses gain the Peninsular bighorn (ESA E DPS, CESA T).
- **A wrong merge came from the GBIF backbone, not from us.** The backbone maps *Neltuma odorata* (honey mesquite) to *Prosopis pubescens* (screwbean mesquite). Names are now matched against the **Catalogue of Life**, the same taxonomy GBIF snapshots use for the store's names. The remaining 66 merges are genus moves (47) or synonymies and lumps as iNaturalist defines them (19). Example: red-shafted flicker → northern flicker, and the fox sparrow forms, which iNaturalist lumps and the AOS splits.
- **Transient API failures fail closed.** A forced status refresh had 283 failed iNaturalist lookups. Those taxa went to COARSE, which is safe but wrong. Shared HTTP fetching now retries 429s, 5xx errors and connection resets with backoff. After that, COARSE went back from 367 to 154 (161 with the new geoprivacy raises).
- **Deep paging is slow.** GBIF search pages took ~40 s at deep offsets. Re-dating now lists the 340 affected events with a facet query and fetches each event's records from offset 0: minutes instead of hours.

## 3. Next steps

1. **Revise profiles from the scorecard:**
   - leopard shark: within-season water-temperature direction;
   - godwit: tide direction;
   - mark contradicted directions for review.
2. **Nowcast-only Level 2 for every OPEN taxon with enough data.** It needs no profile, and recent sightings are the strongest real signal so far.
3. **Timed records** (the iNaturalist API keeps observation times) for intra-day terms: tide stage, hours after sunset.
4. **Lake on object storage and scheduled runs** (data-platform.md §8 steps 3–5), then a second region.
