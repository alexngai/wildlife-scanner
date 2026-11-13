# Static products: file formats (format 2)

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
{"format": 2, "place": {"place_id": "point-lobos", "…": "…"}, "year_basis": 2026,
 "weeks": [ {"week": 1, "groups": [ {"group": "birds:checklist", "most_likely": ["…"],
             "special_here": ["…"], "peaking_now": ["…"]} ], "awareness": ["…"]}, "…" ]}
```

`weeks[w - 1]` is ISO week `w`, in the API's `PlaceLists` shape without `date` and without
`new_for_you` (that needs a life list; ask the API).

## Sizes (Monterey Bay, 4,866 taxa)

See `docs/research/11-second-region-monterey-2026-11.md` §3. Format 1 stored a row per cell
and week with repeated ids and floats, and one file per year. Format 2 stores ids once and
integers in a matrix.

## What stays in the API

Daily forecasts (conditions, recent sightings), times of day and tides, and anything
personal (life lists) need the API: they change daily or depend on the user.
