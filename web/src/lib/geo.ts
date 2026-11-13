import type { PlaceRef, RegionInfo } from "../products/types";

/**
 * Round a location before it leaves the device. Three decimals (~100 m) is finer than any
 * published cell (≥1.4 km) but avoids sending a precise position.
 */
export function roundCoord(value: number, decimals = 3): number {
  const f = 10 ** decimals;
  return Math.round(value * f) / f;
}

export function distanceKm(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const R = 6371;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export function inBbox(region: RegionInfo, lat: number, lon: number): boolean {
  const [w, s, e, n] = region.bbox;
  return lon >= w && lon <= e && lat >= s && lat <= n;
}

/** The smallest region containing the point (as the API does). */
export function regionForPoint<T extends RegionInfo>(regions: T[], lat: number, lon: number): T | null {
  const area = (r: RegionInfo) => (r.bbox[2] - r.bbox[0]) * (r.bbox[3] - r.bbox[1]);
  return [...regions].filter((r) => inBbox(r, lat, lon)).sort((a, b) => area(a) - area(b))[0] ?? null;
}

export function nearestPlaces(
  places: Record<string, PlaceRef>,
  point: { lat: number; lon: number },
  limit = 5,
): { id: string; place: PlaceRef; km: number }[] {
  return Object.entries(places)
    .map(([id, place]) => ({ id, place, km: distanceKm(point, place) }))
    .sort((a, b) => a.km - b.km)
    .slice(0, limit);
}
