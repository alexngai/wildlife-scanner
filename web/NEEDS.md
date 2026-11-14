# Requests from the web app to the data & API session

The web track doesn't edit `src/`, the pipeline or the formats. These are the changes the
app would like, each with the reason. Newest at the bottom; the data session decides.

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
