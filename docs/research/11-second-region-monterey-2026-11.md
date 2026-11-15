# A second region: Monterey Bay (2026-11)

Follow-up to [`10-conditions-and-pipeline-2026-11.md`](10-conditions-and-pipeline-2026-11.md).
Goal: show the job graph runs unchanged for a new region pack, and measure what breaks.
Region: `regions/montereybay` (Santa Cruz to northern Big Sur, inland to Pinnacles). It inherits
the California curated statuses and dataset registry (`regions/california`).

## 1. The run

One command, `wildlife-scanner run publish --region montereybay --ingest-snapshots` (plus the
reruns below):

| Step | Result |
|---|---|
| Snapshot (GBIF 2026-11-01, range requests) | 10,346 parts scanned, 6,181 with rows, 132 GB fetched in 20 min; **24.2 M records** ingested (parse 10 min, load 6 min); 3 GB store |
| Crosswalk | 8,666 names (exported to the shared reference store) |
| Repairs (kelp-survey placeholder dates) | **6.8 M records in 4,741 survey events**; 1,000 events re-dated **2.39 M records** before GBIF rate-limited the paging (see §2) |
| Live | 3,607 iNaturalist records and **1,301 Happywhale records** (GBIF) |
| Baseline | 4,867 taxa, 903 k visits, 3.75 M survey trials |
| Tiers | 4,461 OPEN, 224 GENERALIZED, 181 COARSE, 1 WITHHELD |
| Backtest | 1,472 of 4,847 taxon × effort groups pass the Level-0 gate |
| Conditions | 5 profiled species fitted; only mountain lion Level 2 passes |
| Nowcast | 300 fitted, 59 pass |
| Timed | indices for 4 profiled species (§4) |
| Publish | audit 0 high / 84 medium / 8 info; **62 MB bundle**; static products 5.3 GB (§3) |

## 2. What broke, and the fixes

1. **The audit blocked the first publish (4 high findings).** All four were curated California
   statuses that matched no taxon here. Three were SoCal-only taxa (Peninsular bighorn,
   coastal gnatcatcher, light-footed Ridgway's rail) flagged only because common epithets
   (*canadensis*, *californica*, *obsoletus*) matched unrelated species. The fourth was real:
   the curated ESA status for *Euphydryas editha* reached nothing because the region records
   it as ***Occidryas editha***, held at COARSE only because its status lookup had failed.
   Fix: the crosswalk also resolves curated names; ids sharing a resolved identity are aliases
   (only ever adding statuses); a resolved curated name with no synonym in the region is
   "absent" (info), an unresolved one stays high.
2. **GBIF rate-limits long paging.** Re-dating needs event ids that the snapshot lacks (no
   `eventid` column), so ~25,000 search pages. GBIF answered HTTP 429 after ~800 events at 8
   threads, and again after 200 more at 4 requests/s. Fix: repairs share one rate limiter,
   honour `Retry-After`, checkpoint every 200 events, stop cleanly on a rate limit or after a
   30-minute budget, and continue daily. Records not yet re-dated stay excluded, so the first
   models use ~35% of the placeholder-dated kelp surveys and improve as repairs continue.
3. **Live ticks rebuilt too much.** `tiers` reran on every live tick and, with a new version
   each time, made `nowcast` and `timed` refit every 30 minutes. Fix: tiers fingerprints its
   decisions, and a job reporting an unchanged result keeps its version.
4. **Long first publish.** The first static build took ~2.5 h for 9,700 maps (two years:
   2026, and 2027 within eight weeks of New Year). Later publishes reuse them (the final run
   built 1,244 and reused 8,488). See §3.

## 3. Static products at real scale

- Maps are ~80 per minute; a common bird's year is ~1 MB of JSON (239 KB gzipped: 421 cells ×
  52 weeks). 5.3 GB for the region; the CDN serves them compressed.
- **To do:** a compact format (cells once, per-week arrays: about half the size), building in
  parallel processes, and gzip at upload. The live path is unaffected: publishes between
  baseline rebuilds touch only the index and search index.

## 4. Timed records (iNaturalist hourly counts)

Index = share of the taxon's records in a category ÷ share of its group's records (90% CI).

| Species | Signal | Finding |
|---|---|---|
| Marbled godwit (2,822 timed records) | tide stage | low 1.14 [1.03, 1.21], falling 1.07, rising 0.96, **high 0.80** [0.70, 0.90] |
| | diel phase | night 1.28, dawn 1.29, day 0.97 |
| Mountain lion (972) | diel phase | **night 4.93** [4.45, 5.40], dawn 1.78, day 0.61 → the profile's crepuscular trait is flagged for review (camera traps likely contribute) |
| Leopard shark (118), giant sea bass (4) | — | too few timed records here |

The godwit result contradicts the shorebird guild's note that birds concentrate at roosts
around high tide (at least where people record them), consistent with the San Diego daily
result in note 10. It is a pattern in records, not behavior; both profiles stay as hypotheses.

## 5. Policy notes for the owner

- **Humpback whale is COARSE here** (iNaturalist reports DPS listings as EN/VU equivalents,
  and iNaturalist obscures its locations), so Happywhale's humpback records count only as
  effort. Risso's and bottlenose dolphins are OPEN and their recent records feed nowcasts.
  Whether a whale-watching exception is wanted is a policy decision; tiers are never lowered
  automatically.
- 84 medium findings ("threatened elsewhere" and unmapped statuses), as in San Diego.
