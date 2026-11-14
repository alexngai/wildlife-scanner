/**
 * Runtime configuration, read from /config.json at startup so a deployment can change data
 * locations, regions and basemap without rebuilding. Build-time VITE_* variables give the
 * defaults. Every field is optional.
 */
export interface BasemapConfig {
  /** MapLibre style URL for light and dark themes, or "none" for a plain background. */
  light: string;
  dark: string;
  /** Extra attribution, if the style itself doesn't carry it. */
  attribution?: string;
}

/**
 * An extra map layer: a raster base map (e.g. satellite imagery) or an overlay drawn between the
 * base map and the data (e.g. terrain shading, ocean depth). Tiles must need no key.
 */
export interface MapLayerConfig {
  id: string;
  /** Shown in the map's layer picker. */
  name: string;
  /** "base" replaces the base map; "overlay" is drawn over it, under the data. */
  kind: "base" | "overlay";
  /** "raster": image tiles; "hillshade": elevation tiles drawn as shading. */
  type: "raster" | "hillshade";
  /** Tile URL templates ({z}/{x}/{y}, or {bbox-epsg-3857} for WMS). */
  tiles: string[];
  tileSize?: number;
  maxzoom?: number;
  /** For "hillshade": how heights are encoded in the tiles. */
  encoding?: "terrarium" | "mapbox";
  /** Overlay opacity, 0-1. */
  opacity?: number;
  /** Credit shown on the map (HTML allowed, as MapLibre renders it). */
  attribution: string;
}

export interface AppConfig {
  /** Where the static products live (the publish bucket's public URL). */
  staticBase: string;
  /** The API's base URL; empty when this deployment has no API. */
  apiBase: string;
  /** Region ids to offer. Empty: ask the API's /regions. */
  regions: string[];
  basemap: BasemapConfig;
  /** Extra base maps and overlays offered in each map's layer picker; [] offers none. */
  layers: MapLayerConfig[];
  /** AGPL §13: link to the source of the running version. */
  sourceUrl: string;
}

const env = import.meta.env;

/** OpenFreeMap needs no API key; its styles carry the OpenMapTiles / OpenStreetMap attribution. */
export const DEFAULT_BASEMAP: BasemapConfig = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
};

/**
 * Default extra layers: all keyless, credited on the map. Sentinel-2 cloudless (2018 and later)
 * is CC BY-NC-SA 4.0, which suits this non-commercial project; a commercial deployment must
 * replace it. Deployments can replace or remove any of these in /config.json ("layers").
 */
export const DEFAULT_LAYERS: MapLayerConfig[] = [
  {
    id: "satellite",
    name: "Satellite",
    kind: "base",
    type: "raster",
    tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg"],
    tileSize: 256,
    maxzoom: 15,
    attribution:
      '<a href="https://s2maps.eu" target="_blank" rel="noopener">Sentinel-2 cloudless 2021</a> by EOX IT Services GmbH (contains modified Copernicus Sentinel data 2021), CC BY-NC-SA 4.0',
  },
  {
    id: "terrain",
    name: "Terrain shading",
    kind: "overlay",
    type: "hillshade",
    tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
    tileSize: 256,
    maxzoom: 15,
    encoding: "terrarium",
    attribution:
      'Terrain: <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noopener">Mapzen terrain tiles</a> (SRTM, GMTED, ETOPO1 and others)',
  },
  {
    id: "depth",
    name: "Ocean depth",
    kind: "overlay",
    type: "raster",
    tiles: [
      "https://wms.gebco.net/mapserv?service=WMS&version=1.3.0&request=GetMap&layers=GEBCO_LATEST&styles=&crs=EPSG:3857&bbox={bbox-epsg-3857}&width=256&height=256&format=image/png",
    ],
    tileSize: 256,
    opacity: 0.55,
    attribution:
      'Depth: <a href="https://www.gebco.net" target="_blank" rel="noopener">GEBCO</a> Compilation Group, GEBCO grid',
  },
];

export const DEFAULT_CONFIG: AppConfig = {
  staticBase: env.VITE_STATIC_BASE ?? "/data",
  apiBase: env.VITE_API_BASE ?? "/api",
  regions: (env.VITE_REGIONS ?? "").split(",").map((s: string) => s.trim()).filter(Boolean),
  basemap:
    env.VITE_BASEMAP_STYLE === "none"
      ? { light: "none", dark: "none" }
      : {
          light: env.VITE_BASEMAP_STYLE ?? DEFAULT_BASEMAP.light,
          dark: env.VITE_BASEMAP_STYLE_DARK ?? env.VITE_BASEMAP_STYLE ?? DEFAULT_BASEMAP.dark,
        },
  layers: DEFAULT_LAYERS,
  sourceUrl: env.VITE_SOURCE_URL ?? "https://github.com/alexngai/wildlife-radar",
};

function validLayer(v: unknown): v is MapLayerConfig {
  if (!v || typeof v !== "object") return false;
  const l = v as Partial<MapLayerConfig>;
  return (
    typeof l.id === "string" &&
    typeof l.name === "string" &&
    (l.kind === "base" || l.kind === "overlay") &&
    (l.type === "raster" || l.type === "hillshade") &&
    Array.isArray(l.tiles) &&
    l.tiles.length > 0 &&
    l.tiles.every((t) => typeof t === "string") &&
    typeof l.attribution === "string"
  );
}

export function mergeConfig(base: AppConfig, override: unknown): AppConfig {
  if (!override || typeof override !== "object") return base;
  const o = override as Partial<Omit<AppConfig, "layers">> & { basemap?: Partial<BasemapConfig> | "none"; layers?: unknown };
  const str = (v: unknown, d: string) => (typeof v === "string" ? v : d);
  let basemap = base.basemap;
  if (o.basemap === "none") basemap = { light: "none", dark: "none" };
  else if (o.basemap && typeof o.basemap === "object") {
    basemap = {
      light: str(o.basemap.light, base.basemap.light),
      dark: str(o.basemap.dark, str(o.basemap.light, base.basemap.dark)),
      attribution: typeof o.basemap.attribution === "string" ? o.basemap.attribution : base.basemap.attribution,
    };
  }
  return {
    staticBase: str(o.staticBase, base.staticBase),
    apiBase: str(o.apiBase, base.apiBase),
    regions: Array.isArray(o.regions) ? o.regions.filter((r): r is string => typeof r === "string") : base.regions,
    basemap,
    layers: Array.isArray(o.layers) ? o.layers.filter(validLayer) : base.layers,
    sourceUrl: str(o.sourceUrl, base.sourceUrl),
  };
}

export async function loadConfig(fetcher: typeof fetch = fetch): Promise<AppConfig> {
  try {
    const res = await fetcher("/config.json", { cache: "no-cache" });
    if (!res.ok) return DEFAULT_CONFIG;
    return mergeConfig(DEFAULT_CONFIG, await res.json());
  } catch {
    return DEFAULT_CONFIG;
  }
}
