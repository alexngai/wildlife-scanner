# Bringing up wildlifescanner.com

A step-by-step guide for the owner, in the order things depend on each other. Nothing here has
been created yet. You click through the Cloudflare and fly.io dashboards; no credentials go to
any coding session.

| Address | What | Where |
|---|---|---|
| `https://wildlifescanner.com` | the web app (`www.` redirects here) | Cloudflare Pages |
| `https://data.wildlifescanner.com` | the published data (static products) | Cloudflare R2, public custom domain |
| `https://api.wildlifescanner.com` | the API (forecasts, recent sightings) | fly.io, auto-stopping |
| (private) | the worker that rebuilds and publishes the data | fly.io, with a volume |

The worker and API steps are the data pipeline's ([`docs/deploy.md`](../docs/deploy.md),
*Bringing it up*). This guide is the overall checklist and says when to do them. **Order matters:**
the app goes live before the first data, because the worker only publishes a format the live app
says it reads.

## 1. Put the domain on Cloudflare

R2 custom domains and Pages custom domains need the domain's DNS on Cloudflare.

1. Cloudflare dashboard → **Add a domain** → `wildlifescanner.com` → the **Free** plan.
2. If the domain is registered elsewhere, change its nameservers at your registrar to the two
   Cloudflare gives you. (If you bought it through Cloudflare Registrar, it's already done.)
3. Wait until the domain shows **Active** (minutes to a few hours).
4. **SSL/TLS → Overview:** set the mode to **Full (strict)**.

## 2. The data bucket (R2)

The private lake bucket, `wildlife-scanner-lake`, already exists. This step creates the public
one.

1. **R2 Object Storage → Create bucket**: name `wildlife-scanner-publish`, location *Automatic*.
   R2 needs a payment method on the account, even within the free tier.
2. Bucket → **Settings → Custom Domains → Connect Domain**: `data.wildlifescanner.com`. Leave
   the `r2.dev` address **disabled**: it's rate-limited and not meant for real traffic.
3. Bucket → **Settings → CORS Policy → Add/Edit**, and paste:

   ```json
   [
     {
       "AllowedOrigins": [
         "https://wildlifescanner.com",
         "https://www.wildlifescanner.com",
         "http://localhost:5173"
       ],
       "AllowedMethods": ["GET", "HEAD"],
       "AllowedHeaders": ["*"],
       "MaxAgeSeconds": 86400
     }
   ]
   ```

   The app reads the data from this other address, so without this rule browsers refuse it.
   `localhost:5173` lets a developer point a local copy of the app at the live data. Remove it
   if you'd rather not allow that.
4. **API tokens** for the worker (read and write) and the API (read only): follow
   [`docs/deploy.md`](../docs/deploy.md) → *Bringing it up* → **1. Buckets and R2 tokens**. Paste
   them only into fly.io secrets, never into the repository or a chat.

## 3. The web app (Pages): goes live first

The worker only publishes a data format that the live app lists at
`https://wildlifescanner.com/compat.json`, and it refuses to publish if it can't reach that
address. So the app goes up **before** the first data. Until then it shows the region as "not
available".

1. **Workers & Pages → Create → Pages → Connect to Git**, and pick `alexngai/wildlife-scanner`.
2. Build settings:

   | Setting | Value |
   |---|---|
   | Production branch | `main` |
   | Framework preset | *None* |
   | Root directory | `web` |
   | Build command | `npm ci && npm run build:production` |
   | Build output directory | `dist` |
   | Environment variable | `NODE_VERSION` = `22` |

   `build:production` builds the app and writes
   [`deploy/config.production.json`](deploy/config.production.json) as the site's
   `/config.json`. That file points at the three addresses above.
3. **Save and Deploy.** The first build takes a few minutes.
4. Project → **Custom domains → Set up a custom domain**: `wildlifescanner.com`, then again
   for `www.wildlifescanner.com`.
5. Send `www` to the main address: **Rules → Redirect Rules → Create rule**:
   - when *Hostname equals* `www.wildlifescanner.com`;
   - redirect *Dynamic* to `concat("https://wildlifescanner.com", http.request.uri.path)`;
   - status **301**, with *Preserve query string* on.
6. Check that `https://wildlifescanner.com/compat.json` shows `{"formats":[4],"current":4}`.

Preview deployments (one per branch or pull request, at `*.pages.dev`) use the same production
data and API. Those reject the preview addresses (CORS), so previews show the app but no data.
That's expected; production is unaffected.

## 4. The worker, the API and the first data

Follow [`docs/deploy.md`](../docs/deploy.md) → *Bringing it up*:

- **2. Worker** (`wildlife-scanner-worker`): its first run builds San Diego, then Monterey Bay
  (1–2 hours each), and publishes each one once the app lists the format.
- **3. API** (`wildlife-scanner-api`): its settings (the allowed origins and the source link)
  are already in `deploy/fly.api.toml`. For `api.wildlifescanner.com`, add the CNAME record that
  `fly certs add` prints in Cloudflare → **DNS → Records**, with **Proxy status: DNS only** (grey
  cloud), so fly.io can issue the certificate.
- **4. First data** (optional): seed the bucket with versions that are already built, so the
  site has data before the worker's first run ends.

Until the first publish, the API answers 503 for each region and the app says the region isn't
available yet.

## 5. Check it

| Check | Expect |
|---|---|
| `https://wildlifescanner.com` | the region list, then search, maps, places |
| `https://wildlifescanner.com/compat.json` | `{"formats":[4],"current":4}` |
| `https://api.wildlifescanner.com/health` | each region's version and data freshness |
| `https://data.wildlifescanner.com/region=sandiego/CURRENT` | the same version as `/health` |
| A species page → **Today vs usual** | a coloured map, or "no daily factors are modelled yet" |
| About page | sources and licences listed (from the API) |

From a terminal, the data is served compressed and allowed for the site:

```bash
curl -sI -H 'Origin: https://wildlifescanner.com' -H 'Accept-Encoding: br, gzip' \
  "https://data.wildlifescanner.com/region=montereybay/CURRENT"
# expect: access-control-allow-origin: https://wildlifescanner.com, cache-control: no-cache
curl -sI https://wildlifescanner.com | grep -i content-security-policy
```

## 6. After launch

- **Rate limiting on the API.** Once it works, switch the `api` record to **Proxied** (orange
  cloud). If the certificate then fails to renew, use fly's DNS validation record.
  - Add **Security → WAF → Rate limiting rules**: e.g. at most 60 requests per 10 seconds per
    IP to `api.wildlifescanner.com`.
  - The batch forecast takes up to 2,000 cells per call, so this matters most there.
- **Watch freshness.** `https://api.wildlifescanner.com/health` reports each source's age.
  The app tells open pages when new data is published.
- **Rollback.** Point a region's `CURRENT` at an older version ([`docs/deploy.md`](../docs/deploy.md)).

## Changing the data format without breaking the site

The app reads the formats listed in `src/products/formats.ts` and publishes them at
`/compat.json`. For a breaking format change N → N+1:

1. **App first.** Add an adapter so the app reads N and N+1, make N+1 current, and deploy (merge
   to `main`). Check `https://wildlifescanner.com/compat.json` lists N+1.
2. **Then the data.** Publish format N+1. The worker and `push-publish` fetch `/compat.json`
   first and refuse a format the live app doesn't list.
3. **Clean up later.** Once no published version is format N any more, drop N's adapter.

If data ever arrives in a format the open app doesn't read (e.g. a tab left open across a
release), the page asks the reader to reload. The new app then reads it.

## If you change hosts

The Content-Security-Policy in [`public/_headers`](public/_headers) lists every host the app
loads from: the data and API addresses, the map layers and base map, and iNaturalist's photo
host. A different data or API address, or new map layers, need it updated too.
`tests/headers.test.ts` fails if they disagree.
