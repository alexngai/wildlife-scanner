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

export interface AppConfig {
  /** Where the static products live (the publish bucket's public URL). */
  staticBase: string;
  /** The API's base URL; empty when this deployment has no API. */
  apiBase: string;
  /** Region ids to offer. Empty: ask the API's /regions. */
  regions: string[];
  basemap: BasemapConfig;
  /** AGPL §13: link to the source of the running version. */
  sourceUrl: string;
}

const env = import.meta.env;

/** OpenFreeMap needs no API key; its styles carry the OpenMapTiles / OpenStreetMap attribution. */
export const DEFAULT_BASEMAP: BasemapConfig = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
};

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
  sourceUrl: env.VITE_SOURCE_URL ?? "https://github.com/alexngai/wildlife-radar",
};

export function mergeConfig(base: AppConfig, override: unknown): AppConfig {
  if (!override || typeof override !== "object") return base;
  const o = override as Partial<AppConfig> & { basemap?: Partial<BasemapConfig> | "none" };
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
