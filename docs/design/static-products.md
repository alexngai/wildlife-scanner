# Static products: file formats (format 2)

**This is a contract** with the web app (`web/`, branch `claude/web-app`), as is the API's
`/openapi.json`. Breaking changes bump `format` (every file carries it), are listed below, and
the web session is told. Additions (new fields, new endpoints) don't bump it; clients ignore
fields they don't know.

## Changelog

| Date | Change | Breaking |
|---|---|---|
| 2026-11-13 | **Format 2.** Maps: one file per species for any year (ISO weeks), `segments` of cells × periods integer matrices (`p_scale`), lift via `ref`; paths `static/maps/<taxon>.<key>.json`. Places: names and groups once, list items as rows (`item_fields`); paths `static/places/<place>.<key>.json`. Index: `maps` is `{taxon: path}`, places carry `file`, `lat`, `lon`. | yes (format 1 → 2) |
| 2026-11-13 | API: `GET /species/{id}/forecast/hourly` (hourly spread of the daily forecast, OPEN species only); `GET /species/{id}/timing` (descriptive time-of-day/tide indices, OPEN and GENERALIZED). | no (additions) |
| 2026-11-12 | API: several regions per process. `GET /regions`; `region=` on `/taxa`, `/taxa/{id}`, `/species/{id}/map` (required when more than one region is served); `/health` lists `regions` (single-region fields kept at the top level). | no for one region |
| 2026-11-12 | Format 1 (first static products): per species and year, rows of `[cell, p, lift, seasonal_index, confidence]`. | — |

What the frontend reads from the CDN. Everything here is already policy-filtered: withheld taxa
are absent, sensitive taxa appear only at their tier's resolution and time granularity, and
there are no individual records. Built by `publish` (`src/wildlife_radar/pipeline/static.py`).

## Finding the files

```
<base>/region=<id>/CURRENT                         one line: the live version
<base>/region=<id>/version=<v>/static/index.json   entry point (small; changes every publish)
<base>/region=<id>/version=<v>/static/taxa.json    search index
<base>/region=<id>/static/maps/<taxon>.<key>.json  one species' year of maps
<base>/region=<id>/static/places/<place>.<key>.json  one place's weekly lists
```

Read `CURRENT` (no-cache), then `index.json`; every other path is in the index, relative to
`region=<id>/`. Maps and place files are content-addressed (`key` changes when the content
does), so they can be cached forever.

### `index.json`

```json
{
  "format": 2,
  "region": {"id": "montereybay", "name": "Monterey Bay", "bbox": [-122.55, 35.95, -121.1, 37.2]},
  "version": "20261113T090000",
  "baseline": {"model_version": "baseline-v1", "built_at": "2026-11-12T10:21:53+00:00"},
  "year_basis": 2026,
  "p_scale": 100000,
  "taxa": "version=20261113T090000/static/taxa.json",
  "maps": {"enhydra-lutris": "static/maps/enhydra-lutris.3f2a….json", "…": "…"},
  "places": {"point-lobos": {"name": "Point Lobos", "kind": "park", "lat": 36.518,
             "lon": -121.942, "file": "static/places/point-lobos.9c1d….json"}}
}
```

### `taxa.json`

A list of `{id, scientific_name, common_name, aliases, group, tier, mode, records}`, most
recorded first: enough for a client-side name search. `mode` is `forecast` (tiers 0–1) or
`awareness` (tier 2: show presence, not numbers).

## Species maps (`static/maps/<taxon>.<key>.json`)

One file per species covers the whole year by **ISO week**. Estimates are per week of the
year, so the same file serves any year. Map a date to its ISO week (1–52; fold week 53 into
52).

```json
{
  "format": 2,
  "taxon": {"taxon_id": "falco-sparverius", "common_name": "American Kestrel", "tier": 0, "…": "…"},
  "effort_group": "birds:checklist", "method": "birding_checklist",
  "label": "…what the number means…", "license": {"…": "…"},
  "year_basis": 2026, "p_scale": 100000,
  "segments": [
    {
      "tier": 0, "granularity": "week", "resolution": 7, "resolution_km": 1.41,
      "periods": [1, 2, "…", 52],
      "cells": ["872830828ffffff", "…"],
      "p": [[1234, 1301, "…"], "…"],
      "confidence": ["hhhhmm…", "…"],
      "ref": {"resolution": 3, "p": {"832830fffffffff": [2210, "…"]}},
      "region_p": [880, "…"]
    }
  ]
}
```

- **segments**: runs of weeks sharing a policy tier. Usually one. A species whose
  protection rises in some season has several, possibly at different resolutions. Weeks in
  no segment are withheld.
- **granularity**: `week` (periods are ISO weeks) or `month` (periods are months 1–12; for
  COARSE species). Find the segment whose `periods` contain your week (or month).
- **cells / p**: `p[i][j]` is the chance per outing (see `label` and `method`) in `cells[i]`
  during `periods[j]`, as an integer: divide by `p_scale`. `null` means no estimate there
  then.
- **confidence[i][j]**: one character per period: `h`igh, `m`edium, `l`ow, `i`nsufficient,
  `-` none. Show `i` cells as "not enough data", not as zero.

Derived values (no need to store them):

| Value | How |
|---|---|
| Lift ("how special is this cell") | `p / ref.p[parent][j]`, where `parent = cellToParent(cell, ref.resolution)`; when `ref.resolution` is null the key is `"region"` |
| Seasonal index of a cell | `p[i][j] / mean(p[i])` over the periods |
| Calendar at a point | the row of the cell containing the point (`latLngToCell(lat, lon, resolution)`) |
| Regional calendar | `region_p` |
| Best weeks at a place | sort the cell's row |

With h3-js, a week's map is `segment.cells.map((c, i) => ({hex: c, p: segment.p[i][j] / p_scale}))`,
ready for deck.gl's `H3HexagonLayer` or polygons from `cellToBoundary`.

## Place lists (`static/places/<place>.<key>.json`)

```json
{
  "format": 2, "place": {"place_id": "point-lobos", "…": "…"}, "year_basis": 2026,
  "p_scale": 100000,
  "item_fields": ["taxon_id", "p", "lift_x100", "seasonal_index_x100", "confidence", "res"],
  "resolutions_km": [1.41, 9.85],
  "awareness_message": "…",
  "taxa": {"enhydra-lutris": {"scientific_name": "…", "common_name": "Sea Otter", "group": "mammals"}},
  "groups": {"birds:checklist": {"taxon_group": "birds", "effort_class": "checklist",
             "label": "…", "method": "birding_checklist", "license": {"…": "…"}}},
  "weeks": [
    {"week": 1,
     "groups": {"birds:checklist": {"most_likely": [["sitta-carolinensis", 4120, 180, 95, "h", 0]],
                                    "special_here": ["…"], "peaking_now": ["…"]}},
     "awareness": ["enhydra-lutris"], "area_fallback": []}
  ]
}
```

- `weeks[w - 1]` is ISO week `w`.
- List items are rows in `item_fields` order:
  - `p / p_scale` is the chance per outing;
  - `lift_x100 / 100` and `seasonal_index_x100 / 100` are the ratios;
  - confidence is `h`/`m`/`l`/`i`;
  - `res` indexes `resolutions_km` (larger means a coarser area was used).
- Names come from `taxa`, and group labels, methods and licenses from `groups`, each stored once.
- `awareness` lists sensitive species present at landscape scale, shown with
  `awareness_message` and no numbers.
- `new_for_you` needs a life list, so it comes from the API.

## Sizes (Monterey Bay, 4,866 taxa)

| | Format 1 | Format 2 |
|---|---|---|
| All species maps | 5.3 GB (two years) | 256 MB (50 MB gzipped), one file per species |
| Largest map (western scrub-jay) | ~1 MB (239 KB gzipped) | 166 KB (56 KB gzipped) |
| One place's weekly lists (Point Lobos, 37 effort groups) | 11.3 MB | 2.2 MB (534 KB gzipped) |

Format 1 stored a row per cell and week with repeated ids and floats, and full list items
with names. Format 2 stores ids and names once and integers in matrices or short rows.

## What stays in the API

Daily forecasts (conditions, recent sightings), times of day and tides, and anything
personal (life lists) need the API: they change daily or depend on the user.
