import { usablePhoto, type ShownPhoto } from "./lib/photos";
import { useMemo } from "react";
import { useServices } from "./context";
import { useAsync } from "./lib/useAsync";
import type { RegionInfo, StaticIndex } from "./products/types";

const LAST_REGION = "wildlife-radar:region";

export function rememberRegion(id: string): void {
  try {
    localStorage.setItem(LAST_REGION, id);
  } catch {
    // ignore
  }
}

export function lastRegion(): string | null {
  try {
    return localStorage.getItem(LAST_REGION);
  } catch {
    return null;
  }
}

export interface RegionEntry {
  id: string;
  info: RegionInfo | null;
  index: StaticIndex | null;
}

/** Regions offered: from config, else from the API's /regions; each with its static index. */
export function useRegions() {
  const { config, products, api } = useServices();
  return useAsync(async (): Promise<RegionEntry[]> => {
    let ids = config.regions;
    let fromApi: Record<string, RegionInfo> = {};
    if (ids.length === 0 && api.enabled) {
      try {
        const regions = await api.regions();
        ids = regions.map((r) => r.region);
        fromApi = Object.fromEntries(regions.map((r) => [r.region, { id: r.region, name: r.name, bbox: r.bbox }]));
      } catch {
        ids = [];
      }
    }
    return Promise.all(
      ids.map(async (id) => {
        try {
          const index = await products.index(id);
          return { id, info: index.region, index };
        } catch {
          return { id, info: fromApi[id] ?? null, index: null };
        }
      }),
    );
  }, [config, products, api]);
}

export function useRegionIndex(region: string) {
  const { products } = useServices();
  return useAsync(() => products.index(region), [products, region]);
}

export function useTaxa(region: string) {
  const { products } = useServices();
  return useAsync(() => products.taxa(region), [products, region]);
}

/** Usable photos by taxon id, from taxa.json and the index's URL templates (empty until both load). */
export function usePhotos(region: string): Map<string, ShownPhoto> {
  const { products } = useServices();
  const taxa = useTaxa(region);
  const index = useRegionIndex(region);
  return useMemo(() => {
    const out = new Map<string, ShownPhoto>();
    if (taxa?.status !== "ok" || index?.status !== "ok") return out;
    const templates = index.data.photos;
    for (const t of taxa.data) {
      const p = usablePhoto(t.photo, templates, (path) => products.assetUrl(region, path));
      if (p) out.set(t.id, p);
    }
    return out;
  }, [taxa, index, products, region]);
}
