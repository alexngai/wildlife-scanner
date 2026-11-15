# Deploying: R2 + fly.io

How the pieces fit together, and the steps to bring them up. Nothing here has been created yet:
the code and configs are tested locally, against a folder standing in for the bucket and with
a mocked S3 API. Design background: [`design/data-platform.md`](design/data-platform.md) §5.

```
             every 30 min                        CURRENT pointer               on request
 ┌──────────────────────────┐  push   ┌──────────────────────────┐  pull  ┌──────────────────┐
 │ worker (fly.io + volume) │───────▶ │  R2: publish bucket      │──────▶ │ API (fly.io,     │
 │ runs stale jobs → audit  │         │  region=<id>/CURRENT     │        │ auto-stop)       │
 │ → publish → push         │         │  region=<id>/version=<v>/│        │ mirrors CURRENT  │
 └──────────────────────────┘         └──────────────────────────┘        └──────────────────┘
        ▲ GBIF, iNaturalist, NOAA                    │ static products → frontend (CDN)
```

## Parts

| Part | Command | Where |
|---|---|---|
| Worker | `wildlife-scanner worker --region R1,R2 --db '/data/{region}.duckdb' --lake /data/lake --ingest-snapshots --every 30` | fly.io app with a volume (`deploy/fly.worker.toml`) |
| Publish bucket | `region=<id>/version=<v>/{serving.duckdb, manifest.json}` and `region=<id>/CURRENT` | Cloudflare R2 |
| API | `wildlife-scanner serve --region R1,R2 --cache-dir /tmp/bundles` with `WILDLIFE_SCANNER_PUBLISH_URL` set | fly.io app, auto-stop (`deploy/fly.api.toml`) |
| Static products | `version=<v>/static/{index,taxa}.json`, `static/maps/…`, `static/places/…` | same bucket, served by R2's public domain / CDN |

- **The worker** ticks every 30 minutes. Each tick runs only stale jobs (`Job.max_age`):
  - live iNaturalist records: every tick;
  - NOAA signals: daily;
  - the GBIF snapshot check: weekly, with a full rebuild when a new monthly snapshot appears;
  - model refits: monthly.

  Then it pushes the new version and prunes old ones (keeps 6). Publishing is **gated on the
  tier audit**: a blocked publish fails the job, the bucket keeps the last audited version, and
  the next tick retries. The last tick's summary is in `/data/lake/worker/region=<id>.json`.
- **The bucket:** the worker uploads every file of a version, and only then the `CURRENT`
  pointer. So anyone reading `CURRENT` finds a complete version. Versioned files are marked
  immutable. `CURRENT` is marked `no-cache`.
- **The API** downloads the current bundle at startup and checks `CURRENT` every 60 s. It swaps
  in a new version between requests. A cold start after auto-stop downloads the bundle before
  serving, so the first request after idle is slower.
- **Rollback:** point `CURRENT` at a kept version:
  - `fly ssh console -a <worker>`, then rewrite the pointer;
  - or upload a one-line `CURRENT` file with any S3 tool.

## Static products (for the frontend)

Built by `publish` from the finished bundle, through the same query layer as the API, before
`CURRENT` moves (`src/wildlife_scanner/pipeline/static.py`):

- `version=<v>/static/index.json`: the entry point. The frontend reads `CURRENT`, then this
  index, which lists every other file's path (relative to `region=<id>/`).
- `version=<v>/static/taxa.json`: search index (names, aliases, group, tier, records), each
  species' map path, a 52-week season summary and an openly licensed photo (hotlinked).
- `static/maps/<taxon>.<key>.json`: the species' year of maps by ISO week, as H3 cells × weeks
  matrices (weekly for openly mapped taxa, monthly at landscape scale for coarse ones). Weeks
  a taxon is withheld are absent. Withheld taxa are absent everywhere.
- `static/places/<place>.<key>.json` and `static/places/<place>.<key>/wNN.json`: a place's
  header (names, groups, week paths) and one file per week of lists.

The formats (currently format 4) are specified in
[`design/static-products.md`](design/static-products.md), which the web app relies on.

Maps and place lists are content-addressed, so a live publish rebuilds only the index and
search index. Only files whose inputs changed (a new baseline, a tier change) are regenerated
and uploaded. The bucket needs public read access (an R2 custom domain or `r2.dev`) for these
paths. Everything published is already policy-filtered. `--no-static` skips them.

## Several regions

- **One worker, several regions:** each tick runs the regions in turn. They share the volume and
  the **reference store** (`lake/ref`: name identities and raw iNaturalist taxon records), so a
  new region reuses what the others already resolved. Status lookups are still parsed and
  cached per region, because which statuses apply depends on the region's places.
- **Workers on several machines:** set `WILDLIFE_SCANNER_LAKE_URL` (or `--lake-url`) to a
  **private** bucket. Each tick then copies new reference parts both ways. The parts are
  immutable and uniquely named, so workers never conflict.
- **One API, several regions:** `serve --region a,b` opens each region's bundle on first use.
  - Point and place requests go to the smallest region that contains the point, or to the
    place's own region.
  - Taxon requests (`/taxa`, `/species/{id}/map`) take `region=`, which is required when more
    than one region is served.
  - `/regions` lists the regions, and `/health` reports each one.
  - A region with nothing published yet answers 503.
  - Two served regions may not share a place id.

## Configuration

| Variable | Used by | Value |
|---|---|---|
| `WILDLIFE_SCANNER_PUBLISH_URL` | worker, API | `s3://<bucket>[/prefix]`, or a local folder |
| `AWS_ENDPOINT_URL_S3` | worker, API | `https://<account id>.r2.cloudflarestorage.com` (secret) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | worker, API | R2 API token key pair (secrets) |
| `AWS_REGION` | worker, API | `auto` (R2) |
| `WILDLIFE_SCANNER_CORS_ORIGINS` | API | the frontend's origin(s), comma-separated; none by default |
| `WILDLIFE_SCANNER_SOURCE_URL` | API | link to the running source (AGPL §13) |
| `WILDLIFE_SCANNER_LAKE_URL` | worker | private bucket for the shared reference store (only with several worker machines) |
| `WILDLIFE_SCANNER_APP_COMPAT_URL` | worker, `push-publish` | the live app's `compat.json`; a version whose static format the app doesn't list isn't published |
| `WILDLIFE_SCANNER_USER_AGENT` | worker | operator contact for outside APIs (optional; never the owner's personal details in the repo) |

Credentials only ever go in fly secrets (`fly secrets set …`), never in `fly.toml` or the
repository. Give the API a **read-only** R2 token and the worker a read-write one, both scoped
to the publish bucket.

## Bringing it up (when ready)

Addresses: the app at `https://wildlifescanner.com` (Cloudflare Pages), the static products at
`https://data.wildlifescanner.com` (the publish bucket's custom domain) and the API at
`https://api.wildlifescanner.com` (fly.io). The Cloudflare zone, the publish bucket's public
domain and CORS, and Pages are in the web app's guide, [`web/DEPLOY.md`](../web/DEPLOY.md),
which is the overall checklist and links back here. This section covers the R2 tokens, the
worker, the API and the first data.

Deploy the app (with its `compat.json`) before the worker's first publish: the worker only
publishes a static format the live app lists, so until the app is up, its pushes wait and
retry each tick.

### 1. Buckets and R2 tokens

Two buckets:

| Bucket | Access | Holds |
|---|---|---|
| `wildlife-scanner-publish` | public read through `data.wildlifescanner.com` | published versions and static files |
| `wildlife-scanner-lake` | private | coverage tiles, live log, reference store (already filled) |

Create two tokens in the Cloudflare dashboard under **R2 → Manage API tokens → Create API
token**. Each gives an Access Key ID and a Secret Access Key, shown once:

- **worker:** permission *Object Read & Write*, applied to both buckets;
- **api:** permission *Object Read*, applied to `wildlife-scanner-publish` only.

The S3 endpoint for both is `https://<account id>.r2.cloudflarestorage.com` (on the R2 overview
page). Keep the values for the fly secrets below; they never go in a file or the repository.

### 2. Worker

```bash
fly apps create wildlife-scanner-worker
fly volumes create worker_data --app wildlife-scanner-worker --region lax --size 50
fly secrets set --app wildlife-scanner-worker \
    AWS_ACCESS_KEY_ID=<worker key id> AWS_SECRET_ACCESS_KEY=<worker secret> \
    AWS_ENDPOINT_URL_S3=https://<account id>.r2.cloudflarestorage.com
fly deploy --config deploy/fly.worker.toml --dockerfile deploy/Dockerfile
fly logs --app wildlife-scanner-worker
```

The first tick:

1. pulls the reference store, the live log and the California tiles (about 5 GB) from the lake
   bucket, instead of a 180 GB pass over GBIF;
2. builds San Diego, then Monterey Bay (1–2 hours each);
3. publishes each, if the tier audit passes and the app lists the format.

Later ticks take minutes. The last tick's summary is in
`/data/lake/worker/region=<id>.json` (`fly ssh console`). The worker also prunes old snapshots
and live-log days after each tick.

If a push fails with "the app … reads [...]", the app hasn't been deployed with that format
yet: deploy the app first; the next tick retries.

### 3. API

```bash
fly apps create wildlife-scanner-api
fly secrets set --app wildlife-scanner-api \
    AWS_ACCESS_KEY_ID=<api key id> AWS_SECRET_ACCESS_KEY=<api secret> \
    AWS_ENDPOINT_URL_S3=https://<account id>.r2.cloudflarestorage.com
fly deploy --config deploy/fly.api.toml --dockerfile deploy/Dockerfile
fly certs add api.wildlifescanner.com --app wildlife-scanner-api
```

`fly certs add` prints the DNS records to create in Cloudflare (a CNAME to
`wildlife-scanner-api.fly.dev`, set to **DNS only**, not proxied, so fly can issue the
certificate). `fly certs show api.wildlifescanner.com` reports when it's ready.

Until the worker's first publish, the API answers 503 for each region; the app shows that as
"no data yet".

### 4. First data

Either wait for the worker's first tick (above), or seed the bucket with versions that are
already built and audited:

```bash
wildlife-scanner push-publish --region montereybay --lake data/lake --publish-url s3://wildlife-scanner-publish
wildlife-scanner push-publish --region sandiego --lake data/lake --publish-url s3://wildlife-scanner-publish
```

The worker takes over from there: its own versions replace the seeded ones at its first
publish.

### 5. Checks

- `https://api.wildlifescanner.com/health` names each region's bundle version and data
  freshness.
- `https://data.wildlifescanner.com/region=sandiego/CURRENT` names the same version.
- The app's species and place pages load, with no CORS errors in the browser console.

## Running it locally

The same commands work with a folder in place of the bucket:

```bash
uv run wildlife-scanner worker --region sandiego --db data/sd.duckdb --lake data/lake \
    --publish-url data/bucket --once
WILDLIFE_SCANNER_PUBLISH_URL=data/bucket uv run wildlife-scanner serve --region sandiego
```

The image:

```bash
docker build -f deploy/Dockerfile -t wildlife-scanner .
docker run -p 8080:8080 -v "$PWD/data/bucket:/bucket:ro" -e WILDLIFE_SCANNER_PUBLISH_URL=/bucket \
    wildlife-scanner wildlife-scanner serve --region sandiego --host 0.0.0.0 --port 8080
```

The image starts as root only to give `/data` (a fly volume) to the `app` user, then runs the
command as `app`.

## Costs and sizing (to confirm against current fly.io and R2 pricing)

- **API:** one small shared-CPU machine, stopped when idle. Billed only while it runs.
- **Worker:** an always-on shared-CPU machine with 4 GB and a 40 GB volume. This is the largest
  fixed cost. To make it cheaper later, start a stopped machine on a schedule and run
  `worker --once`, which exits after one tick, so it's billed per tick. It would need an outside
  cron (a GitHub Actions schedule or a Cloudflare Worker cron calling the fly machines API),
  because fly's own machine schedules are at most hourly.
- **R2:** a few versions of a few hundred MB each; R2 doesn't charge egress.

## Not done yet

- **Static products on real data** (format 4, Monterey Bay, 4,866 species):
  - maps total 256 MB (50 MB gzipped), at most 166 KB per species;
  - a place page loads a 162 KB header (34 KB gzipped) and a 38 KB week (10 KB gzipped);
  - a full rebuild runs in parallel processes, and publishes between baseline rebuilds reuse
    the files.

  PMTiles was skipped: H3 cells render directly in the browser.
- **Raw, norm and derived layers stay on the worker's volume.** Only `publish` (and `ref`, with
  a lake bucket) is in R2. If the
  volume is lost, the worker rebuilds from scratch (~1.5 h per region), and the API keeps
  serving the last version meanwhile.
- **Every tick republishes the whole bundle**, even when only the live aggregates changed.
  Splitting the small live tables into their own file would make pushes and cold starts
  cheaper; measure bundle sizes on real data first.


## Private lake storage (R2)

The lake's shared layers (`lake/ref`, `lake/norm`) live in a private R2 bucket, so a new
machine restores them instead of re-downloading from GBIF.

- **Address:** `r2://<account id>/<bucket>/lake` (`--lake-url` or `WILDLIFE_SCANNER_LAKE_URL`).
- **Token:** a Cloudflare API token with *Account → Workers R2 Storage → Edit*, sent as a
  bearer header to `api.cloudflare.com`. In a cloud session it is a saved network secret that
  the proxy injects; elsewhere set `CLOUDFLARE_API_TOKEN`. A token limited to one bucket's
  objects is refused by the REST API.
- **Limits:** one upload is at most 300 MiB; coverage tiles are written in files of about
  200 MB, and `lake-sync --push` splits older, larger tiles first.

```sh
wildlife-scanner lake-sync --push            # upload new files (add --prune after splits)
wildlife-scanner lake-sync --pull            # restore everything (~5 GB for California)
wildlife-scanner lake-sync --pull --pull-prefix ref --pull-prefix norm/observations/source=live
```

Region work stores are not synced: they are rebuilt from the tiles and the live log.

After a new monthly snapshot is built, `wildlife-scanner lake-prune` (add `--dry-run` to see the
list) drops snapshots older than the previous one and live-log days the snapshot has
absorbed, locally and in the bucket. This keeps the bucket at about 12–15 GB for California.
