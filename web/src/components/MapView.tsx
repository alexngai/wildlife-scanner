import { useEffect, useLayoutEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";

// MapLibre's worker is a separate, self-contained file; ship it as an asset and point at it.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

maplibregl.setWorkerUrl(workerUrl);

type GeoData = Parameters<GeoJSONSource["setData"]>[0];
type Expr = maplibregl.ExpressionSpecification;
import "maplibre-gl/dist/maplibre-gl.css";
import type { BasemapConfig } from "../config";
import type { CellFeatureProps, FeatureCollection } from "../lib/maps";
import { liftRampFor, rampFor, type MapMetric } from "./mapColors";

export interface MapPlace {
  id: string;
  name: string;
  lat: number;
  lon: number;
  /** 0-1: when given, the dot is sized and coloured by it (hotspots); null = no data. */
  value?: number | null;
  /** Extra text for the place's hover / tap popup. */
  note?: string;
}

/** A point drawn over the cells, e.g. today's forecast against the usual chance. */
export interface MapMarker {
  lat: number;
  lon: number;
  /** -1 below usual, 0 about the same, 1 above. */
  direction: -1 | 0 | 1;
  text: string;
}

export interface MapViewProps {
  data: FeatureCollection;
  /** [w, s, e, n] to fit when the map opens (and when it changes). */
  bounds: [number, number, number, number] | null;
  theme: "light" | "dark";
  basemap: BasemapConfig;
  /** What the cell colours show: chance per outing (default) or chance against the wider area. */
  metric?: MapMetric;
  selectedCell?: string | null;
  onSelect?: (pt: { lat: number; lon: number; cell: string | null }) => void;
  /** Named places drawn as points; tapping one calls onPlace. */
  places?: MapPlace[];
  selectedPlace?: string | null;
  onPlace?: (id: string) => void;
  /** Text for a cell's hover / tap popup; no popup when absent. */
  describe?: (cell: CellFeatureProps) => string;
  /** Accessible description of what the map shows (the map itself isn't readable by screen readers). */
  label: string;
  markers?: MapMarker[];
  /** A shorter map, for overviews. */
  short?: boolean;
}

const SRC = "wr-cells";
const NO_MARKERS: MapMarker[] = [];
const PLACES = "wr-places";
const MARKERS = "wr-markers";

function markersData(markers: MapMarker[]): GeoData {
  return {
    type: "FeatureCollection",
    features: markers.map((m) => ({
      type: "Feature",
      properties: { direction: m.direction, popup: m.text },
      geometry: { type: "Point", coordinates: [m.lon, m.lat] },
    })),
  } as GeoData;
}

function blankStyle(theme: "light" | "dark"): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [{ id: "bg", type: "background", paint: { "background-color": theme === "dark" ? "#16191d" : "#eef1f3" } }],
  };
}

function styleFor(basemap: BasemapConfig, theme: "light" | "dark"): string | StyleSpecification {
  const url = theme === "dark" ? basemap.dark : basemap.light;
  return !url || url === "none" ? blankStyle(theme) : url;
}

function matchBins(prop: string, ramp: string[], fallback: string): Expr {
  return ["match", ["get", prop], ...ramp.flatMap((color, bin) => [bin, color]), fallback] as unknown as Expr;
}

/** Fill colour by metric; presence and "not enough data" look the same in both. */
export function fillColor(theme: "light" | "dark", metric: MapMetric): Expr {
  const dark = theme === "dark";
  const values =
    metric === "lift"
      ? matchBins("liftBin", liftRampFor(theme), dark ? "#16191d" : "#ffffff")
      : matchBins("bin", rampFor(theme), rampFor(theme)[0] ?? "#888888");
  return [
    "case",
    ["get", "presence"],
    dark ? "#e0a458" : "#b4630e",
    ["get", "insufficient"],
    dark ? "#8a9099" : "#9aa1a9",
    values,
  ] as unknown as Expr;
}

function fillOpacity(metric: MapMetric): Expr {
  return [
    "case",
    ["get", "presence"],
    0.45,
    ["get", "insufficient"],
    0.12,
    // Cells with no comparison stay faint in the "compared" view.
    metric === "lift" ? ["==", ["get", "liftBin"], -1] : false,
    0.15,
    ["==", ["get", "confidence"], "low"],
    0.4,
    0.72,
  ] as unknown as Expr;
}

const HATCH = "wr-hatch";

/** A small diagonal-line tile so "not enough data" is hatched on the map, as in the legend. */
function hatchImage(theme: "light" | "dark"): { width: number; height: number; data: Uint8Array } {
  const size = 8;
  const data = new Uint8Array(size * size * 4);
  const [r, g, b] = theme === "dark" ? [170, 176, 184] : [110, 117, 125];
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if ((x + y) % size < 2) {
        const o = (y * size + x) * 4;
        data.set([r, g, b, 200], o);
      }
    }
  }
  return { width: size, height: size, data };
}

/** Plain dots, or sized by value (5-22 px) when places carry one. */
function placeRadius(selected: string | null): Expr {
  return [
    "+",
    ["case", ["==", ["get", "id"], selected ?? ""], 2, 0],
    ["case", [">=", ["get", "value"], 0], ["+", 6, ["*", 16, ["sqrt", ["get", "value"]]]], 5],
  ] as unknown as Expr;
}

function placeColor(theme: "light" | "dark"): Expr {
  const ramp = rampFor(theme);
  const plain = theme === "dark" ? "#ffffff" : "#1b1f24";
  return [
    "case",
    [">=", ["get", "value"], 0],
    ["interpolate", ["linear"], ["get", "value"], 0, ramp[1] ?? plain, 0.5, ramp[3] ?? plain, 1, ramp[5] ?? plain],
    plain,
  ] as unknown as Expr;
}

function placesData(places: MapPlace[]): GeoData {
  return {
    type: "FeatureCollection",
    features: places.map((p) => ({
      type: "Feature",
      properties: { id: p.id, name: p.name, value: p.value ?? -1, popup: p.note ? `${p.name}: ${p.note}` : p.name },
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
    })),
  } as GeoData;
}

function addLayers(map: maplibregl.Map, s: Latest) {
  if (map.getSource(SRC)) return;
  const dark = s.theme === "dark";
  map.addSource(SRC, { type: "geojson", data: s.data as unknown as GeoData });
  if (map.hasImage(HATCH)) map.removeImage(HATCH);
  map.addImage(HATCH, hatchImage(s.theme));
  map.addLayer({
    id: "wr-fill",
    type: "fill",
    source: SRC,
    paint: { "fill-color": fillColor(s.theme, s.metric), "fill-opacity": fillOpacity(s.metric) },
  });
  map.addLayer({
    id: "wr-hatch",
    type: "fill",
    source: SRC,
    filter: ["==", ["get", "insufficient"], true],
    paint: { "fill-pattern": HATCH },
  });
  map.addLayer({
    id: "wr-insufficient",
    type: "line",
    source: SRC,
    filter: ["==", ["get", "insufficient"], true],
    paint: { "line-color": dark ? "#c3c8cf" : "#5b6168", "line-width": 1, "line-dasharray": [2, 2] },
  });
  map.addLayer({
    id: "wr-selected",
    type: "line",
    source: SRC,
    filter: ["==", ["get", "cell"], s.selectedCell ?? ""],
    paint: { "line-color": dark ? "#ffffff" : "#111111", "line-width": 2.5 },
  });

  const lift = liftRampFor(s.theme);
  map.addSource(MARKERS, { type: "geojson", data: markersData(s.markers) });
  map.addLayer({
    id: "wr-markers",
    type: "circle",
    source: MARKERS,
    paint: {
      "circle-radius": ["case", ["==", ["get", "direction"], 0], 5, 8],
      // "About usual" is a hollow ring, so it isn't mistaken for a place dot.
      "circle-opacity": ["case", ["==", ["get", "direction"], 0], 0, 1],
      "circle-color": [
        "match",
        ["get", "direction"],
        1,
        lift[4] ?? "#e66101",
        -1,
        lift[0] ?? "#5e3c99",
        dark ? "#c3c8cf" : "#5b6168",
      ] as unknown as Expr,
      "circle-stroke-color": [
        "case",
        ["==", ["get", "direction"], 0],
        dark ? "#c3c8cf" : "#5b6168",
        dark ? "#1b1f24" : "#ffffff",
      ] as unknown as Expr,
      "circle-stroke-width": 2,
    },
  });

  map.addSource(PLACES, { type: "geojson", data: placesData(s.places) });
  map.addLayer({
    id: "wr-places",
    type: "circle",
    source: PLACES,
    paint: {
      "circle-radius": placeRadius(s.selectedPlace),
      "circle-color": placeColor(s.theme),
      "circle-stroke-color": dark ? "#1b1f24" : "#ffffff",
      "circle-stroke-width": 2,
    },
  });
  // Labels need the basemap's fonts; the plain fallback style has none, so names show on hover.
  if (map.getStyle().glyphs) {
    map.addLayer({
      id: "wr-place-labels",
      type: "symbol",
      source: PLACES,
      layout: {
        "text-field": ["get", "name"],
        "text-size": 12,
        "text-offset": [0, 0.9],
        "text-anchor": "top",
        "text-optional": true,
      },
      paint: {
        "text-color": dark ? "#f2f4f6" : "#1b1f24",
        "text-halo-color": dark ? "#1b1f24" : "#ffffff",
        "text-halo-width": 1.5,
      },
    });
  }
}

interface Latest {
  data: FeatureCollection;
  theme: "light" | "dark";
  metric: MapMetric;
  selectedCell: string | null;
  places: MapPlace[];
  markers: MapMarker[];
  selectedPlace: string | null;
  onSelect?: MapViewProps["onSelect"];
  onPlace?: MapViewProps["onPlace"];
  describe?: MapViewProps["describe"];
}

export default function MapView({
  data,
  bounds,
  theme,
  basemap,
  metric = "chance",
  selectedCell = null,
  onSelect,
  places = [],
  selectedPlace = null,
  onPlace,
  describe,
  label,
  short = false,
  markers = NO_MARKERS,
}: MapViewProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const latest = useRef<Latest>({ data, theme, metric, selectedCell, places, markers, selectedPlace, onSelect, onPlace, describe });
  useLayoutEffect(() => {
    latest.current = { data, theme, metric, selectedCell, places, markers, selectedPlace, onSelect, onPlace, describe };
  });

  // Create the map once.
  useEffect(() => {
    if (!container.current) return;
    let styleLoaded = false;
    const map = new maplibregl.Map({
      container: container.current,
      style: styleFor(basemap, theme),
      bounds: bounds ?? undefined,
      fitBoundsOptions: { padding: 24 },
      attributionControl: { compact: false, customAttribution: basemap.attribution },
      cooperativeGestures: true,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "wr-popup", maxWidth: "240px" });

    map.on("style.load", () => {
      styleLoaded = true;
      addLayers(map, latest.current);
    });
    // If the basemap can't be reached, fall back to a plain background so the data still shows.
    map.on("error", (e: { error?: { message?: string } }) => {
      if (!styleLoaded && /style|fetch|Failed/i.test(String(e.error?.message ?? ""))) {
        styleLoaded = true;
        map.setStyle(blankStyle(latest.current.theme));
      }
    });

    // Points drawn over the cells (places, markers) take hover and taps before the cell under them.
    const overlayAt = (e: MapLayerMouseEvent) => {
      const layers = ["wr-places", "wr-markers"].filter((l) => map.getLayer(l));
      return layers.length > 0 ? map.queryRenderedFeatures(e.point, { layers })[0] : undefined;
    };
    const showCell = (e: MapLayerMouseEvent) => {
      const props = e.features?.[0]?.properties as CellFeatureProps | undefined;
      const text = props && latest.current.describe?.(props);
      if (text) popup.setLngLat(e.lngLat).setText(text).addTo(map);
    };

    map.on("click", "wr-fill", (e: MapLayerMouseEvent) => {
      const over = overlayAt(e);
      if (over?.layer.id === "wr-places") return; // the place handles it
      const f = e.features?.[0];
      const markerText = over?.properties?.popup as string | undefined;
      if (markerText) popup.setLngLat(e.lngLat).setText(markerText).addTo(map);
      else showCell(e);
      latest.current.onSelect?.({ lat: e.lngLat.lat, lon: e.lngLat.lng, cell: (f?.properties?.cell as string) ?? null });
    });
    map.on("mousemove", "wr-fill", (e: MapLayerMouseEvent) => {
      if (!overlayAt(e)) showCell(e);
    });
    map.on("mouseleave", "wr-fill", () => popup.remove());
    map.on("click", "wr-places", (e: MapLayerMouseEvent) => {
      const id = e.features?.[0]?.properties?.id as string | undefined;
      if (id) latest.current.onPlace?.(id);
    });
    map.on("mousemove", "wr-markers", (e: MapLayerMouseEvent) => {
      const text = e.features?.[0]?.properties?.popup as string | undefined;
      if (text) popup.setLngLat(e.lngLat).setText(text).addTo(map);
    });
    map.on("mouseleave", "wr-markers", () => popup.remove());
    map.on("mousemove", "wr-places", (e: MapLayerMouseEvent) => {
      const text = e.features?.[0]?.properties?.popup as string | undefined;
      if (text) popup.setLngLat(e.lngLat).setText(text).addTo(map);
    });
    for (const layer of ["wr-fill", "wr-places"]) {
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }
    return () => {
      popup.remove();
      map.remove();
      mapRef.current = null;
    };
    // The map is created once; later prop changes are applied by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Theme or basemap change: swap the style; layers are re-added on style.load.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    mapRef.current?.setStyle(styleFor(basemap, theme));
  }, [theme, basemap]);

  useEffect(() => {
    const src = mapRef.current?.getSource(SRC) as GeoJSONSource | undefined;
    src?.setData(data as unknown as GeoData);
  }, [data]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getLayer("wr-fill")) return;
    map.setPaintProperty("wr-fill", "fill-color", fillColor(theme, metric));
    map.setPaintProperty("wr-fill", "fill-opacity", fillOpacity(metric));
  }, [metric, theme]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer("wr-selected")) map.setFilter("wr-selected", ["==", ["get", "cell"], selectedCell ?? ""]);
  }, [selectedCell]);

  useEffect(() => {
    const src = mapRef.current?.getSource(MARKERS) as GeoJSONSource | undefined;
    src?.setData(markersData(markers));
  }, [markers]);

  useEffect(() => {
    const src = mapRef.current?.getSource(PLACES) as GeoJSONSource | undefined;
    src?.setData(placesData(places));
  }, [places]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer("wr-places"))
      map.setPaintProperty("wr-places", "circle-radius", placeRadius(selectedPlace));
  }, [selectedPlace]);

  useEffect(() => {
    if (bounds && mapRef.current) mapRef.current.fitBounds(bounds, { padding: 24, duration: 0 });
  }, [bounds]);

  // MapLibre's canvas is focusable (keyboard pan and zoom), so the description goes on it
  // rather than on a wrapping role="img".
  useEffect(() => {
    mapRef.current?.getCanvas().setAttribute("aria-label", label);
  }, [label]);

  return <div ref={container} className={short ? "map map-short" : "map"} data-testid="map" />;
}
