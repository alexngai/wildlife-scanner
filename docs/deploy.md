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
        ▲ GBIF, iNaturalist, NOAA                    │ static products (CDN), next step
```

## Parts

| Part | Command | Where |
|---|---|---|
| Worker | `wildlife-radar worker --region R --db /data/R.duckdb --lake /data/lake --ingest-snapshots --every 30` | fly.io app with a volume (`deploy/fly.worker.toml`) |
| Publish bucket | `region=<id>/version=<v>/{serving.duckdb, manifest.json}` and `region=<id>/CURRENT` | Cloudflare R2 |
| API | `wildlife-radar serve --region R --cache-dir /tmp/bundles` with `WILDLIFE_RADAR_PUBLISH_URL` set | fly.io app, auto-stop (`deploy/fly.api.toml`) |

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

## Configuration

| Variable | Used by | Value |
|---|---|---|
| `WILDLIFE_RADAR_PUBLISH_URL` | worker, API | `s3://<bucket>[/prefix]`, or a local folder |
| `AWS_ENDPOINT_URL_S3` | worker, API | `https://<account id>.r2.cloudflarestorage.com` (secret) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | worker, API | R2 API token key pair (secrets) |
| `AWS_REGION` | worker, API | `auto` (R2) |
| `WILDLIFE_RADAR_CORS_ORIGINS` | API | the frontend's origin(s), comma-separated; none by default |
| `WILDLIFE_RADAR_SOURCE_URL` | API | link to the running source (AGPL §13) |
| `WILDLIFE_RADAR_USER_AGENT` | worker | operator contact for outside APIs (optional; never the owner's personal details in the repo) |

Credentials only ever go in fly secrets (`fly secrets set …`), never in `fly.toml` or the
repository. Give the API a **read-only** R2 token and the worker a read-write one, both scoped
to the publish bucket.

## Bringing it up (when ready)

1. **R2:** create a bucket (e.g. `wildlife-radar-publish`) and two API tokens scoped to it:
   Object Read for the API, Object Read & Write for the worker.
2. **Worker:**
   ```bash
   fly apps create <worker app>
   fly volumes create worker_data --app <worker app> --region lax --size 40
   fly secrets set --app <worker app> AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… AWS_ENDPOINT_URL_S3=…
   fly deploy --config deploy/fly.worker.toml --dockerfile deploy/Dockerfile --app <worker app>
   ```
   The first tick ingests the newest GBIF snapshot and builds everything: about 1.5 h for San
   Diego. Later ticks take minutes.
3. **API:**
   ```bash
   fly apps create <api app>
   fly secrets set --app <api app> AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… AWS_ENDPOINT_URL_S3=…
   fly deploy --config deploy/fly.api.toml --dockerfile deploy/Dockerfile --app <api app>
   ```
4. Check `https://<api app>.fly.dev/health`: it names the bundle version it serves.

## Running it locally

The same commands work with a folder in place of the bucket:

```bash
uv run wildlife-radar worker --region sandiego --db data/sd.duckdb --lake data/lake \
    --publish-url data/bucket --once
WILDLIFE_RADAR_PUBLISH_URL=data/bucket uv run wildlife-radar serve --region sandiego
```

The image:

```bash
docker build -f deploy/Dockerfile -t wildlife-radar .
docker run -p 8080:8080 -v "$PWD/data/bucket:/bucket:ro" -e WILDLIFE_RADAR_PUBLISH_URL=/bucket \
    wildlife-radar wildlife-radar serve --region sandiego --host 0.0.0.0 --port 8080
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

- **Static products** (search index, calendars, place lists, maps) for the CDN: next.
- **One API for several regions:** `serve` serves one region today. A second region means a
  second process or app until the API routes requests by coordinates (data-platform.md §5).
- **Raw, norm, ref and derived layers stay on the worker's volume.** Only `publish` is in R2. If the
  volume is lost, the worker rebuilds from scratch (~1.5 h per region), and the API keeps
  serving the last version meanwhile.
- **Every tick republishes the whole bundle**, even when only the live aggregates changed.
  Splitting the small live tables into their own file would make pushes and cold starts
  cheaper; measure bundle sizes on real data first.
