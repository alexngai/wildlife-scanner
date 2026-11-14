# Requests from the web app to the data & API session

The web track doesn't edit `src/`, the pipeline or the formats. These are the changes the
app would like, each with the reason. Newest at the bottom; the data session decides.

**Status (2026-11-14):** §9–15 are done in static format 3 and the API (data branch 92e394f,
contract in `docs/design/static-products.md`), and the app uses them. §14's failure is fixed
there (f3e15a2). Format 4 (24f8aff) then moved photos to an id plus URL templates in the
index, to shrink `taxa.json`; the app reads that.

## 1. Awareness-mode species: numbers are still published (policy)

**What:** tier-2 / `mode: "awareness"` taxa still carry numbers:

- in the **static maps**: `p`, `region_p` and `ref.p` in tier-2 segments (e.g. the demo's
  `raritas-orientalis` has monthly `p` per landscape cell);
- in the **API**: `/species/{id}/forecast` and `/species/{id}/calendar` return `p`,
  `p_level0` and monthly `p` and `seasonal_index` for awareness taxa.

**Why:** the policy is "awareness-mode species show presence, never numbers", and
the place-list `awareness_message` says "no location or timing details are given". The app
hides these numbers (presence only, no calendar or forecast), but the files and responses
are public, so anyone can read them.

**Suggested:**
- tier ≥ 2 segments publish presence only (e.g. `p` as 0/1, or a `present` cell list) with
  no `region_p`, no `ref` and no per-month values;
- the API answers awareness taxa's forecast and calendar like withheld ones (404), or
  without numbers.

## 2. A region list in the static products

**What:** a small `regions.json` at the publish root: `[{id, name, bbox}]`, or the
`CURRENT` paths.

**Why:** without the API, the app can't discover regions and needs them in its config
(`regions` in `/config.json`). With the file, a static-only deployment lists regions itself.

## 3. Publication delays and tier rules in `index.json`

**What:** e.g. `"policy": {"tiers": {"0": {"min_delay_hours": 24, "granularity": "hour"},
"1": {...}, "2": {...}}}`.

**Why:** the app must show publication delays. It mirrors `policy/tiers.py`
(24 h / 7 d / 30 d) in `web/src/lib/policy.ts`, which will drift if the tiers change.

## 4. Bug: `push-publish` with a relative `--publish-url`

`wildlife-radar push-publish --publish-url data/bucket` uploads the files, then fails when
pruning:

```
ValueError: '/home/…/data/bucket/region=socal/CURRENT' is not in the subpath of 'data/bucket'
```

The folder store's `root` should be resolved (`Path(root).resolve()`). An absolute path
works.

## 5. Typed responses for the remaining endpoints

**What:** Pydantic response models for `/species/{id}/timing`, `/regions`, `/sources` and
`/places`.

**Why:** these return untyped `dict`s in `openapi.json`, so the app's generated types can't
cover them. They're hand-typed in `web/src/api/client.ts` for now.

## 6. A richer demo for local development

**What:** have `wildlife-radar demo` (or a `demo --full`) also produce:
- a gated Level-1 condition model with drivers;
- a timed index (hourly forecast and `/timing`);
- some live-source recent records (`/nearby/recent`, `picking_up`);
- common names.

**Why:** today the demo yields Level 0 only: no drivers, flat hours, no recent activity,
and scientific names only. So the "why", hourly and "right now" panels can only be
exercised with the app's synthetic fixtures (`web/tests/fixtures`), not end to end.

## 7. Note: "new for you" is computed in the browser

The app doesn't send the life list to `/places/{id}/lists?life_list=…` or `/nearby`. It
computes "new for you" from the published lists and a life list kept in `localStorage`, so
the list never leaves the device. If the API's `new_for_you` ever draws on more than the
published lists, say so, and the app can offer it as an opt-in.

## 8. `taxa.json` lists only the species visible on the publish date

**What:** build the search index from every taxon that has a published map, not
`list_taxa(today)`. Give each entry its strictest tier and mode over the year, or per-season
modes.

**Why:** a species withheld only this week (e.g. in a protected season) is missing from
search all week, although its map file is published for its other weeks and opens by direct
link. Each entry's `tier` and `mode` also describe only the publish day, so a species that
becomes awareness-only later in the year is labelled `forecast` in search.

## 9. Place files hold all 52 weeks (2.2 MB each with real data)

**What:** split each place file by week (e.g. `places/<id>/w<NN>.json`, plus a small
`places/<id>.json` with `place`, `taxa`, `groups` and the week paths), or publish the current
and next few weeks separately.

**Why:** measured on a Monterey Bay build (4 places, 1,333 taxa per place). A place file is
about 2.2 MB, or 560 KB gzipped, and 2.37 MB of that is the `weeks` array. The page shows one
week at a time. On a phone at about 1.6 Mbps, the place page took 16 s uncompressed and should
take about 4 s gzipped. One week would be about 45 KB.

## 10. Every page loads all of `index.json` to find one map path

**What:** move each taxon's map path into its `taxa.json` entry (`map: "static/maps/…"`), or
split `maps` out of `index.json` into its own file.

**Why:** with 4,853 taxa, `index.json` is 379 KB, or 114 KB gzipped, and nearly all of it is the
`maps` table. A species page needs one entry but has to load all of it before it can request
the map. Search already loads `taxa.json` (835 KB, 145 KB gzipped), so a path there costs
almost nothing more.

## 11. Small per-taxon season summary in `taxa.json`

**What:** a regional seasonal profile per taxon, for example `season: [0-9 × 52]` (each week's
regional value as a 0–9 level, or null when withheld), only for tiers below 2.

**Why:** search results and lists could show a tiny "when it's around" ribbon without
fetching a map per result. It is region-wide and already published (`region_p`), so nothing
finer is revealed. Until then the app fetches the map files for the first few results.

## 12. Inconsistent capitalisation of common names

Real data mixes "coyote brush" and "coastal sagewort" with "European Searocket" and "Alkali
Heath" in the same list. The app shows names as published. Normalising at ingest, or
preferring a source with consistent case, would read better.

## 13. A day's forecast for many cells in one call

**What:** e.g. `GET /species/{id}/forecast/map?date=…&cells=…` (or for the whole map), returning each
cell's `p`, `p_level0` and drivers for that day.

**Why:** the species map's "Today's conditions" overlay compares the day's forecast with the usual
chance in the week's 12 highest cells. Today that's 12 calls to `/species/{id}/forecast`, one per
cell (about 0.2 s each locally). One call would let the overlay cover every cell and cost the API
less.

## 14. Monterey Bay build: the signals and conditions stages fail

Seen in a full `run publish --region montereybay` (not app code, for the data session):
- `signals`: `ConnectorError: No Predictions data was found. Please make sure the Datum input is
  valid.` (tide predictions);
- `conditions`: `CatalogException: Table with name signal_daily does not exist`, which follows
  from the first error;
- so `nowcast` and the final `publish` were skipped. Running `publish --region montereybay`
  separately worked. Without conditions, every forecast is Level 0, with the note "no condition
  model has passed its backtest gate".

## 15. A representative photo per taxon, chosen at publish

**What:** add an optional `photo` to each entry in `taxa.json` (the app already reads it; see
`TaxonPhoto` in `web/src/products/types.ts`):

```json
"photo": {
  "url": "https://inaturalist-open-data.s3.amazonaws.com/photos/12345678/square.jpg",
  "url_medium": "https://inaturalist-open-data.s3.amazonaws.com/photos/12345678/medium.jpg",
  "license": "cc-by",
  "attribution": "(c) A. Photographer, some rights reserved (CC BY)",
  "source": "iNaturalist",
  "source_url": "https://www.inaturalist.org/photos/12345678"
}
```

`url` and `url_medium` may instead be paths relative to the region root (like map paths), if
the images are copied into the bucket. Leave `photo` out (or `null`) when nothing qualifies.

**How (prototyped against Monterey Bay: 40 of the 40 most-recorded taxa got a photo):**
1. Find the iNaturalist taxon: the ingest crosswalk may already hold its id; otherwise
   `GET /v1/taxa?q=<scientific name>&is_active=true` and require an exact name match.
2. `GET /v1/taxa/{id}` (or `/v1/taxa?id=a,b,c…`, about 30 per call) and walk `taxon_photos` in
   order. Take the first photo whose `license_code` is one of `cc0`, `cc-by`, `cc-by-sa`,
   `cc-by-nc`, `cc-by-nc-sa`. **Skip "all rights reserved" (`license_code: null`) and the ND
   licences.** The default photo is often all rights reserved (e.g. California Scrub-Jay's), so
   don't just take `default_photo`.
3. `url` is the photo's `square` size, and `url_medium` is the same URL with `/medium.`.
   Openly licensed photos are on `inaturalist-open-data.s3.amazonaws.com` (AWS Open Data).
4. Keep `attribution` verbatim and record the licence code.

**Be a good API citizen:** about 1 request per second, an identifying User-Agent with no personal
details, and cache results between publishes. Photos rarely change, so refresh them weekly or
when a taxon is new. Please check iNaturalist's current API guidance (I couldn't open it from
here).

**Decision (owner): hotlink, don't store, for now.** Publish the absolute
`inaturalist-open-data.s3.amazonaws.com` URLs: `url` = `…/photos/<id>/square.<ext>` (about 6 KB)
and `url_medium` = `…/small.<ext>` (about 20 KB). Visitors' browsers load them from AWS, which the
About page's privacy section mentions. Copying them into the bucket later would take about 30 KB
per taxon, at most about 150 MB per region (measured on Monterey), and needs no app change:
relative paths already work.

**App behaviour:** it re-checks the licence and URL (https or a bucket path only), shows the
credit with every photo (visible on the species page, under "Photo credits" in lists), loads
lazily with no referrer, and falls back to a group placeholder if an image fails to load, e.g.
if it moved or was deleted after publishing.
