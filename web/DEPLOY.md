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

The worker and API steps are the data pipeline's ([`docs/deploy.md`](../docs/deploy.md)). This
guide says when to do them.

## 1. Put the domain on Cloudflare

R2 custom domains and Pages custom domains need the domain's DNS on Cloudflare.

1. Cloudflare dashboard → **Add a domain** → `wildlifescanner.com` → the **Free** plan.
2. If the domain is registered elsewhere, change its nameservers at your registrar to the two
   Cloudflare gives you. (If you bought it through Cloudflare Registrar, it's already done.)
3. Wait until the domain shows **Active** (minutes to a few hours).
4. **SSL/TLS → Overview:** set the mode to **Full (strict)**.

## 2. The data bucket (R2)

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
4. **API tokens** for the worker (read and write) and the API (read only), scoped to this
   bucket: follow [`docs/deploy.md`](../docs/deploy.md) ("Bringing it up", step 1). Paste them
   only into fly.io secrets, never into the repository or a chat.

## 3. The worker: first data

Follow [`docs/deploy.md`](../docs/deploy.md), step 2, with
`WILDLIFE_SCANNER_PUBLISH_URL=s3://wildlife-scanner-publish`. The first run builds every
region from scratch and pushes it to the bucket: about 1.5 hours per region.

When it finishes, check in a browser:

- `https://data.wildlifescanner.com/region=montereybay/CURRENT` shows a version, e.g.
  `20261116T…`;
- `https://data.wildlifescanner.com/region=montereybay/version=<that version>/static/index.json`
  shows `"format": 4`.

## 4. The API

Follow [`docs/deploy.md`](../docs/deploy.md), step 3, with these settings:

| Setting | Value |
|---|---|
| `WILDLIFE_SCANNER_PUBLISH_URL` | `s3://wildlife-scanner-publish` |
| `WILDLIFE_SCANNER_CORS_ORIGINS` | `https://wildlifescanner.com,https://www.wildlifescanner.com` |
| `WILDLIFE_SCANNER_SOURCE_URL` | `https://github.com/alexngai/wildlife-scanner` |

Then give it its address:

1. `fly certs add api.wildlifescanner.com -a <api app>`. It prints the DNS records it needs.
2. Cloudflare → **DNS → Records → Add record**: **CNAME** `api` → `<api app>.fly.dev`, with
   **Proxy status: DNS only** (grey cloud), so fly.io can issue the certificate. If it asks for
   an `_acme-challenge` CNAME too, add that one as well.
3. `fly certs show api.wildlifescanner.com -a <api app>` until it says the certificate is
   issued. Then `https://api.wildlifescanner.com/health` names the version it serves.

## 5. The web app (Pages)

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

Preview deployments (one per branch or pull request, at `*.pages.dev`) use the same production
data and API. Those reject the preview addresses (CORS), so previews show the app but no data.
That's expected; production is unaffected.

## 6. Check it

| Check | Expect |
|---|---|
| `https://wildlifescanner.com` | the region list, then search, maps, places |
| `https://wildlifescanner.com/compat.json` | `{"formats":[4],"current":4}` |
| `https://api.wildlifescanner.com/health` | status ok, and the version it serves |
| A species page → **Today vs usual** | a coloured map, or "no daily factors are modelled yet" |
| About page | sources and licences listed (from the API) |

From a terminal, the data is served compressed and allowed for the site:

```bash
curl -sI -H 'Origin: https://wildlifescanner.com' -H 'Accept-Encoding: br, gzip' \
  "https://data.wildlifescanner.com/region=montereybay/CURRENT"
# expect: access-control-allow-origin: https://wildlifescanner.com, cache-control: no-cache
curl -sI https://wildlifescanner.com | grep -i content-security-policy
```

## 7. After launch

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
2. **Then the data.** Publish format N+1. The publisher can fetch `/compat.json` and refuse a
   format the live app doesn't list.
3. **Clean up later.** Once no published version is format N any more, drop N's adapter.

If data ever arrives in a format the open app doesn't read (e.g. a tab left open across a
release), the page asks the reader to reload. The new app then reads it.

## If you change hosts

The Content-Security-Policy in [`public/_headers`](public/_headers) lists every host the app
loads from: the data and API addresses, the map layers and base map, and iNaturalist's photo
host. A different data or API address, or new map layers, need it updated too.
`tests/headers.test.ts` fails if they disagree.
