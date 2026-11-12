# Data platform: layers, jobs and serving (draft)

How data moves from sources to the app, for many regions, with fresh data where it matters and
cheap, simple hosting. Companion to [`framework.md`](framework.md) (what we compute) and
[`licensing.md`](licensing.md) (what we may publish).

## Decisions

| Question | Decision |
|---|---|
| Hosting | Simple and cheap: free tiers first, a small monthly budget is fine. |
| Freshness | Users must be able to see fresh data: recent sightings and current conditions, not just monthly snapshots. |
| Regions | Plan for many regions from the start. |
| Takedowns | Less stringent for now: deletions and license changes are picked up by the next full rebuild. |

## 1. Lessons from the San Diego runs

- **One shared database file doesn't work.** Every step wrote to one DuckDB file, so long jobs (backtests, re-dating) blocked every reader, including the tier audit.
- **Hand-run scripts lose state.** Steps were rerun from scratch after a failure, with no record of which inputs produced which outputs.
- **External APIs are slow and flaky at scale.** GBIF paging took ~40 s per page at deep offsets, and connections reset. Jobs must be resumable and retry, and shallow access patterns must be designed in.
- **Policy failures are silent.** The tier audit caught real under-protection three times. Publishing must be gated on it.

## 2. Layers

Each layer is written by exactly one job and read by the next. Each output is a versioned folder
with a `manifest.json` recording what produced it.

```
lake/
  raw/          immutable source pulls, by source and fetch date
    gbif-snapshot/date=2026-11-01/region=socal/part-*.parquet
    inat/region=socal/fetched=2026-11-12T10/part-*.json.zst
    noaa/station=9410230/product=water_temperature/year=2026.json.zst
  norm/         cleaned, typed, deduplicated, one schema per entity
    observations/region=socal/h3r3=8329a4fffffffff/part-*.parquet   (sorted by taxon, cell, date)
    recent/region=socal/day=2026-11-12/part-*.parquet               (live layer, last ~60 days)
    signals/station=9410230/part-*.parquet
  ref/          global reference data, shared by all regions
    taxon_identity/, taxon_alias/, statuses/, profiles/ (generated drafts)
  derived/      models and statistics, per region and build version
    region=socal/build=2026-11-01/{prior_*, gates, tiers, conditions_*, scorecard}.parquet
  publish/      what the app serves: policy-filtered, per region and version
    region=socal/version=2026-11-12T0600/{serving.duckdb, tiles.pmtiles, lists/, manifest.json}
    region=socal/CURRENT        (points at the live version; swapped atomically)
```

- **raw** is never edited. Repairs (e.g. re-dated survey records) happen in `norm`, so any build can be replayed.
- **norm** keeps each record's license through every layer, for attribution and takedowns.
- **ref** is global: a species' identity, aliases and statuses are shared by all regions. Tiers are regional, because status scopes are.
- **derived** builds are stamped with their inputs (snapshot date, signal range, code commit, model version), so backtests can be reproduced and checked for leakage.
- **publish** contains only policy-approved products: no raw observations, aggregates only, sensitive taxa at their tier's resolution, and withheld taxa absent. Then "withheld looks like unknown" holds by construction.

DuckDB remains the engine. It reads and writes Parquet directly, so jobs don't share a database
file and readers never wait for writers. A job may still use a scratch DuckDB file internally.

### Manifests

```json
{
  "job": "baseline", "region": "socal", "version": "2026-11-01",
  "inputs": {"norm/observations": "2026-11-01", "ref/taxon_alias": "2026-11-10T03"},
  "code": "git:50e9562", "model_version": "baseline-v1",
  "created_at": "2026-11-12T06:12:00Z", "rows": {"prior_hits": 6012532},
  "status": "complete"
}
```

A job is **up to date** when its latest complete manifest records the current versions of all
its inputs. `wildlife-radar run <target>` walks the dependency graph and runs only stale jobs.
A failed or interrupted job leaves no `complete` manifest, so it reruns. Long jobs checkpoint
their progress, as re-dating does by event.

## 3. Jobs

| Job | Cadence | Reads → writes | Notes |
|---|---|---|---|
| `snapshot` | monthly | GBIF snapshot → raw, norm/observations | per region; the heaviest job |
| `live` | every 15–60 min | iNaturalist API (`updated_since` cursor per region) → raw, norm/recent | see §4 |
| `signals` | hourly | NOAA CO-OPS (and later SST/weather grids) → norm/signals | water temperature updates hourly |
| `crosswalk` | daily, new names only | names in norm → ref/taxon_identity, ref/taxon_alias | full refresh monthly |
| `statuses` | daily for new taxa; refresh after 90 days | iNaturalist + curated files → ref/statuses | |
| `datasets` | per snapshot | dataset metadata, date spikes → review list | curation stays human |
| `repairs` | per snapshot | registry rules → norm | e.g. re-dating from event ids |
| `baseline` | monthly | norm, ref → derived/prior_* | incremental monthly; full rebuild quarterly picks up deletions |
| `backtest` | monthly | → derived/gates | |
| `conditions` | monthly | norm/signals, derived → derived/conditions_*, scorecard | |
| `tiers` | after statuses or baseline | → derived/tiers | |
| `audit` | before every publish | tiers vs every status signal | **any high finding blocks publishing** |
| `publish` | after any derived change, and after each `live` run | derived, recent aggregates → publish/ | policy filter + audit; atomic `CURRENT` swap |
| `profiles` | when new taxa appear | → drafts + review queue | |

Every job takes `--region`. Regions run in parallel, and global `ref` jobs run once for all.
Adding a region means adding a region pack: bounding box, status scopes, places, stations,
dataset registry. The same graph then runs for it.

## 4. Freshness: the live layer

Users need to see what's happening now: recent sightings, today's conditions. Three paths keep
data fresh without rebuilding models:

1. **Incremental ingest** (`live`): iNaturalist's API with an `updated_since` cursor per region, within its limits (≤1 request/s, ~10k/day). It writes the last ~60 days to `norm/recent`. The GBIF API and other sources can be added the same way.
2. **Recent aggregates in the bundle**: each `live` run republishes small tables:
   - `recent_detections(taxon, effort group, parent cell, day)`
   - `recent_effort(effort group, parent cell, day)`

   These feed the Level-2 nowcast and "seen recently nearby" lists. Bundles stay aggregate-only.
3. **On-demand refresh**: when a user asks about a place whose recent data is older than a few minutes, the API fetches that area's latest records with a short timeout, caches them per cell, and merges them before answering. Every answer reports the age of each part: baseline build, signals, recent sightings.

**Freshness never overrides policy.** Each tier has a minimum delay:

| Tier | Delay | Spatial / time resolution |
|---|---|---|
| OPEN | 24 h | ~1.4 km, hour |
| GENERALIZED | 7 days | ~10 km, week |
| COARSE | 30 days | ~69 km, month |
| WITHHELD | never | — |

The live layer applies these delays before anything reaches a bundle or a response. Sensitive
taxa therefore never get "fresh" locations, but their records still count as effort.

Whether OPEN's 24-hour delay could be shorter for common species (e.g. 1 hour) is a policy
question for later. It would make "seen today" possible for birds at feeders and fish at dive
sites.

## 5. Serving

| Part | What | Where (suggested) | Cost |
|---|---|---|---|
| Static products | map tiles (PMTiles), place lists, calendars, taxon pages, search index, per region and version | **Cloudflare R2 + CDN** (no egress fees), frontend on **Cloudflare Pages** | free tier covers early traffic |
| Dynamic API | forecasts and nowcasts, point queries, on-demand refresh | the existing FastAPI app in a container on **fly.io** (auto-stop when idle), loading `publish/<region>/CURRENT` read-only | a few $/month |
| Batch jobs | snapshot, baseline, conditions | short-lived **fly.io machines** with more memory (billed per second), or GitHub Actions for light daily jobs | cents to a few $/month |
| Live and signal jobs | every 15–60 min | a scheduled fly machine, or a Cloudflare Worker cron that triggers it | small |
| Lake | raw, norm, ref, derived, publish | **Cloudflare R2** (S3-compatible; DuckDB reads it directly) | ~$0.015/GB-month |

Firebase/Firestore isn't a good fit for the core data: our queries are analytical (H3
aggregates, joins over statistics), and Firestore bills per document read. It could hold
per-user data later (accounts, life lists, contributed logs), though Cloudflare D1 or a small
Postgres would serve that equally well.

The API process holds one open bundle per region it serves (lazy-loaded, routed by the
coordinates in the request) and reopens a region when its `CURRENT` pointer changes. Because a
bundle never changes after publish, swaps are atomic and rollbacks are a pointer change.

## 6. Indexing

- **Space:** H3 throughout. Partition norm and derived data by the region and the res-3 cell (the context level). Sort within files by `(taxon, res-6 cell, date or week)` so DuckDB skips most of each file.
- **Taxa:** `ref/taxon_identity` and `ref/taxon_alias` are the taxon index. A name-search index (scientific names, common names, synonyms) is built per region at publish time, as a small SQLite full-text file shipped with the bundle.
- **Precomputed at publish:** species maps per week at each tier's resolution, place lists per place per week, and calendars. Everything else is computed on demand from the sparse statistics, which answer in well under a second.

## 7. Takedowns and corrections

Deleted or re-licensed records are dropped at the next full rebuild (quarterly). The license
ledger already lets a product be rebuilt without a removed source. Faster removal can come
later: a tombstone list applied at publish.

## 8. Build order

1. **Pipeline core:**
   - versioned outputs with manifests
   - `wildlife-radar run <target>` with up-to-date checks
   - a `publish` job that writes a policy-filtered serving bundle per region (gated on the audit) and swaps `CURRENT`
   - the API serving from bundles

   This also removes the lock contention.
2. **Live layer:** the incremental iNaturalist ingest with tier delays, recent aggregates in bundles, the nowcast reading them, and on-demand refresh.
3. **Lake on R2:** sync `raw/norm/ref/derived/publish` to object storage, and run jobs on fly.io machines on a schedule.
4. **Static products:** PMTiles maps, lists and the search index published to the CDN, for the TypeScript frontend.
5. **Multi-region:** a second region pack (e.g. Northern California or Pacific Northwest) to prove the graph runs unchanged.
