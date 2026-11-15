# Handoff: state of the project and open threads (2026-11-12)

For the next working session. Start here, then read the files it points to.

## 1. Where things stand

- **Branch** `claude/brave-newton-ui859d`. **PR** [#1](https://github.com/alexngai/wildlife-scanner/pull/1) was merged on 2026-11-13 (up to `534b5d3`). `main` has since been merged back into the branch without rewriting it. Later commits (deploy, Monterey Bay, static format 2, hourly factors, …) are not on `main` yet; open a new PR only when the owner asks.
- **Web app:** a parallel session builds it on `claude/web-app` (React + Vite + TypeScript, MapLibre). It owns `web/` and `.github/workflows/web.yml`; don't edit them. Its change requests go in `web/NEEDS.md` on that branch.
- **Contracts:** `docs/design/static-products.md` (static formats, with a changelog; bump `format` for breaking changes) and the API's `/openapi.json`.
- **Done:**
  - research and design (`docs/research/00–07`, `docs/design/*`);
  - Phases 0–2;
  - Phase 3: daily condition signals, Level 1–2 models with gates, hypothesis scorecard, recent-sightings forecasts for every OPEN species;
  - the data platform's first steps: a job graph, audit-gated policy-filtered bundles, a live iNaturalist ingest, and an API that serves bundles.
- **Results so far:** `docs/research/08`, `09`, `10` (real San Diego data) and `11` (Monterey Bay, the second region). Read 10 and 11 first.
- **Test suite:** `uv run pytest` (≈252 tests, ~110 s); `uv run ruff check .`; `uv run ruff format --check .`.

## 2. Standing decisions and constraints (from the project owner)

- **Exclusively non-commercial**, free and educational. **Code is AGPL-3.0**; the operator is an individual (`docs/design/licensing.md`).
- **Any species, both query modes** (species-first and place-first). Start with Southern California, design for global. Profiles are generated from metadata plus community review.
- **Hosting:** simple and cheap; free tiers first, a small monthly budget is fine. Suggested: Cloudflare R2/Pages for static products, a small fly.io container for the API.
- **Freshness:** users must see fresh data.
- **Multi-region** from the start.
- **Takedowns:** less stringent for now (handled at the next full rebuild).
- **Data partners:** eBird/Cornell and IUCN partnerships are on hold. eBird data comes only via the GBIF EOD dataset (CC BY 4.0).
- **Privacy:** never put the owner's name, email or other personal details into requests to outside services. The default User-Agent is `wildlife-scanner/<version>` with no contact. Operators set `WILDLIFE_SCANNER_USER_AGENT`.
- **No third-party data in the repository.** Data, caches, drafts and audit files go in the git-ignored `data/`.
- **Sensitive species:** never publish fine-scale details. Tier assignment fails closed, and LLMs never set or lower statuses or tiers.
- **Git:** develop on the branch above. **Don't open PRs unless asked.** Commit messages end with the session attribution lines. No model identifiers in commits, code or docs: the extraction model is configured at runtime (`--model` or `WILDLIFE_SCANNER_EXTRACTION_MODEL`).

## 3. Environment

- **Before running uv:** `export UV_SYSTEM_CERTS=1; unset UV_NATIVE_TLS`, then `uv sync --all-extras`.
- **The `wildlife-scanner` cloud environment allows these hosts:**
  - Wikidata (`www.wikidata.org`, `query.wikidata.org`)
  - `en.wikipedia.org` (but see §4.3)
  - `api.inaturalist.org`, `api.gbif.org`
  - `zenodo.org`, `extensions.duckdb.org`
  - `api.checklistbank.org`, `verifier.globalnames.org`, `www.marinespecies.org`
  - `api.tidesandcurrents.noaa.gov`

  The GBIF snapshot bucket (`gbif-open-data-us-east-1.s3.us-east-1.amazonaws.com`) was reachable too.
- **No secrets are configured.** Two things are pending from the owner: a contact User-Agent (Wikipedia requires one) and an Anthropic API key (for LLM extraction).

## 4. Rebuilding a region's store (San Diego; Monterey Bay is the same with `--region montereybay --db data/mb.duckdb`)

Data doesn't survive between sessions. To rebuild it (about 1.5 h, mostly downloads):

```bash
uv run wildlife-scanner run publish --region sandiego --db data/sd.duckdb --lake data/lake --ingest-snapshots
uv run wildlife-scanner serve --region sandiego --bundle-dir data/lake/publish
```

- `--ingest-snapshots` makes the `snapshot` job find the newest complete monthly GBIF snapshot, extract the region with HTTPS range requests and ingest it (~45 min for San Diego; staging goes under `data/lake/raw/` and is deleted afterwards unless `--keep-staging`). Pin a snapshot with `--snapshot-date 2026-11-01`. The step-by-step scripts in `tools/` still work.
- The job rechecks weekly. When no newer snapshot exists it reports `unchanged` and keeps its version, so nothing downstream reruns. Records deleted upstream stay until a full rebuild.

- `regions/sandiego/` (like `socal` and `montereybay`) inherits the `california` pack's curated statuses and dataset registry. The registry carries the kelp-survey date fix, so it must be used.
- The first `run publish` takes ~45 min:
  - crosswalk ~12 min (9.7k names)
  - re-dating ~10 min
  - tiers ~10 min (iNaturalist statuses)
  - conditions ~5 min
  - nowcast ~10 min
  - publish ~2 min

  Reruns redo only stale jobs.
- `TetrapodTraits_1.0.0.csv` (CC BY 4.0) goes in `data/traits/`. URL in `profilegen/traits.py`.

## 5. Open threads (suggested order)

**Owner's order (2026-11-12):** Deployment code locally first (accounts exist on fly.io and
Cloudflare; hook them up later), with the housekeeping quick fixes; then a second region; then
4, 5, 6. LLM extraction (3) is deferred. Policy questions (7) are with the owner.

1. **Deployment** (`docs/design/data-platform.md` §5, §8 steps 3–5):
   - lake on Cloudflare R2 (raw/norm/ref/derived/publish);
   - the API container on fly.io, auto-stopping, loading `publish/<region>/CURRENT`;
   - schedule `run publish` every 30 min (live), signals daily, full rebuild monthly;
   - static products for the TypeScript app: PMTiles maps, place lists, calendars, a name-search index.

   The owner has fly.io and Cloudflare accounts. **Hosting is deferred** until the app is more
   mature: no fly.io or Cloudflare resources and no credential requests.
   - **Done locally** ([`deploy.md`](deploy.md)): an object-store layer (folder or S3/R2),
     `worker` (scheduled ticks, audit-gated push, pruning), `push-publish`,
     `serve --bundle-url` (mirrors `CURRENT`), opt-in CORS, `deploy/Dockerfile` (builds and
     serves a bundle from a folder bucket, checked end to end), fly configs for the API and
     the worker.
   - **Static products** (done locally): `publish` writes a search index, H3 maps per taxon
     and year, and place lists, content-addressed so live publishes rebuild only the index
     (see `deploy.md`). `BaselineQueries.species_maps` batches a year of maps in one query
     per tier and matches `species_map` exactly.
   - **Later:** a multi-region API, splitting the live tables out of the bundle, measuring
     static sizes on real data, and syncing the other lake layers.
2. **A second region** to prove multi-region (e.g. Northern California or the Pacific Northwest region pack). Then move identities and the status cache to a **global reference store** shared by regions; they are per store today.
   *Done 2026-11-12* (`docs/research/11`): Monterey Bay published end to end; shared
   reference store (`lake/ref`); multi-region API and worker. Open: kelp-survey repairs
   continue daily (3,741 events left, GBIF rate limits); static map format and build speed
   (5.3 GB, ~2.5 h first build).
3. **LLM extraction live run + calibration** (`profilegen generate --extract`, `profilegen calibrate`). Blocked on the User-Agent contact and API key (§3). Score per-field accuracy against TetrapodTraits before trusting any extracted field.
4. **Profile revisions from the scorecard** (`docs/research/10` §1). *Done 2026-11-12: direction
   claims withdrawn for both, and the scorecard flags them (`scorecard --review`).*
   - leopard shark: water temperature is negative *within* season (the aggregation is seasonal);
   - marbled godwit: higher daily lows → more records;
   - mark contradicted directions for review.
5. **Timed records** (iNaturalist API keeps observation times): diel priors, tide stage, hours after sunset (white seabass profile). The GBIF snapshot has dates only.
   *First step done 2026-11-12:* the `timed` job builds time-of-day and tide-stage indices
   for profiled species from iNaturalist hourly counts (`conditions/timed.py`; no records
   downloaded), judges the profiles' intra-day claims (`timed_scorecard`), publishes them for
   open and generalized taxa only, and serves `/species/{id}/timing`. Next: real-data results
   and folding the indices into daily forecasts as availability terms.
6. **More live sources for nowcasts:** an eBird feed (partnership), and the GBIF API for frequently publishing datasets. Nowcast features must come only from live sources, in training and serving alike.
   *GBIF part done 2026-11-12:* datasets marked `live: true` in the dataset registry are
   pulled by the `live` job from the GBIF API and count as live sources in training and
   serving. The California registry marks 30 Happywhale North Pacific datasets (CC BY-NC;
   ~400 Monterey Bay records in the first six weeks of autumn 2026, mostly humpbacks).
7. **Policy questions for the owner:**
   - Could OPEN's 24 h delay be shorter for common species?
   - CITES Appendix II maps to COARSE (strict; would hide e.g. hummingbirds if iNaturalist reported CITES statuses).
   - Review the medium audit findings ("threatened elsewhere").
   - Humpback whales are COARSE in Monterey Bay (DPS listings, iNaturalist obscuring), so
     Happywhale humpback sightings never reach users. A whale-watching exception would be the
     owner's call (`docs/research/11` §5).
8. **Housekeeping:**
   - Report the kelp-forest dataset's placeholder dates to its publisher (GBIF dataset `154d6192…`, ~21 M records dated 2023-11-30).
   - ~~Cache `SignalLookup` in the forecast service~~ (done: once per service and signal set).
   - ~~Automate monthly ingests~~ (done: `run … --ingest-snapshots`; see §4).
   - 35 names are unresolved and 67 taxa fail their status lookups (fail closed to COARSE; mostly plants and insects).

## 6. Lessons that cost time (don't relearn them)

- **One DuckDB file per region is single-writer.** Long jobs lock readers. Serving reads bundles; run read-only queries only when no job is running.
- **GBIF search is slow at deep offsets** (~40 s/page). Partition by a facet (e.g. `eventId`) and page each part from offset 0.
- **External APIs reset connections.** `get_json(..., retries=N)` retries 429, 5xx and resets. Failed status lookups fail closed to COARSE: safe, but they hide species until retried.
- **Taxonomies disagree:**
  - GBIF's backbone mapped honey mesquite to screwbean, so match against the **Catalogue of Life** (what snapshots use).
  - Wikidata synonym links are sometimes wrong. They may raise protection, but never verify ids or merge taxa.
  - Follow an inactive iNaturalist concept only if its own name matches.
- **GBIF rate-limits long paging by volume** (HTTP 429 after ~1,000 pages even at 4/s). Budget and checkpoint any long GBIF job; never assume one run finishes.
- **Background tool commands stop after 2 h.** Start long pipeline runs detached (`nohup … &`) and follow the log.
- **Check every policy result end to end on real data.** The audit caught OPEN listed species three times: skipped curated statuses, a renamed species, and fresh records with obscured geoprivacy. `publish` is gated on it; keep it that way.
- **Gates need a fair reference.** Compare Level 1 with a *recalibrated* Level 0, require a practical effect (≥0.5%), and train only on features that exist at serving time.
- **Survey data quirks:** placeholder dates, absences recorded only for some taxa, campaign dates that aren't seasonality. `annotate-datasets` reports date spikes.
