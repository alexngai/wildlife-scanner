/**
 * Place hotspots for one week and one effort group, from the published place lists.
 *
 * Chances are only comparable within one effort group (one method), so places are compared
 * group by group, never summed across groups. The score is "likely species per outing": the sum
 * of the published chances in the group's most-likely list. Lists are capped (top 20), so this is
 * a lower bound, and the same cap applies to every place.
 */
import type { PlaceFile } from "../products/types";
import { listsFromPlaceFile, type ListItem } from "./lists";

export interface HotspotPlace {
  id: string;
  name: string;
  lat: number;
  lon: number;
  file: PlaceFile;
}

export interface HotspotRow {
  id: string;
  name: string;
  lat: number;
  lon: number;
  /** Likely species per outing (sum of the most-likely list's chances); null when the place has no list for the group. */
  score: number | null;
  /** How many species in the list are peaking now. */
  peaking: number;
  /** The species most special to this place this week (highest lift), if any. */
  special: ListItem | null;
}

export interface GroupOption {
  id: string;
  label: string;
  /** Places with a list for this group in the week. */
  places: number;
}

/** Effort groups with lists in `week`: most widely available first, then the busiest. */
export function hotspotGroups(places: HotspotPlace[], week: number): GroupOption[] {
  const seen = new Map<string, GroupOption & { total: number }>();
  for (const p of places) {
    for (const g of listsFromPlaceFile(p.file, week)?.groups ?? []) {
      if (g.mostLikely.length === 0) continue;
      const o = seen.get(g.id) ?? { id: g.id, label: g.label, places: 0, total: 0 };
      o.places += 1;
      o.total += g.mostLikely.reduce((sum, i) => sum + i.p, 0);
      seen.set(g.id, o);
    }
  }
  // Widest coverage first, then the group with the most activity (more to tell places apart).
  return [...seen.values()]
    .sort((a, b) => b.places - a.places || b.total - a.total || a.label.localeCompare(b.label))
    .map(({ id, label, places: n }) => ({ id, label, places: n }));
}

export function hotspots(places: HotspotPlace[], week: number, groupId: string): HotspotRow[] {
  return places
    .map((p) => {
      const g = listsFromPlaceFile(p.file, week)?.groups.find((x) => x.id === groupId);
      const score = g && g.mostLikely.length > 0 ? g.mostLikely.reduce((s, i) => s + i.p, 0) : null;
      const special =
        g?.specialHere.filter((i) => i.lift !== null && !i.coarser).sort((a, b) => (b.lift ?? 0) - (a.lift ?? 0))[0] ??
        null;
      return { id: p.id, name: p.name, lat: p.lat, lon: p.lon, score, peaking: g?.peakingNow.length ?? 0, special };
    })
    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
}
