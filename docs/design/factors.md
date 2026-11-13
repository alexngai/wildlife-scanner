# Factors: time of day, moon, tides and other conditions in forecasts

One registry (`src/wildlife_radar/conditions/factors.py`) lists every environmental factor a
forecast can use, at two time scales. The scale decides how a factor is fitted and served.

| Scale | Factors | Fitted from | Enters the forecast as | Code |
|---|---|---|---|---|
| **day** | water temperature and its anomaly, the day's low tide and range, moon illumination and phase, air temperature, wind | dated records (GBIF snapshot + live) | Level-1 terms on the daily chance per outing | `conditions/levels.py` |
| **hour** | diel phase (day/dawn/dusk/night), hours since sunset, moonlight (moonlit/dark night), tide stage, tide height | iNaturalist hourly counts | multipliers that spread the daily chance over the hours | `conditions/hourly.py` |

Dated records can't see time of day, and the snapshot has dates only. So hourly factors come
from a second data source and are fitted separately; their output redistributes the daily
forecast without changing it.

## Which factors a species is tested for

- **Profile signals:** what the species' profile declares (with its shape, strength,
  expected direction or peak). Profile ids that name a factor differently are mapped
  (`astro.sun_altitude_deg` → `astro.diel_phase`).
- **Group defaults** (`GROUP_DEFAULTS`), so species without a profile are covered too:
  - fishes: diel phase, moonlight, tide stage
  - birds: diel phase, tide stage
  - mammals: diel phase, moonlight
  - mollusks: diel phase, tide stage
  - herps and insects: diel phase

  Tide factors are dropped where the region has no tide station.
- **Who gets hourly models:** profiled species plus the `timed_top` most-recorded openly
  mapped or generalized species (default 40) each month (`timed` job). Hourly counts are
  cached, so reruns fetch only the last two years.

Candidates are cheap; claims are not. A factor changes a forecast only through a model that
passed its gate.

## The hourly model

For each UTC hour: `k` iNaturalist records of the species and `n` records of its group (the
group stands in for when people are out looking). A penalized logistic model, aggregated
binomial (`y = k/n`, weight `n`):

```
logit P(a group record in hour h is this species) = b0 + Σ f(factor(h))
```

Categorical factors get one coefficient per level (the first level is the reference); tide
height gets a smooth (linear or optimum) term. Ridge penalties follow the profile's strength.

- **Gate:** trained on hours before the region's conditions split, tested on hours after.
  To be used, the model must beat "the same share of the group every hour" on held-out
  binomial log loss:
  - the lower end of a 90% day-block bootstrap interval is above zero;
  - the relative gain is at least 0.5%;
  - there are at least 50 training records and 20 test records.
- **Scorecard:** each factor is dropped in turn (held-out gain of keeping it, with an
  interval: supported / inconclusive / contradicted). The level with the largest effect is
  its **peak**. If a profile expects a different peak (a diel trait, or `at:` for hours after
  sunset), the term is flagged for review (`hourly_scorecard.review`).
- **Serving:** odds for an outing in hour `h` = daily odds × `exp(η(h) − log m̄)`. Here `η` is
  the factor part of the model, and `m̄` is its effort-weighted mean over all hours. Averaged
  over when people usually go out, the hours reproduce the daily chance.
  - `GET /species/{id}/forecast/hourly?lat=&lon=|place_id=&date=` gives 24 local hours, each
    with `p`, its multiplier and the hour's factor levels, plus the three best hours and
    each factor's per-level multipliers.
  - Tides come from the nearest station within 40 km (predictions shipped in the bundle).
  - The sun and moon are computed for the point.

**Policy:** hourly detail is finer than any tier but OPEN allows (hour granularity), so only
openly mapped species' hourly models are published. Descriptive indices (`/timing`) are
published for open and generalized species.

**Caveat:** records mix activity, detectability and observer habits (night records are
rarer, camera traps record at night). The result says when a species is *recorded* relatively
more often. That is the right quantity for "when should I go", but it is not a behavioral
claim.

## Adding a factor

1. **Register it** in `FACTORS` with its scale, default shape and levels.
2. **Compute it:**
   - hourly: in `HourSignals.category` / `HourSignals.value` (`conditions/timed.py`);
   - daily: in `DAILY_SIGNALS` and its fetcher (`conditions/daily.py`).
3. **Make it a candidate:** add it to `GROUP_DEFAULTS` for the groups it plausibly affects,
   or declare it in profiles.
4. **Rerun:** `wildlife-radar run publish --force timed` (hourly) or `--force conditions`
   (daily). The gate and scorecard decide whether it helps.
