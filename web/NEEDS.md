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
