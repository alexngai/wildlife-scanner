/**
 * One view model for place lists, built from the static place file (by week) or from the API
 * (`/places/{id}/lists`, `/nearby`). "New for you" is computed here from the published lists
 * and the life list kept in this browser, so the life list never leaves the device.
 */
import type { components } from "../api/schema";
import type { License, PlaceFile, PlaceItemRow, PlaceWeek } from "../products/types";
import { capitalize } from "./format";
import { normalizeConfidence, type ConfidenceLevel } from "./policy";

export interface ListItem {
  taxonId: string;
  name: string;
  scientificName: string | null;
  p: number;
  lift: number | null;
  seasonalIndex: number | null;
  confidence: ConfidenceLevel;
  resolutionKm: number | null;
  /** Estimated from a coarser area than the place itself. */
  coarser: boolean;
}

export interface GroupView {
  id: string;
  label: string;
  method: string;
  license: License | null;
  mostLikely: ListItem[];
  specialHere: ListItem[];
  peakingNow: ListItem[];
}

export interface AwarenessView {
  taxonId: string;
  name: string;
  scientificName: string | null;
}

export interface ListsView {
  week: number;
  groups: GroupView[];
  awareness: AwarenessView[];
  awarenessMessage: string;
  label: string | null;
}

export const DEFAULT_AWARENESS_MESSAGE =
  "Present in this wider area. Shown for awareness only: no location or timing details are given for sensitive species.";

function fieldIndex(fields: string[], name: string, fallback: number): number {
  const i = fields.indexOf(name);
  return i >= 0 ? i : fallback;
}

/** One week of a place's lists: the header (names, groups, fields) and that week's file. */
export function listsFromPlace(file: PlaceFile, w: PlaceWeek): ListsView {
  const f = file.item_fields;
  const idx = {
    id: fieldIndex(f, "taxon_id", 0),
    p: fieldIndex(f, "p", 1),
    lift: fieldIndex(f, "lift_x100", 2),
    si: fieldIndex(f, "seasonal_index_x100", 3),
    conf: fieldIndex(f, "confidence", 4),
    res: fieldIndex(f, "res", 5),
  };
  const fallback = new Set(w.area_fallback ?? []);
  const item = (row: PlaceItemRow): ListItem => {
    const id = String(row[idx.id]);
    const t = file.taxa[id];
    const lift = row[idx.lift] as number | null;
    const si = row[idx.si] as number | null;
    const res = row[idx.res] as number;
    return {
      taxonId: id,
      name: capitalize(t?.common_name || t?.scientific_name || id),
      scientificName: t?.scientific_name ?? null,
      p: (row[idx.p] as number) / file.p_scale,
      lift: lift === null ? null : lift / 100,
      seasonalIndex: si === null ? null : si / 100,
      confidence: normalizeConfidence(row[idx.conf] as string),
      resolutionKm: file.resolutions_km[res] ?? null,
      coarser: res > 0 || fallback.has(id),
    };
  };
  const groups: GroupView[] = Object.entries(w.groups).map(([id, g]) => {
    const info = file.groups[id];
    return {
      id,
      label: info?.label ?? id,
      method: info?.method ?? "",
      license: info?.license ?? null,
      mostLikely: (g.most_likely ?? []).map(item),
      specialHere: (g.special_here ?? []).map(item),
      peakingNow: (g.peaking_now ?? []).map(item),
    };
  });
  return {
    week: w.week,
    groups,
    awareness: (w.awareness ?? []).map((id) => {
      const t = file.taxa[id];
      return {
        taxonId: id,
        name: capitalize(t?.common_name || t?.scientific_name || id),
        scientificName: t?.scientific_name ?? null,
      };
    }),
    awarenessMessage: file.awareness_message || DEFAULT_AWARENESS_MESSAGE,
    label: null,
  };
}

type ApiLists = components["schemas"]["PlaceLists"];
type ApiItem = components["schemas"]["PlaceItem"];

export function listsFromApi(lists: ApiLists): ListsView {
  const fallback = new Set(lists.area_fallback ?? []);
  const item = (i: ApiItem): ListItem => ({
    taxonId: i.taxon_id,
    name: capitalize(i.common_name || i.scientific_name || i.taxon_id),
    scientificName: i.scientific_name ?? null,
    p: i.p,
    lift: i.lift ?? null,
    seasonalIndex: i.seasonal_index ?? null,
    confidence: normalizeConfidence(i.confidence as string),
    resolutionKm: i.resolution_km,
    coarser: fallback.has(i.taxon_id),
  });
  return {
    week: lists.week,
    groups: (lists.groups ?? []).map((g) => ({
      id: g.group,
      label: g.label,
      method: g.method,
      license: (g.license as License | null | undefined) ?? null,
      mostLikely: (g.most_likely ?? []).map(item),
      specialHere: (g.special_here ?? []).map(item),
      peakingNow: (g.peaking_now ?? []).map(item),
    })),
    awareness: (lists.awareness ?? []).map((a) => ({
      taxonId: a.taxon_id,
      name: capitalize(a.common_name || a.scientific_name || a.taxon_id),
      scientificName: a.scientific_name ?? null,
    })),
    awarenessMessage: lists.awareness?.[0]?.message ?? DEFAULT_AWARENESS_MESSAGE,
    label: lists.label ?? null,
  };
}

/**
 * Species on this group's published lists that are not on the life list, most likely first.
 * Only published list items are used, so nothing beyond what's published is revealed.
 */
export function newForYou(group: GroupView, seen: ReadonlySet<string>, limit = 10): ListItem[] {
  const byId = new Map<string, ListItem>();
  for (const it of [...group.mostLikely, ...group.peakingNow, ...group.specialHere]) {
    if (!seen.has(it.taxonId) && !byId.has(it.taxonId)) byId.set(it.taxonId, it);
  }
  return [...byId.values()].sort((a, b) => b.p - a.p).slice(0, limit);
}
