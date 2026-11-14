import { latLngToCell } from "h3-js";
import { lazy, Suspense, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import type { Where } from "../api/client";
import { ForecastPanel, HourlyPanel, TimingPanel } from "../components/ApiPanels";
import { CalendarChart } from "../components/CalendarChart";
import { ConfidenceBadge } from "../components/Confidence";
import { Legend } from "../components/Legend";
import { LicenseNote } from "../components/License";
import { MapTable } from "../components/MapTable";
import { Async, Loading, NotAvailable } from "../components/Status";
import { WeekSlider } from "../components/WeekSlider";
import { useServices } from "../context";
import { usePhotos, useRegionIndex } from "../hooks";
import { displayName, groupLabel, km, methodLabel, percent, shortDate, times } from "../lib/format";
import { roundCoord } from "../lib/geo";
import {
  bestPeriods,
  calendar,
  cellsBounds,
  cellsForPeriod,
  isPresenceOnly,
  presenceCells,
  presenceGeoJSON,
  segmentForWeek,
  toGeoJSON,
} from "../lib/maps";
import { CONFIDENCE_TEXT, TIER_NAME, delayText, isAwareness } from "../lib/policy";
import type { MapMetric } from "../components/mapColors";
import type { CellFeatureProps } from "../lib/maps";
import { useAsync } from "../lib/useAsync";
import { isoDate, monthLabel, parseIsoDate, weekLabel, weekOf } from "../lib/weeks";
import { CONDITION_CELLS, ConditionsSummaryView, useConditions } from "../components/Conditions";
import { ArrowLeftIcon, WeatherIcon } from "../components/Icons";
import { SpeciesFigure } from "../components/SpeciesPhoto";
import type { SpeciesMapFile, StaticIndex } from "../products/types";
import { useThemeContext } from "../themeContext";
import { usePageTitle } from "../lib/usePageTitle";

const MapView = lazy(() => import("../components/MapView"));

export function SpeciesPage() {
  const { region = "", taxonId = "" } = useParams();
  const { products } = useServices();
  const index = useRegionIndex(region);
  const map = useAsync(() => products.speciesMap(region, taxonId), [products, region, taxonId]);
  usePageTitle(map?.status === "ok" ? displayName(map.data.taxon) : map?.status === "error" ? "Not available" : null);
  return (
    <div className="page">
      <p className="crumbs">
        <Link to={`/r/${region}`}>
          <ArrowLeftIcon />
          {index?.status === "ok" ? index.data.region.name : "Region"}
        </Link>
      </p>
      <Async state={map} what="This species" notAvailable={<NotAvailable what="This species" />}>
        {(m) => (index?.status === "ok" ? <SpeciesView region={region} index={index.data} map={m} /> : <Loading />)}
      </Async>
    </div>
  );
}

function SpeciesView({ region, index, map }: { region: string; index: StaticIndex; map: SpeciesMapFile }) {
  const { config, api } = useServices();
  const photos = usePhotos(region);
  const { effective: theme } = useThemeContext();
  const [params, setParams] = useSearchParams();
  const t = map.taxon;
  const awareness = isAwareness(t.mode, t.tier) || map.segments.every(isPresenceOnly);
  const year = new Date().getFullYear();

  const week = clampWeek(Number(params.get("week")) || weekOf(new Date()));
  const placeId = params.get("place");
  const lat = params.get("lat");
  const lon = params.get("lon");
  const point = useMemo(() => pointFrom(index, placeId, lat, lon), [index, placeId, lat, lon]);
  const metric: MapMetric = params.get("view") === "compare" ? "lift" : "chance";
  const mapPlaces = useMemo(
    () =>
      Object.entries(index.places).map(([id, p]) => ({
        id,
        name: p.name,
        lat: p.lat,
        lon: p.lon,
      })),
    [index],
  );
  const where: Where | null = placeId && index.places[placeId] ? { placeId } : point;
  const [date, setDate] = useState(isoDate());

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    setParams(next, { replace: true });
  };

  const choosePoint = (pt: { lat: number; lon: number }) =>
    update({
      lat: String(roundCoord(pt.lat)),
      lon: String(roundCoord(pt.lon)),
      place: null,
    });

  const hit = useMemo(() => segmentForWeek(map, week), [map, week]);
  const presenceOnlyWeek = hit ? isPresenceOnly(hit.segment) : false;

  const geo = useMemo(() => {
    if (awareness) return presenceGeoJSON(presenceCells(map));
    if (!hit) return toGeoJSON([]);
    if (isPresenceOnly(hit.segment)) {
      const cells = hit.segment.cells.filter((_, i) => (hit.segment.p[i] ?? []).some((v) => v !== null && v > 0));
      return presenceGeoJSON(cells);
    }
    return toGeoJSON(cellsForPeriod(hit.segment, hit.j, map.p_scale));
  }, [awareness, map, hit]);

  const bounds = useMemo(() => {
    const all = map.segments.flatMap((s) => s.cells);
    return cellsBounds(all) ?? index.region.bbox;
  }, [map, index]);

  const values = useMemo(
    () => geo.features.filter((f) => f.properties.p !== null).map((f) => f.properties.p as number),
    [geo],
  );
  const insufficient = geo.features.filter((f) => f.properties.insufficient).length;
  const selectedCell = useMemo(() => {
    if (!point || !hit) return null;
    return (
      geo.features.find((f) => f.properties.cell === cellAt(point, hit.segment.resolution))?.properties.cell ?? null
    );
  }, [point, hit, geo]);

  const series = useMemo(() => (awareness ? null : calendar(map, point)), [awareness, map, point]);
  const best = series ? bestPeriods(series) : [];
  const currentPeriod = series?.granularity === "month" ? hit?.period : week;

  const hasLift = geo.features.some((f) => f.properties.liftBin >= 0);
  const showLift = metric === "lift" && hasLift;

  // Today's conditions over the week's highest cells (API only, on request).
  const [conditionsOn, setConditionsOn] = useState(false);
  const canCondition = api.enabled && !awareness && hit !== null && !presenceOnlyWeek;
  const dateWeek = weekOf(parseIsoDate(date) ?? new Date());
  const conditions = useConditions(t.taxon_id, geo, date, conditionsOn && canCondition && week === dateWeek);

  const mapLabel = awareness
    ? `Map of where ${displayName(t)} is present at landscape scale (awareness only).`
    : !hit
      ? `No map is published for ${displayName(t)} in week ${week}.`
      : presenceOnlyWeek
        ? `Map of where ${displayName(t)} is present this time of year (awareness only).`
        : `Map of ${displayName(t)}: ${showLift ? "chance compared with the wider area" : "chance per outing"} in week ${week} across ${geo.features.length} cells of ${km(hit.segment.resolution_km)}; highest chance ${percent(Math.max(0, ...values))}.`;

  const placeName = placeId ? index.places[placeId]?.name : null;
  const whereText = placeName ?? (point ? "the point you chose" : null);

  return (
    <article className="page">
      <header className="page-head species-head">
        <div className="species-title">
          <SpeciesFigure photo={photos.get(t.taxon_id) ?? null} group={t.group} name={displayName(t)} />
          <div>
            <h1>{displayName(t)}</h1>
            {t.common_name && t.scientific_name && <p className="sci">{t.scientific_name}</p>}
            <div className="chips">
              <span className="chip">{groupLabel(t.group)}</span>
              <span className={awareness ? "chip warn" : "chip accent"}>{TIER_NAME[t.tier] ?? `Tier ${t.tier}`}</span>
            </div>
          </div>
        </div>
        {!awareness && (
          <div className="what-number">
            <p>
              <span className="muted">What the number means: </span>
              <strong>chance {methodLabel(map.method)}</strong> of recording this species.
            </p>
            {map.label && (
              <details className="more">
                <summary>How it's worked out</summary>
                <p>{map.label}</p>
              </details>
            )}
          </div>
        )}
      </header>

      {awareness && (
        <div className="notice notice-awareness" role="note">
          <p>
            <strong>Shown for awareness only.</strong> This species is sensitive, so we show only where it is present at
            landscape scale: no chances, timings or recent sightings.
          </p>
        </div>
      )}

      <section aria-labelledby="map-h" className="card">
        <div className="card-head">
          <h2 id="map-h">{awareness ? "Where it occurs" : "Map by week"}</h2>
        </div>
        {!awareness && (
          <WeekSlider
            week={week}
            year={year}
            monthly={hit?.segment.granularity === "month"}
            onChange={(w) => update({ week: String(w) })}
          />
        )}
        {!awareness && !hit && (
          <NotAvailable what={`Week ${week}`} detail="No map is published for this species at this time of year." />
        )}
        {!awareness && presenceOnlyWeek && (
          <p className="notice notice-awareness">
            At this time of year this species is shown for awareness only: presence at landscape scale, without numbers.
          </p>
        )}
        {!awareness && hit && !presenceOnlyWeek && (hasLift || canCondition) && (
          <div className="map-tools">
            {hasLift && (
              <div className="segmented" role="group" aria-label="Colour the map by">
                <button type="button" aria-pressed={!showLift} onClick={() => update({ view: null })}>
                  Chance
                </button>
                <button type="button" aria-pressed={showLift} onClick={() => update({ view: "compare" })}>
                  Compared with wider area
                </button>
              </div>
            )}
            {canCondition && (
              <button
                type="button"
                className="toggle"
                aria-pressed={conditionsOn}
                onClick={() => setConditionsOn((v) => !v)}
              >
                <WeatherIcon />
                {date === isoDate() ? "Today's conditions" : `Conditions on ${shortDate(date)}`}
              </button>
            )}
          </div>
        )}
        {showLift && !presenceOnlyWeek && (
          <p className="muted small">
            Each cell's chance against the average of the wider area around it this week. Orange cells are better than
            their surroundings, even where the chance itself is low.
          </p>
        )}
        {conditionsOn && canCondition && (
          <div className="conditions-panel">
            {week !== dateWeek ? (
              <p className="small">
                The forecast is for {shortDate(date)}, in week {dateWeek}.{" "}
                <button type="button" className="link-button" onClick={() => update({ week: String(dateWeek) })}>
                  Show week {dateWeek}
                </button>
              </p>
            ) : conditions.state?.status === "loading" ? (
              <p className="loading muted small" role="status">
                Getting the forecast for the {CONDITION_CELLS} highest cells…
              </p>
            ) : conditions.state?.status === "error" ? (
              <p className="muted small">The forecast isn't available for this species right now.</p>
            ) : conditions.summary ? (
              <>
                {conditions.summary.baselineOnly < conditions.summary.cells && (
                  <ul className="legend" aria-label="Map legend: conditions against the usual chance">
                    <li>
                      <span className="swatch swatch-dot dot-up" aria-hidden="true" /> Better than usual
                    </li>
                    <li>
                      <span className="swatch swatch-dot dot-same" aria-hidden="true" /> About usual
                    </li>
                    <li>
                      <span className="swatch swatch-dot dot-down" aria-hidden="true" /> Worse than usual
                    </li>
                  </ul>
                )}
                <ConditionsSummaryView summary={conditions.summary} date={date} />
              </>
            ) : null}
          </div>
        )}
        <div className="map-wrap">
          <Suspense fallback={<div className="map map-placeholder">Loading map…</div>}>
            <MapView
              data={geo}
              bounds={bounds}
              theme={theme}
              basemap={config.basemap}
              layers={config.layers}
              selectedCell={selectedCell}
              label={mapLabel}
              metric={showLift ? "lift" : "chance"}
              markers={
                conditionsOn &&
                week === dateWeek &&
                conditions.summary &&
                conditions.summary.baselineOnly < conditions.summary.cells
                  ? conditions.markers
                  : undefined
              }
              places={mapPlaces}
              selectedPlace={placeId}
              onPlace={(id) => update({ place: id, lat: null, lon: null })}
              describe={awareness || presenceOnlyWeek ? undefined : describeCell}
              onSelect={awareness ? undefined : choosePoint}
            />
          </Suspense>
        </div>
        <Legend theme={theme} presence={awareness || presenceOnlyWeek} metric={showLift ? "lift" : "chance"} />
        {!awareness && hit && !presenceOnlyWeek && (
          <p className="muted small map-caption">
            {geo.features.length} cells of {km(hit.segment.resolution_km)}
            {hit.segment.granularity === "month"
              ? `, monthly (${monthLabel(hit.period)})`
              : `, ${weekLabel(year, week)}`}
            {insufficient > 0 && ` · ${insufficient} with not enough data`}. Tap a cell or a place, or use the table, to
            see its calendar and forecast.
          </p>
        )}
        {!awareness && hit && !presenceOnlyWeek && (
          <MapTable
            data={geo}
            places={index.places}
            selectedCell={selectedCell}
            onChoose={choosePoint}
            sortBy={showLift ? "lift" : "chance"}
          />
        )}
      </section>

      {!awareness && (
        <section aria-labelledby="where-h" className="card">
          <div className="card-head">
            <div>
              <h2 id="where-h">Calendar</h2>
              <p className="muted small">
                {point
                  ? `At ${whereText}.`
                  : `Across ${index.region.name}. Choose a place or tap the map for a local calendar.`}
              </p>
            </div>
            <LocationPicker
              index={index}
              placeId={placeId}
              point={placeId ? null : point}
              onPlace={(id) => update({ place: id || null, lat: null, lon: null })}
              onClear={() => update({ place: null, lat: null, lon: null })}
            />
          </div>
          {series &&
            (point && series.points.every((p) => p.p === null && p.confidence !== "insufficient") ? (
              <NotAvailable what="Calendar here" detail="No estimates are published for this location." />
            ) : (
              <CalendarChart
                series={series}
                year={year}
                currentPeriod={currentPeriod}
                title={`Seasonal calendar for ${displayName(t)} ${point ? "at the selected location" : `across ${index.region.name}`}`}
              />
            ))}
          {series && best.length > 0 && (
            <p className="small">
              <strong>Best {series.granularity === "month" ? "months" : "weeks"}:</strong>{" "}
              {best
                .map((b) =>
                  series.granularity === "month"
                    ? monthLabel(b.period)
                    : `${weekLabel(year, b.period)} (${percent(b.p)})`,
                )
                .join("; ")}{" "}
              {point && best[0] && <ConfidenceBadge level={best[0].confidence} />}
            </p>
          )}
        </section>
      )}

      {!awareness && (
        <section aria-labelledby="forecast-h" className="card">
          <div className="card-head">
            <div>
              <h2 id="forecast-h">Forecast for a day</h2>
              <p className="muted small">
                {whereText ? `At ${whereText}.` : "Choose a place above or tap the map to see the forecast for a day."}
              </p>
            </div>
            {where && (
              <label className="field">
                Day
                <input type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
              </label>
            )}
          </div>
          {where && (
            <>
              <ForecastPanel taxonId={t.taxon_id} where={where} date={date} />
              <h3>Best time of day</h3>
              <HourlyPanel taxonId={t.taxon_id} where={where} date={date} />
            </>
          )}
        </section>
      )}

      {!awareness && (
        <section aria-labelledby="timing-h" className="card">
          <details className="fold">
            <summary>
              <h2 id="timing-h" className="inline-h">
                When it's recorded
              </h2>
            </summary>
            <TimingPanel taxonId={t.taxon_id} region={region} />
          </details>
        </section>
      )}

      <section className="card small" aria-labelledby="about-data-h">
        <h2 id="about-data-h" className="h-small">
          About this data
        </h2>
        {!awareness && (
          <p className="muted">
            Recent sightings of this species are published after at least {delayText(t.tier)}. Seasonal maps are built
            from historical records ({index.baseline.model_version}).
          </p>
        )}
        <LicenseNote license={map.license} />
      </section>
    </article>
  );
}

function LocationPicker({
  index,
  placeId,
  point,
  onPlace,
  onClear,
}: {
  index: StaticIndex;
  placeId: string | null;
  point: { lat: number; lon: number } | null;
  onPlace: (id: string) => void;
  onClear: () => void;
}) {
  const places = Object.entries(index.places);
  return (
    <div className="location-picker">
      <label className="field">
        Location
        <select value={placeId ?? ""} onChange={(e) => onPlace(e.target.value)}>
          <option value="">{point ? "Point on the map" : "Whole region"}</option>
          {places.map(([id, p]) => (
            <option key={id} value={id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      {(placeId || point) && (
        <button type="button" className="link-button small" onClick={onClear}>
          Clear
        </button>
      )}
    </div>
  );
}

function pointFrom(
  index: StaticIndex,
  placeId: string | null,
  lat: string | null,
  lon: string | null,
): { lat: number; lon: number } | null {
  const place = placeId ? index.places[placeId] : undefined;
  if (place) return { lat: place.lat, lon: place.lon };
  if (lat && lon && Number.isFinite(Number(lat)) && Number.isFinite(Number(lon)))
    return { lat: Number(lat), lon: Number(lon) };
  return null;
}

function clampWeek(w: number): number {
  return Math.min(52, Math.max(1, Math.round(w)));
}

function cellAt(pt: { lat: number; lon: number }, res: number): string {
  return latLngToCell(pt.lat, pt.lon, res);
}

function describeCell(c: CellFeatureProps): string {
  if (c.insufficient) return "Not enough data here";
  if (c.p === null) return "";
  const lift = c.lift === null ? "" : ` · ${times(c.lift)} the wider area`;
  return `${percent(c.p)} chance per outing · ${CONFIDENCE_TEXT[c.confidence].toLowerCase()}${lift}`;
}
