# First real-data run: Level-0 baseline on the GBIF snapshot (San Diego County)

**Date:** 2026-11-11.

**Data:** GBIF.org (1 November 2026) GBIF Occurrence Download https://doi.org/10.15468/dl.jeesns. Records used: CC BY 4.0 (82%), CC BY-NC 4.0 (15%), CC0 (3%).

**Goal:** before Phase 2, check that the Phase-1 pipeline works on real data at scale and produces sensible outputs. Fix what doesn't.

Raw data and databases were kept outside the repository. Figures below are aggregate, derived statistics. Sensitive taxa are reported only as counts and policy outcomes.

## 1. Pipeline and scale

| Step | Result |
|---|---|
| Snapshot | 10,346 Parquet parts, 272 GB, 3.89 B records. Taxon keys now come from the Catalogue of Life backbone (alphanumeric, e.g. `QLXL`). |
| Extraction (Southern California bbox) | HTTPS range requests only (`tools/extract_region.py`): 135 GB fetched, **22 min**, **81.6 M rows** staged in 1.9 GB |
| Composition of the Southern California rows | 46.8 M birds (eBird via GBIF: 44.8 M). Marine monitoring datasets: 10.9 M ray-finned fish, 3.2 M kelp, 2.0 M sea stars, 1.6 M sharks/rays. iNaturalist research grade: 5.8 M |
| Ingest (San Diego County, all years) | 12.6 M records in 6 min on 4 cores; 1.9 GB DuckDB store |
| Baseline (records since 2010; specimens and captive records excluded) | **5,480 taxa** in 14 groups; 1.15 M outings; 422 cells (res 6); 5.5 M stored statistics rows; built in about 75 s |
| Backtest (train < 2025, test ≥ 2025) | About 3 min; 50k sampled test outings |

Parts are clustered by dataset (most eBird parts are eBird-only). A random sample of parts therefore samples individual records, not outings: an eBird checklist's species end up spread across parts. The effort correction needs complete outings, which is why the run scanned the whole snapshot for a bounding box.

## 2. Does the baseline beat a range-only map?

Brier skill vs. the range-only reference, for taxa with ≥5 test detections. **1,245 of 1,944 pass.**

**By data volume** (detections in the test period):

| Test detections | Taxa | Pass rate | Median skill |
|---|---|---|---|
| 5–19 | 1,002 | 46% | −0.001 |
| 20–99 | 610 | 75% | +0.015 |
| 100–999 | 265 | 97% | +0.050 |
| 1,000+ | 67 | 100% | +0.099 |

**By group** (selected):

| Group | Taxa | Pass | Median skill | 90th pct |
|---|---|---|---|---|
| Birds | 381 | 78% | +0.048 | +0.166 |
| Mammals | 28 | 68% | +0.040 | +0.268 |
| Herps | 39 | 79% | +0.028 | +0.144 |
| Plants | 822 | 66% | +0.008 | +0.054 |
| Fishes | 56 | 52% | +0.001 | +0.090 |
| Insects | 327 | 41% | −0.002 | +0.029 |

**What this means:**
- Skill grows with data, as the maturity ladder assumes. The per-species gate is doing real work: about half of the thinly recorded taxa should fall back to a range-only display.
- Birds are strong. eBird checklists are close to ideal effort units.
- Fishes and insects are weak. Marine survey data and iNaturalist photos mix very different observation processes inside one "group" denominator. This is the strongest argument for **method-specific target groups** in later phases: divers vs. tidepoolers vs. anglers.
- Strongest single gains:
  - seasonal visitors, e.g. yellow-rumped warbler +0.24, white-crowned sparrow +0.18;
  - habitat specialists, e.g. western gull +0.19 (coastal).

## 3. Natural-history checks

Each line is a policy-enforced output from the query layer. Status lookups couldn't run in this environment, so a local stand-in "no statuses found" provider was used together with the curated region file. These are not publishable tiers.

**Seasonality** (region level, peak week):
- Brant: peaks late November, absent in July (winter visitor). ✔
- Elegant tern: peaks August, absent in January (summer and post-breeding visitor). ✔
- Black-throated gray warbler: peaks mid-April (spring migrant). ✔
- Anna's hummingbird: nearly flat (resident). ✔
- Leopard shark: peaks mid/late October in the records. The known La Jolla aggregation runs about July–October. The late peak probably reflects when divers and surveys record them. ⚠

**Place-first lists:**

| Place / date | Most likely | Special here (p · ln lift) | Peaking now |
|---|---|---|---|
| La Jolla Cove, mid-May (birds) | Western gull, brown pelican, Brandt's cormorant, Heermann's gull | Brandt's cormorant 17×, black oystercatcher 24×, wandering tattler 26× | Hooded oriole, Caspian tern |
| La Jolla Cove, mid-May (fishes) | Woolly sculpin, garibaldi, horn shark, grunion | Horn shark, leopard shark, shovelnose guitarfish | **California grunion 5.4×** (spawning-run season) |
| La Jolla Cove, mid-May (mammals) | California sea lion, harbor seal | Sea lion 4.5×, harbor seal 5.9× | — |
| La Jolla Cove, mid-August (fishes) | **Leopard shark**, garibaldi, kelp bass, round stingray | Leopard shark, guitarfish | Yellowfin croaker, kelp bass |
| Cuyamaca, mid-May (birds) | Acorn woodpecker, western bluebird, spotted towhee | Steller's jay, mountain chickadee, violet-green swallow, black-chinned sparrow | Black-headed grosbeak, mountain quail |
| Anza-Borrego, mid-March (birds) | White-winged dove, Costa's hummingbird, verdin | — | **Swainson's hawk 5.5×** (spring hawk migration) |
| Tijuana Estuary, mid-January (birds) | Willet, American wigeon, snowy egret | Yellow-crowned night-heron 19×, northern harrier, marbled godwit | Wintering ducks (pintail, teal, bufflehead) |

**Sensitive taxa:**
- Mountain lion and the curated listed birds appeared only in awareness lists.
- Mountain lion and giant sea bass maps came out at 69 km cells and monthly.

## 4. Problems found and fixed in this run

1. **Probabilities aren't comparable across taxon groups.** Each p means "per outing by someone who records *this group*". A land snail at 0.66 and a bird at 0.4 are on different scales. → Place lists are now **grouped by taxon group**, with an optional group filter.
2. **"Special here" and "peaking now" were swamped by rarely recorded taxa.** Their tiny probabilities produced huge ratios: an ornamental daisy at 74×, invertebrates from a single survey week. → Both now rank by **p · ln(ratio)**, so a taxon must be both likely and distinctive.
3. **"Gray wolf" appeared in San Diego awareness lists.** These were 55 museum specimens, probably domestic dogs (*Canis lupus familiaris* collapses to *C. lupus*). → `basis_of_record` is now stored. **Museum specimens, living collections (zoos, gardens) and fossils are excluded** from baselines by default. They aren't evidence of encounterable wild presence, and collecting trips aren't comparable effort. This removed 682 specimen-only taxa.
4. **Giant sea bass would have been open.** It isn't legally listed. → Added a profile that raises it to coarse, awareness-only.
5. **Old records.** → `since_year` option; this run used records from 2010 onward.
6. **Dense storage didn't scale** (found earlier). → Sparse sufficient statistics with on-demand estimates (Phase 1). Here, 5.5 M stored rows answer queries in well under a second.

## 5. Limitations of this run

- **Status lookups couldn't run.** iNaturalist is unreachable from this environment, so the tiers above are a local stand-in. A real deployment runs `build-tiers` online; offline, everything correctly falls back to coarse.
- **One county, Level 0 only.** No conditions or recent-sightings terms yet.
- **Records-based seasonality reflects when people look.** This is clearest for fishes and other dive-recorded taxa. Detection and conditions terms (Phase 3) should help separate the two.
- **Marine survey datasets contribute non-detections.** The current target-group effort treats all of a group's outings alike. Survey transects and casual photos need different observation models (`ObservationProcess`). That is Phase 3 work.

## 6. Recommendations

1. Proceed to Phase 2 (profiles). Use gate results per taxon as an input: a taxon needs roughly ≥100 test detections before Level-0 claims are reliably better than a range map.
2. Bring forward **method-specific target groups** (birding checklists, dive surveys, tidepooling, camera traps) and **survey-vs-casual observation processes**. These are the biggest expected gains for fishes, invertebrates and insects.
3. Run the full Southern California build (81.6 M staged rows) in an environment with more cores, and with iNaturalist reachable for status lookups.
