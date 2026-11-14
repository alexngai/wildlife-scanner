/**
 * The viewer's map-layer choice (base map, overlays, data opacity), shared by every map and
 * remembered in this browser only. A convenience: if storage is unavailable, the defaults apply.
 */
import { useSyncExternalStore } from "react";
import type { MapLayerConfig } from "../config";

/** "map": the configured vector base map; "plain": no base map; otherwise a base layer's id. */
export type BaseChoice = string;

export interface LayerChoice {
  base: BaseChoice;
  overlays: string[];
  /** Opacity of the data cells, 0.2-1 (1 = as designed). */
  dataOpacity: number;
}

const KEY = "wildlife-radar:map-layers:v1";
export const DEFAULT_CHOICE: LayerChoice = { base: "map", overlays: [], dataOpacity: 1 };

const listeners = new Set<() => void>();
let snapshot: LayerChoice | null = null;

function read(): LayerChoice {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_CHOICE;
    const v = JSON.parse(raw) as Partial<LayerChoice>;
    return {
      base: typeof v.base === "string" ? v.base : DEFAULT_CHOICE.base,
      overlays: Array.isArray(v.overlays) ? v.overlays.filter((x): x is string => typeof x === "string") : [],
      dataOpacity: clampOpacity(Number(v.dataOpacity)),
    };
  } catch {
    return DEFAULT_CHOICE;
  }
}

export function clampOpacity(v: number): number {
  return Number.isFinite(v) ? Math.min(1, Math.max(0.2, v)) : 1;
}

export function getLayerChoice(): LayerChoice {
  if (snapshot === null) snapshot = read();
  return snapshot;
}

export function setLayerChoice(next: LayerChoice): void {
  snapshot = { ...next, dataOpacity: clampOpacity(next.dataOpacity) };
  try {
    localStorage.setItem(KEY, JSON.stringify(snapshot));
  } catch {
    // Not remembered; the choice still applies on this page.
  }
  listeners.forEach((l) => l());
}

/** For tests. */
export function resetLayerChoice(): void {
  snapshot = null;
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useLayerChoice(): LayerChoice {
  return useSyncExternalStore(subscribe, getLayerChoice, getLayerChoice);
}

/** The choice limited to what this deployment offers (unknown ids fall back to defaults). */
export function effectiveChoice(choice: LayerChoice, layers: MapLayerConfig[], hasBasemap: boolean): LayerChoice {
  const bases = new Set(layers.filter((l) => l.kind === "base").map((l) => l.id));
  const overlays = new Set(layers.filter((l) => l.kind === "overlay").map((l) => l.id));
  let base = choice.base;
  if (base === "map" && !hasBasemap) base = "plain";
  if (base !== "map" && base !== "plain" && !bases.has(base)) base = hasBasemap ? "map" : "plain";
  return { base, overlays: choice.overlays.filter((o) => overlays.has(o)), dataOpacity: choice.dataOpacity };
}
