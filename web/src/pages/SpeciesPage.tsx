import { latLngToCell } from "h3-js";
import { lazy, Suspense, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import type { Where } from "../api/client";
import { ForecastPanel, HourlyPanel, TimingPanel } from "../components/ApiPanels";
import { CalendarChart } from "../components/CalendarChart";
import { ConfidenceBadge } from "../components/Confidence";
import { Legend } from "../components/Legend";
import { LicenseNote } from "../components/License";
import { Async, Loading, NotAvailable } from "../components/Status";
import { WeekSlider } from "../components/WeekSlider";
import { useServices } from "../context";
import { useRegionIndex } from "../hooks";
import { displayName, groupLabel, km, methodLabel, percent } from "../lib/format";
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
import { TIER_NAME, delayText, isAwareness } from "../lib/policy";
import { useAsync } from "../lib/useAsync";
import { isoDate, monthLabel, weekLabel, weekOf } from "../lib/weeks";
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
        <Link to={`/r/${region}`}>← {index?.status === "ok" ? index.data.region.name : "Region"}</Link>
      </p>
      <Async state={map} what="This species" notAvailable={<NotAvailable what="This species" />}>
        {(m) => (index?.status === "ok" ? <SpeciesView region={region} index={index.data} map={m} /> : <Loading />)}
      </Async>
    </div>
  );
}

function SpeciesView({ region, index, map }: { region: string; index: StaticIndex; map: SpeciesMapFile }) {
  const { config } = useServices();
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
    return geo.features.find((f) => f.properties.cell === cellAt(point, hit.segment.resolution))?.properties.cell ?? null;
  }, [point, hit, geo]);

  const series = useMemo(() => (awareness ? null : calendar(map, point)), [awareness, map, point]);
  const best = series ? bestPeriods(series) : [];
  const currentPeriod = series?.granularity === "month" ? hit?.period : week;

  const mapLabel = awareness
    ? `Map of where ${displayName(t)} is present at landscape scale (awareness only).`
    : !hit
      ? `No map is published for ${displayName(t)} in week ${week}.`
      : presenceOnlyWeek
        ? `Map of where ${displayName(t)} is present this time of year (awareness only).`
        : `Map of ${displayName(t)}: chance per outing in week ${week} across ${geo.features.length} cells of ${km(hit.segment.resolution_km)}; highest ${percent(Math.max(0, ...values))}.`;

  return (
    <article>
      <header className="species-head">
        <h1>{displayName(t)}</h1>
        {t.common_name && t.scientific_name && <p className="sci">{t.scientific_name}</p>}
        <p className="muted small">
          {groupLabel(t.group)} · <span className="badge">{TIER_NAME[t.tier] ?? `Tier ${t.tier}`}</span>
        </p>
      </header>

      {awareness ? (
        <div className="notice notice-awareness" role="note">
          <p>
            <strong>Shown for awareness only.</strong> This species is sensitive, so we show only where it is present at
            landscape scale: no chances, timings or recent sightings.
          </p>
        </div>
      ) : (
        <section className="what-number" aria-labelledby="meaning-h">
          <h2 id="meaning-h" className="h-small">
            What the number means
          </h2>
          <p>
            <strong>Chance {methodLabel(map.method)}</strong> of recording this species. {map.label}
          </p>
        </section>
      )}

      <section aria-labelledby="map-h" className="section">
        <h2 id="map-h">{awareness ? "Where it occurs" : "Map by week"}</h2>
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
        <div className="map-wrap">
          <Suspense fallback={<div className="map map-placeholder">Loading map…</div>}>
            <MapView
              data={geo}
              bounds={bounds}
              theme={theme}
              basemap={config.basemap}
              selectedCell={selectedCell}
              label={mapLabel}
              onSelect={
                awareness
                  ? undefined
                  : (pt) => update({ lat: String(roundCoord(pt.lat)), lon: String(roundCoord(pt.lon)), place: null })
              }
            />
          </Suspense>
        </div>
        <Legend theme={theme} presence={awareness || presenceOnlyWeek} />
        {!awareness && hit && !presenceOnlyWeek && (
          <p className="muted small">
            {geo.features.length} cells of {km(hit.segment.resolution_km)}
            {hit.segment.granularity === "month" ? `, monthly (${monthLabel(hit.period)})` : `, ${weekLabel(year, week)}`}
            {insufficient > 0 && ` · ${insufficient} with not enough data`}. Tap a cell to see its calendar and forecast.
          </p>
        )}
      </section>

      {!awareness && (
        <section aria-labelledby="where-h" className="section">
          <h2 id="where-h">Calendar and forecast</h2>
          <LocationPicker
            index={index}
            placeId={placeId}
            point={placeId ? null : point}
            onPlace={(id) => update({ place: id || null, lat: null, lon: null })}
            onClear={() => update({ place: null, lat: null, lon: null })}
          />
          {series && (
            <>
              <h3>Calendar {point ? "here" : `across ${index.region.name}`}</h3>
              {point && series.points.every((p) => p.p === null && p.confidence !== "insufficient") ? (
                <NotAvailable what="Calendar here" detail="No estimates are published for this location." />
              ) : (
                <CalendarChart
                  series={series}
                  year={year}
                  currentPeriod={currentPeriod}
                  title={`Seasonal calendar for ${displayName(t)} ${point ? "at the selected location" : `across ${index.region.name}`}`}
                />
              )}
              {best.length > 0 && (
                <p>
                  Best {series.granularity === "month" ? "months" : "weeks"}:{" "}
                  {best
                    .map((b) =>
                      series.granularity === "month" ? monthLabel(b.period) : `${weekLabel(year, b.period)} (${percent(b.p)})`,
                    )
                    .join("; ")}
                  {point && best[0] && <ConfidenceBadge level={best[0].confidence} />}
                </p>
              )}
              {!point && <p className="muted small">Regional average. Choose a place or tap the map for a local calendar.</p>}
            </>
          )}

          <h3>Daily forecast</h3>
          {where ? (
            <>
              <label className="label inline">
                Day{" "}
                <input type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
              </label>
              <ForecastPanel taxonId={t.taxon_id} where={where} date={date} />
              <h3>Best time of day</h3>
              <HourlyPanel taxonId={t.taxon_id} where={where} date={date} />
            </>
          ) : (
            <p className="muted">Choose a place or tap the map to see the forecast for a day.</p>
          )}
          <h3>When it's recorded</h3>
          <TimingPanel taxonId={t.taxon_id} region={region} />
        </section>
      )}

      <section className="section small" aria-labelledby="about-data-h">
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
      <label className="label inline">
        Place{" "}
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
        <button type="button" className="link-button" onClick={onClear}>
          Clear location
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
  if (lat && lon && Number.isFinite(Number(lat)) && Number.isFinite(Number(lon))) return { lat: Number(lat), lon: Number(lon) };
  return null;
}

function clampWeek(w: number): number {
  return Math.min(52, Math.max(1, Math.round(w)));
}

function cellAt(pt: { lat: number; lon: number }, res: number): string {
  return latLngToCell(pt.lat, pt.lon, res);
}
