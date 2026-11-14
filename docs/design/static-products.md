# Static products: file formats (format 4)

**This is a contract** with the web app (`web/`, branch `claude/web-app`), as is the API's
`/openapi.json`. Breaking changes bump `format` (every file carries it), are listed below, and
the web session is told. Additions (new fields, new endpoints) don't bump it; clients ignore
fields they don't know.

## Changelog

| Date | Change | Breaking |
|---|---|---|
| 2026-11-14 | **Format 4.** A `taxa.json` photo is `{id, ext, license, attribution}`; build its URLs from `index.json`'s `photos` templates (San Diego: `taxa.json` 3.7 → 2.6 MB, 525 → 458 KB gzipped). Every file says `"format": 4`; nothing else changed. | yes (format 3 → 4) |
| 2026-11-14 | **Format 3.** `index.json` no longer has `maps`: each `taxa.json` entry carries its `map` path. Place files are a header (`places/<place>.<key>.json`: names, groups, item fields, and `weeks`, a list of 52 paths) plus one file per week (`places/<place>.<key>/wNN.json`). Every file says `"format": 3`. | yes (format 2 → 3) |
| 2026-11-14 | `taxa.json` entries may carry `season` (52 levels 0–9, OPEN/GENERALIZED only) and `photo` (an openly licensed iNaturalist photo, hotlinked, with its credit). Common names are title-cased when a source gives them all in lowercase. | no (additions) |
| 2026-11-14 | API: `GET /species/{id}/forecast/map?date=&cells=` (the day's forecast for every cell of the week's map, or for up to 2,000 listed cells, in one call). | no (addition) |
| 2026-11-13 | **Format 2.** Maps: one file per species for any year (ISO weeks), `segments` of cells × periods integer matrices (`p_scale`), lift via `ref`; paths `static/maps/<taxon>.<key>.json`. Places: names and groups once, list items as rows (`item_fields`); paths `static/places/<place>.<key>.json`. Index: `maps` is `{taxon: path}`, places carry `file`, `lat`, `lon`. | yes (format 1 → 2) |
| 2026-11-13 | API: `/health` regions carry `freshness` (per source: `last_update`, `newest_record`, `age_hours`, `target_hours`, `status` ok/stale/unknown); a region's `status` is `stale` when any source misses its target. | no (addition; `status` may now be `stale`) |
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
<base>/region=<id>/static/places/<place>.<key>.json  one place: names, groups, week paths
<base>/region=<id>/static/places/<place>.<key>/wNN.json  one week of that place's lists
```

Read `CURRENT` (no-cache), then `index.json`. Every other path is in the index or in
`taxa.json` (map paths), relative to `region=<id>/`. Maps and place files are content-addressed
(`key` changes when the content does), so they can be cached forever.

### `index.json`

```json
{
  "format": 4,
  "region": {"id": "montereybay", "name": "Monterey Bay", "bbox": [-122.55, 35.95, -121.1, 37.2]},
  "version": "20261113T090000",
  "baseline": {"model_version": "baseline-v1", "built_at": "2026-11-12T10:21:53+00:00"},
  "year_basis": 2026,
  "p_scale": 100000,
  "taxa": "version=20261113T090000/static/taxa.json",
  "photos": {"image": "https://inaturalist-open-data.s3.amazonaws.com/photos/{id}/{size}.{ext}",
             "page": "https://www.inaturalist.org/photos/{id}",
             "sizes": {"thumb": "square", "medium": "small"}, "source": "iNaturalist"},
  "places": {"point-lobos": {"name": "Point Lobos", "kind": "park", "lat": 36.518,
             "lon": -121.942, "file": "static/places/point-lobos.9c1d….json"}}
}
```

### `taxa.json`

A list of `{id, scientific_name, common_name, aliases, group, tier, mode, records, map,
season, photo}`, most recorded first: enough for a client-side name search and for list rows.
`mode` is `forecast` (tiers 0–1) or `awareness` (tier 2: show presence, not numbers).

```json
{"id": "aphelocoma-californica", "scientific_name": "Aphelocoma californica",
 "common_name": "California Scrub-Jay", "aliases": [], "group": "birds", "tier": 0,
 "mode": "forecast", "records": 41234,
 "map": "static/maps/aphelocoma-californica.5b0e….json",
 "season": [8, 8, 8, "…", 9, 8],
 "photo": {"id": 12345678, "ext": "jpg", "license": "cc-by-nc",
           "attribution": "(c) A. Photographer, some rights reserved (CC BY-NC)"}}
```

- **map**: the species' map file (absent when nothing is mapped).
- **season**: the regional season, one level 0–9 per ISO week, relative to the species' own
  peak week (9 = its best weeks, 0 = no records then); `null` for weeks withheld. Derived from
  the map's `region_p`, so it reveals nothing finer. Only OPEN and GENERALIZED species, and
  only weekly segments.
- **photo**: the first photo in iNaturalist's order for the taxon whose licence is CC0, CC BY,
  CC BY-SA, CC BY-NC or CC BY-NC-SA (never all rights reserved or no-derivatives), served from
  iNaturalist's open-data bucket (hotlinked). Build the URLs from `index.json`'s `photos`:
  the thumbnail is `image` with `size` = `sizes.thumb` (75 px square), the larger image
  `size` = `sizes.medium` (240 px), and the credit link `page`, each with this photo's `id`
  and `ext`. `ext` is kept as iNaturalist stores it (`jpg`, `jpeg`, `JPG`, `png`, …) and is
  empty for some old uploads, whose URL ends in `square.`. Show `attribution` (verbatim) with
  the photo. Absent when no photo qualifies; withheld taxa have no entry at all.
- **common_name**: as the source writes it, title-cased when the source gives it all in
  lowercase ("coyote brush" → "Coyote Brush").

## Species maps (`static/maps/<taxon>.<key>.json`)

One file per species covers the whole year by **ISO week**. Estimates are per week of the
year, so the same file serves any year. Map a date to its ISO week (1–52; fold week 53 into
52).

```json
{
  "format": 4,
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

## Place lists (`static/places/<place>.<key>.json` and `…/wNN.json`)

A header with what every week shares, and one small file per ISO week. A page loads the
header and the week it shows.

```json
{
  "format": 4, "place": {"place_id": "point-lobos", "…": "…"}, "year_basis": 2026,
  "p_scale": 100000,
  "item_fields": ["taxon_id", "p", "lift_x100", "seasonal_index_x100", "confidence", "res"],
  "resolutions_km": [1.41, 9.85],
  "awareness_message": "…",
  "taxa": {"enhydra-lutris": {"scientific_name": "…", "common_name": "Sea Otter", "group": "mammals"}},
  "groups": {"birds:checklist": {"taxon_group": "birds", "effort_class": "checklist",
             "label": "…", "method": "birding_checklist", "license": {"…": "…"}}},
  "weeks": ["static/places/point-lobos.9c1d…/w01.json", "…", "static/places/point-lobos.9c1d…/w52.json"]
}
```

A week file:

```json
{"format": 4, "week": 1,
 "groups": {"birds:checklist": {"most_likely": [["sitta-carolinensis", 4120, 180, 95, "h", 0]],
                                "special_here": ["…"], "peaking_now": ["…"]}},
 "awareness": ["enhydra-lutris"], "area_fallback": []}
```

- `weeks[w - 1]` is the path of ISO week `w`'s file.
- List items are rows in `item_fields` order:
  - `p / p_scale` is the chance per outing;
  - `lift_x100 / 100` and `seasonal_index_x100 / 100` are the ratios;
  - confidence is `h`/`m`/`l`/`i`;
  - `res` indexes `resolutions_km` (larger means a coarser area was used).
- Names come from the header's `taxa`, and group labels, methods and licenses from its
  `groups`, each stored once for all weeks.
- `awareness` lists sensitive species present at landscape scale, shown with
  `awareness_message` and no numbers.
- `new_for_you` needs a life list, so it comes from the API.

## Sizes (Monterey Bay, 4,866 taxa)

| | Format 1 | Format 2 | Format 3–4 |
|---|---|---|---|
| All species maps | 5.3 GB (two years) | 256 MB (50 MB gzipped), one file per species | same as format 2 |
| Largest map (western scrub-jay) | ~1 MB (239 KB gzipped) | 166 KB (56 KB gzipped) | same |
| One place's weekly lists | 11.3 MB | 2.2 MB (534 KB gzipped) | header 162 KB (34 KB gzipped) + one week 38 KB (10 KB gzipped) |
| Index | | 379 KB (114 KB gzipped) | a few KB (map paths moved to `taxa.json`) |

Format 1 stored a row per cell and week with repeated ids and floats, and full list items
with names. Format 2 stores ids and names once and integers in matrices or short rows.

## What stays in the API

Daily forecasts (conditions, recent sightings), times of day and tides, and anything
personal (life lists) need the API: they change daily or depend on the user.
