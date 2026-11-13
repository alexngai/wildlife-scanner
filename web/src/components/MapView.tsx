import { useEffect, useLayoutEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";

// MapLibre's worker is a separate, self-contained file; ship it as an asset and point at it.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

maplibregl.setWorkerUrl(workerUrl);

type GeoData = Parameters<GeoJSONSource["setData"]>[0];
import "maplibre-gl/dist/maplibre-gl.css";
import type { BasemapConfig } from "../config";
import type { FeatureCollection } from "../lib/maps";
import { rampFor } from "./mapColors";

export interface MapViewProps {
  data: FeatureCollection;
  /** [w, s, e, n] to fit when the map opens (and when it changes). */
  bounds: [number, number, number, number] | null;
  theme: "light" | "dark";
  basemap: BasemapConfig;
  selectedCell?: string | null;
  onSelect?: (pt: { lat: number; lon: number; cell: string | null }) => void;
  /** Accessible description of what the map shows (the map itself isn't readable by screen readers). */
  label: string;
}

const SRC = "wr-cells";

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

function addLayers(map: maplibregl.Map, data: FeatureCollection, theme: "light" | "dark") {
  if (map.getSource(SRC)) return;
  const ramp = rampFor(theme);
  map.addSource(SRC, { type: "geojson", data: data as unknown as GeoData });
  const binColor = [
    "match",
    ["get", "bin"],
    ...ramp.flatMap((color, bin) => [bin, color]),
    ramp[0] ?? "#888888",
  ] as unknown as maplibregl.ExpressionSpecification;
  map.addLayer({
    id: "wr-fill",
    type: "fill",
    source: SRC,
    paint: {
      "fill-color": [
        "case",
        ["get", "presence"],
        theme === "dark" ? "#e0a458" : "#b4630e",
        ["get", "insufficient"],
        theme === "dark" ? "#8a9099" : "#9aa1a9",
        binColor,
      ],
      "fill-opacity": [
        "case",
        ["get", "presence"],
        0.45,
        ["get", "insufficient"],
        0.25,
        ["==", ["get", "confidence"], "low"],
        0.4,
        0.72,
      ],
    },
  });
  map.addLayer({
    id: "wr-insufficient",
    type: "line",
    source: SRC,
    filter: ["==", ["get", "insufficient"], true],
    paint: { "line-color": theme === "dark" ? "#c3c8cf" : "#5b6168", "line-width": 1, "line-dasharray": [2, 2] },
  });
  map.addLayer({
    id: "wr-selected",
    type: "line",
    source: SRC,
    filter: ["==", ["get", "cell"], ""],
    paint: { "line-color": theme === "dark" ? "#ffffff" : "#111111", "line-width": 2.5 },
  });
}

export default function MapView({ data, bounds, theme, basemap, selectedCell, onSelect, label }: MapViewProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const latest = useRef({ data, theme, selectedCell, onSelect });
  useLayoutEffect(() => {
    latest.current = { data, theme, selectedCell, onSelect };
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
    const onStyle = () => {
      styleLoaded = true;
      const { data: d, theme: t, selectedCell: sel } = latest.current;
      addLayers(map, d, t);
      map.setFilter("wr-selected", ["==", ["get", "cell"], sel ?? ""]);
    };
    map.on("style.load", onStyle);
    // If the basemap can't be reached, fall back to a plain background so the data still shows.
    map.on("error", (e: { error?: { message?: string } }) => {
      if (!styleLoaded && /style|fetch|Failed/i.test(String(e.error?.message ?? ""))) {
        styleLoaded = true;
        map.setStyle(blankStyle(latest.current.theme));
      }
    });
    map.on("click", "wr-fill", (e: MapLayerMouseEvent) => {
      const f = e.features?.[0];
      latest.current.onSelect?.({ lat: e.lngLat.lat, lon: e.lngLat.lng, cell: (f?.properties?.cell as string) ?? null });
    });
    map.on("mouseenter", "wr-fill", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "wr-fill", () => (map.getCanvas().style.cursor = ""));
    return () => {
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
    if (map?.getLayer("wr-selected")) map.setFilter("wr-selected", ["==", ["get", "cell"], selectedCell ?? ""]);
  }, [selectedCell]);

  useEffect(() => {
    if (bounds && mapRef.current) mapRef.current.fitBounds(bounds, { padding: 24, duration: 0 });
  }, [bounds]);

  return <div ref={container} className="map" role="img" aria-label={label} data-testid="map" />;
}
