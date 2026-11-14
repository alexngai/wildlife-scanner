# Ingestion and data model: staying fresh (proposal, 2026-11-13)

Status: **accepted 2026-11-13; steps 1, 2 and 4 implemented** (see §6). Builds on
[`data-platform.md`](data-platform.md) (layers, jobs) and measurements from San Diego and
Monterey Bay ([`../research/10`](../research/10-conditions-and-pipeline-2026-11.md),
[`11`](../research/11-second-region-monterey-2026-11.md)).

## 1. What we have now

| Source | How | Cadence | Latency to users |
|---|---|---|---|
| GBIF (everything, incl. eBird EOD) | monthly snapshot on AWS, range-request extraction per region bbox | monthly | 1–2 months (plus eBird's yearly release) |
| iNaturalist | API, `updated_since` cursor, 60-day window, per region | 30 min | 24 h (the OPEN delay) |
| GBIF "live" datasets (Happywhale) | API by dataset key, per region | 30 min | publisher's lag (days) |
| NOAA CO-OPS | API | daily | 1 day |
| iNaturalist hourly counts | histogram API, cached | monthly | n/a (model input) |
| Reference: identities, iNat taxon records, GBIF event ids | APIs, shared Parquet parts (`lake/ref`) | as needed | n/a |

Everything else lives in **one DuckDB work store per region**. Raw records, repairs, model
tables and caches are mixed together; the store is single-writer and exists only on the
worker's disk.

**What the runs taught us:**
- **A region's snapshot pass scans everything.** It fetches ~132 GB (~36 min), so N regions
  cost N × 132 GB a month, and overlapping regions (`socal` ⊃ `sandiego`) store the same
  records twice.
- **Repairs mutate rows in place.** Each new snapshot brings the placeholder dates back. Event
  ids are in the reference store now, but the fix is still re-applied by hand-written code
  rather than being part of the data.
- **Losing a work store costs ~3 h per region**, plus days for rate-limited repairs (event ids
  now fixed).
- **GBIF's "changed since" is mostly reprocessing:** 181 M California records were
  reinterpreted in one week (mostly eBird and the kelp survey). A weekly GBIF-wide delta by
  `lastInterpreted` isn't viable. The monthly snapshot stays the backbone for GBIF at large.
- **iNaturalist deletions need an authenticated API** (`/observations/deleted` returns 401),
  so deletions are caught only when the next snapshot no longer has the record.
- **eBird reaches GBIF once a year.** For birds, freshness depends on iNaturalist until an
  eBird feed exists (partnership on hold).

## 2. Proposed data model

Store records **once for a coverage area** (e.g. all of California), partitioned so regions
are queries, and keep each kind of data in its own layer. Every layer is Parquet in the lake
(local folder or private bucket), so the DuckDB work store becomes a disposable cache.

```
lake/
  norm/observations/source=gbif/snapshot=2026-11-01/h3r3=<cell>/part-*.parquet   monthly, immutable
  norm/observations/source=live/day=2026-11-13/part-*.parquet                     appended every tick
  ref/{taxon_identity, inat_taxon_records, gbif_event_ids, …}/part-*.parquet       shared, per writer
  ref/corrections/part-*.parquet          record id → corrected field (dates from event ids, …)
  derived/region=<id>/build=<v>/…         baselines, gates, models (per region, versioned)
  publish/region=<id>/…                   as now
```

- **One snapshot pass for the whole coverage area.** Test every part's lat/lon once against
  the union of regions. Write rows partitioned by res-3 H3 cell, with `lastinterpreted` and
  `license` kept. A region reads the cells its bbox covers. A new region inside the area costs
  no download at all.
- **Monthly deltas:** compare `(gbifid, lastinterpreted)` with the previous snapshot to report
  what really changed, including which records disappeared (deletions and takedowns,
  matching the "handled at the next rebuild" decision).
- **Corrections as data:** repairs write `record id → corrected value` rows (event-id dates,
  later others) to `ref/corrections`. They are applied when the training view is built, so
  every future snapshot is corrected automatically and the raw layer stays immutable.
- **Live records as a daily-partitioned append log** (iNaturalist plus registry-live GBIF
  datasets), deduplicated against snapshot rows by record id at read time. Once a monthly
  snapshot contains a record, its live copy can be dropped.
- **The work store as a cache:** jobs attach Parquet views (DuckDB reads them directly), write
  their outputs as Parquet, and keep DuckDB only for scratch. A lost machine rebuilds from the
  bucket in minutes, not hours. Several regions can run at once.

## 3. Proposed ingestion cadence

| Cadence | Job | Notes |
|---|---|---|
| every 15–30 min | **one** iNaturalist live stream for the whole coverage area (not per region), plus registry-live GBIF datasets | appends to `norm/observations/source=live`; each region's publish takes its cells |
| every 30 min | publish recent aggregates per region | already in place; only the index and recent tables change |
| daily | NOAA signals; repairs (30-min budget); new names → crosswalk; hourly-count cache for the current year | |
| monthly | GBIF snapshot (one pass, coverage area) → delta report → baselines, gates, conditions, nowcasts, hourly models → static products | the authoritative reconciliation |
| yearly | eBird EOD release lands through the snapshot | bigger baseline change; worth a review |

**Freshness targets** (reported per source in `/health` and the worker status):

| Source | Target |
|---|---|
| iNaturalist | ≤ 30 min ingest; users see records after the 24 h OPEN delay |
| Happywhale and other live datasets | the publisher's lag + 30 min |
| NOAA | ≤ 1 day |
| everything else via GBIF | ≤ 1 month |

Alert when a source misses its target twice.

## 4. Order of work

1. **Freshness metrics** (small): per-source latest record and ingest time, in `/health`
   and the worker status.
2. **Coverage-area snapshot pass** to partitioned Parquet (biggest saving, enables everything
   else), with the monthly delta report.
3. **Corrections layer;** repairs write corrections instead of updating rows.
4. **Live log** for the coverage area (one iNaturalist stream).
5. **Work store as cache:** jobs read Parquet views; derived outputs to Parquet.

## 5. Questions for the owner

1. **Coverage area:** commit to "all of California" as the first coverage area (one snapshot
   pass, ~80–100 M records, a few GB of Parquet), or stay region by region?
2. **Durable storage before hosting:** is a private bucket for the lake (no compute) acceptable
   now, so data survives this environment? Without it, the reference store and lake still live
   only on the session's disk.
3. **Freshness targets:** are the targets above right? In particular, is a monthly lag for
   non-iNaturalist GBIF data acceptable until an eBird feed exists?
4. **Deletions:** is "removed at the next monthly snapshot" fast enough, or should we ask
   about an iNaturalist account for its deletions feed?

## 6. Decisions and status (2026-11-13)

Owner decisions: California is the first coverage area; a private bucket for the lake is
approved (not yet created); the iNaturalist account doesn't help with deletions (its
deletions feed lists only the signed-in user's own observations), so deletions use an
existence check (below).

| Step | Status | Where |
|---|---|---|
| 1. Freshness metrics | done | `pipeline/freshness.py`; `freshness` table in bundles; `/health` |
| 2. Coverage snapshot pass, delta, reconciliation | done | `pipeline/coverage.py`; `wildlife-radar-pipeline coverage-snapshot`; the `snapshot` job of regions with `coverage:` |
| 3. Corrections layer | covered for now | event ids in `lake/ref` are re-applied after each ingest; no separate table |
| 4. Live log | done | `pipeline/livelog.py`; the `live` job of regions with `coverage:` |
| 5. Work store as cache | later | |
| Retention (old snapshots, old live-log days) | done 2026-11-14 | `wildlife-radar lake-prune` (keeps the newest two complete snapshots; drops live days past 67 days and older than the newest snapshot, here and in the bucket) |
| Bucket sync of `lake/ref` and `lake/norm` | done 2026-11-14 | `wildlife-radar lake-sync`; the worker pulls `ref/` and the live log before a tick and pushes after; see [`../deploy.md`](../deploy.md) |

**Deletions, as built.**
- *Monthly:* when a region ingests a new snapshot, GBIF rows from earlier ingests that the
  snapshot no longer has are deleted (deleted or re-licensed at the source, withdrawn
  datasets). Rows of live datasets pulled after the snapshot date are kept until the next
  snapshot can confirm them. `delta.json` reports per-dataset additions, removals and changes.
- *Daily:* iNaturalist observations from the last 7 days in the live log are requested again
  by id (200 per request, ~350 requests a day for California); ids that don't come back are
  listed in `deleted/` and removed from every region's store on its next load.
- Not planned (owner, 2026-11-13): a weekly 60-day check or a manual tombstone list. The
  licenses (CC0/CC BY/CC BY-NC) don't require deletions to propagate; the check exists for
  privacy changes (observations made private) and good citizenship, and the products are
  aggregates. Older deletions are removed when GBIF's monthly snapshot drops them. Revisit
  if a takedown request ever arrives.

**Cadence.** The live job pulls the coverage area at most every 25 minutes; regions load from
the log on every tick. Recommended once hosted: ingest every 15 min, publish every 30–60 min
while the OPEN delay is 24 h.
