# wildlife-radar web app

The browser front end: React + Vite + TypeScript (strict), MapLibre GL for maps, H3 cells
drawn with `h3-js`. It reads the **static products** (format 4,
[`docs/design/static-products.md`](../docs/design/static-products.md)) and, when configured,
the **API** (daily forecasts, hourly timing, recent activity). It builds to a static site for
Cloudflare Pages. AGPL-3.0, like the rest of the repository.

## Pages

| Route | What it shows | Data |
|---|---|---|
| `/` | region picker | `/config.json` regions (or API `/regions`) → each region's `index.json` |
| `/r/:region` | species search with a 52-week season ribbon per result (from `taxa.json`'s `season`, no map files); "Where to go": places compared within one effort group by likely species per outing (week slider, map, ranked list; loaded on request); places, "near me" | `taxa.json`, `index.json`, place headers and week files (hotspots) |
| `/r/:region/species/:id` | week map + slider (with play), coloured by chance or by chance compared with the wider area; a third view, "Today vs usual", colours every cell by the day's forecast against its usual chance (one `/species/{id}/forecast/map` call) with the factors summarised; cell details on hover/tap; named places on the map; the map as a table (keyboard alternative to tapping); calendar (region or a tapped cell / place), what the number means, confidence, daily forecast + drivers, hourly timing, licence | species map file (path from `taxa.json`); API `forecast`, `forecast/map`, `forecast/hourly`, `timing` |
| `/r/:region/places/:id` | one effort group at a time (busiest first) with tabs for most likely / special here / peaking now / new for you (top 10, then "Show all"); awareness species; picking up now / reported recently with data delay | place file; API `places/{id}/recent` |
| `/r/:region/nearby` | geolocation (on request, rounded to ~100 m) → closest places, lists, recent activity | `index.json`; API `nearby`, `nearby/recent` |
| `/about` | AGPL source link, non-commercial notice, licences, privacy | API `/sources` |

## Look and feel

One token system in `src/styles/app.css` (colour, type, spacing, radii, shadows), redefined for
dark mode. The theme follows the system unless the viewer picks Light or Dark in the header
(saved in their browser). Pages share one structure: a page header (back link, title, chips),
then cards with a heading and optional actions. Navigation is in the header on wide screens and
a bottom tab bar on phones. Icons are inline SVG (`src/components/Icons.tsx`).

## Policy in the UI

Data arrives policy-filtered, and the app adds display rules on top. See
`src/lib/policy.ts` and the tests.

- Never derive anything finer than what's published: values are shown per published cell and
  period, with no interpolation or smoothing, and percentages are rounded.
- Unknown and withheld species look identical ("not available"), whether they're missing
  from `index.json` or the API answers 404.
- Awareness-mode species (tier ≥ 2) show presence only: no numbers, calendar, timing or
  forecast. Numbers in awareness segments of the static files are ignored (see
  [NEEDS.md](NEEDS.md) §1).
- Confidence: `i` cells are drawn hatched as "not enough data", never as zero, and low
  confidence is paler.
- "Compared with the wider area" divides a cell's published value by the published
  reference value (`ref.p`, its parent cell or the region) for the same period. Both numbers
  are already in the file, so nothing finer is derived.
- Publication delays are shown with recent activity (`data_through`) and per species.
- Season ribbons use each species' published region-wide values (`region_p`) and are scaled to the
  species' own peak, so they show timing, not how common species are against each other. Withheld
  weeks are empty, awareness weeks a flat band, and awareness species get none.
- "Likely species per outing" adds up the published chances in a place's top list for one effort
  group. Places are only compared within a group, because chances from different methods don't
  mix.
- Species photos are chosen when the data is published ([NEEDS.md](NEEDS.md) §15). `taxa.json`
  gives each photo's id, extension, licence and credit; `index.json`'s `photos` holds the URL
  templates (format 4). The app checks the id and extension before filling a template. Only openly
  licensed ones are shown (CC0, BY, BY-SA, BY-NC, BY-NC-SA; never "all rights reserved" or ND),
  always with their credit. An image that fails to load falls back to a group placeholder.
- Licence and attribution appear with every map and list, alongside a non-commercial notice
  and the source link.

## Develop

Node ≥ 20. All commands run from `web/`.

```bash
npm ci
npm run dev          # http://localhost:5173
```

The dev server serves a local **folder bucket** at `/data` (default `../data/bucket`;
override with `WR_BUCKET_DIR`). It proxies `/api` to the local API (default
`http://127.0.0.1:8000`; override with `WR_API_URL`). To make synthetic data with the CLI,
from the repo root:

```bash
export UV_SYSTEM_CERTS=1; unset UV_NATIVE_TLS
uv run wildlife-radar demo
uv run wildlife-radar publish --db data/demo.duckdb --out data/lake/publish
uv run wildlife-radar push-publish --db data/demo.duckdb --publish-url "$PWD/data/bucket"   # absolute path: NEEDS.md §4
WILDLIFE_RADAR_PUBLISH_URL="$PWD/data/bucket" uv run wildlife-radar serve --region socal --port 8000
```

Or point the dev server at the test fixtures, with no Python needed:
`WR_BUCKET_DIR=tests/fixtures/bucket npm run dev`. Then open `/r/testland`.

| Script | |
|---|---|
| `npm run lint` | ESLint (typescript-eslint strict, react-hooks, jsx-a11y) |
| `npm run format` | Prettier (120 columns); CI runs `format:check` |
| `npm run typecheck` | `tsc -b` |
| `npm test` | Vitest unit and component tests (jsdom; MapLibre is mocked) |
| `npm run e2e` | Playwright smoke test against the production build (`vite preview`), mobile + desktop; run `npx vite build` first |
| `npm run gen:api` | regenerate `src/api/schema.d.ts` from `api/openapi.json` |
| `npm run fixtures` | regenerate the synthetic fixtures in `tests/fixtures/` |

To refresh the API types, save the running API's schema to `api/openapi.json`, then
regenerate:

```bash
curl -s localhost:8000/openapi.json > api/openapi.json && npm run gen:api
```

CI (`.github/workflows/web.yml`) checks that both generated files are up to date.

**Test data is synthetic only.** `scripts/make-fixtures.mjs` invents a region ("Testland"),
species and numbers. It covers:
- a seasonal tier change (weeks served by a coarse, awareness-only monthly segment);
- withheld weeks;
- insufficient cells;
- an awareness-only species.

## Configure a deployment

`/config.json` is read at startup (no rebuild needed). Every field is optional:

```json
{
  "staticBase": "https://static.example.org",
  "apiBase": "https://api.example.org",
  "regions": ["sandiego", "montereybay"],
  "basemap": { "light": "https://…/style.json", "dark": "https://…/style.json", "attribution": "…" },
  "layers": [{ "id": "satellite", "name": "Satellite", "kind": "base", "type": "raster", "tiles": ["https://…/{z}/{x}/{y}.jpg"], "attribution": "…" }],
  "sourceUrl": "https://github.com/alexngai/wildlife-radar"
}
```

- `staticBase`: the publish bucket's public URL. It contains `region=<id>/CURRENT`.
- `apiBase`: `""` turns off the API panels; they then say the live service isn't connected.
  Set `WILDLIFE_RADAR_CORS_ORIGINS` on the API to the site's origin.
- `regions`: empty means ask the API's `/regions`.
- `layers`: extra base maps and overlays offered in every map's **Layers** picker. Each is
  `{id, name, kind: "base" | "overlay", type: "raster" | "hillshade", tiles, tileSize?, maxzoom?,
  encoding?, opacity?, attribution}`. `[]` turns the picker down to Map / Plain. The defaults
  need no key:
  - Satellite: EOX Sentinel-2 cloudless 2021 (CC BY-NC-SA 4.0, fine for this non-commercial
    project; replace it for any commercial use);
  - Terrain shading: Mapzen terrain tiles on AWS Open Data (`raster-dem`, terrarium encoding);
  - Ocean depth: GEBCO's WMS (`GEBCO_LATEST`), drawn at 55% under the data.

  Overlays draw between the base map and the data. The viewer's choice, including a data-opacity
  slider, is remembered in their browser only.
- `basemap`: defaults to OpenFreeMap (no API key; attribution comes with the style). Use
  `"none"` for a plain background. If the basemap can't load, the map falls back to a plain
  background and the data still shows.

Build-time defaults are also available: `VITE_STATIC_BASE`, `VITE_API_BASE`,
`VITE_REGIONS`, `VITE_BASEMAP_STYLE`, `VITE_BASEMAP_STYLE_DARK` and `VITE_SOURCE_URL`.

**Cloudflare Pages** (for the hosting track, which sets this up later; nothing is created
here):
- build command: `cd web && npm ci && npm run build`;
- output directory: `web/dist`;
- `public/_redirects` gives SPA routing, and `public/_headers` sets security and cache headers.

## Layout

```
src/products/   static-products client + format-2 types
src/api/        API client + generated OpenAPI types
src/lib/        pure logic: weeks, maps (segments, calendar, GeoJSON), lists, policy, search, geo, life list
src/components/ map, slider, calendar, lists, API panels, status views
src/pages/      routes
tests/          fixtures, fixture fetch, component tests
e2e/            Playwright smoke test
```
