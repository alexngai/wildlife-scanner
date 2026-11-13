/**
 * Species-map helpers over format-2 segments. Only published values are read: nothing is
 * interpolated between weeks or cells, and no cell finer than the segment's is produced.
 */
import { cellToBoundary, cellToParent, latLngToCell } from "h3-js";
import type { MapSegment, SpeciesMapFile } from "../products/types";
import { AWARENESS_TIER, confidenceLevel, type ConfidenceLevel } from "./policy";
import { monthOfWeek } from "./weeks";

export interface SegmentHit {
  segment: MapSegment;
  /** Index into segment.periods (and each p row / confidence string). */
  j: number;
  /** The period found (week or month). */
  period: number;
}

/** The segment and period index serving ISO week `week`, or null when the week is withheld. */
export function segmentForWeek(map: SpeciesMapFile, week: number, year = map.year_basis): SegmentHit | null {
  for (const segment of map.segments) {
    const period = segment.granularity === "month" ? monthOfWeek(year, week) : week;
    const j = segment.periods.indexOf(period);
    if (j >= 0) return { segment, j, period };
  }
  return null;
}

export function isPresenceOnly(segment: MapSegment): boolean {
  return segment.tier >= AWARENESS_TIER;
}

export interface CellValue {
  cell: string;
  /** Chance per outing (0-1); null when there is no number to show. */
  p: number | null;
  confidence: ConfidenceLevel;
  /** p compared with the published reference area (parent cell or region) for the same period. */
  lift?: number | null;
}

/** Cells for one period. "Insufficient" cells are kept (shown as "not enough data"). */
export function cellsForPeriod(segment: MapSegment, j: number, pScale: number): CellValue[] {
  const out: CellValue[] = [];
  segment.cells.forEach((cell, i) => {
    const confidence = confidenceLevel(segment.confidence[i]?.[j]);
    const raw = segment.p[i]?.[j] ?? null;
    if (confidence === "insufficient") {
      out.push({ cell, p: null, confidence });
      return;
    }
    if (raw === null || confidence === "none") return;
    out.push({ cell, p: raw / pScale, confidence, lift: liftFor(segment, i, j) });
  });
  return out;
}

/**
 * Presence-only view for awareness segments: cells with any published estimate in any period,
 * without numbers or timing.
 */
export function presenceCells(map: SpeciesMapFile): string[] {
  const cells = new Set<string>();
  for (const seg of map.segments) {
    if (!isPresenceOnly(seg)) continue;
    seg.cells.forEach((cell, i) => {
      if ((seg.p[i] ?? []).some((v) => v !== null && v > 0)) cells.add(cell);
    });
  }
  return [...cells];
}

/** Lift ("how special is this cell"): p / ref.p[parent][j]. */
export function liftFor(segment: MapSegment, i: number, j: number): number | null {
  const raw = segment.p[i]?.[j];
  const cell = segment.cells[i];
  if (raw === null || raw === undefined || !cell) return null;
  const key = segment.ref.resolution === null ? "region" : cellToParent(cell, segment.ref.resolution);
  const ref = segment.ref.p[key]?.[j];
  if (!ref) return null;
  return raw / ref;
}

/** Colour bins for chance per outing; the same thresholds drive the legend. */
export const P_BINS = [0.01, 0.05, 0.1, 0.25, 0.5] as const;

export function binFor(p: number): number {
  let b = 0;
  for (const t of P_BINS) if (p >= t) b += 1;
  return b; // 0..5
}

export const BIN_LABELS = ["<1%", "1–5%", "5–10%", "10–25%", "25–50%", "≥50%"];

/** Colour bins for lift (a cell against its wider area); the same thresholds drive the legend. */
export const LIFT_BINS = [0.5, 0.8, 1.25, 2] as const;

export function liftBinFor(lift: number): number {
  let b = 0;
  for (const t of LIFT_BINS) if (lift >= t) b += 1;
  return b; // 0..4, 2 = about the same as the wider area
}

export const LIFT_LABELS = ["Under half", "Lower", "About the same", "Higher", "Over twice"];

export interface CellFeatureProps {
  cell: string;
  bin: number;
  p: number | null;
  confidence: ConfidenceLevel;
  insufficient: boolean;
  presence: boolean;
  /** Ratio to the wider area, or null when there's no reference. */
  lift: number | null;
  /** Lift colour bin, or -1 when there's no lift. */
  liftBin: number;
}

export interface FeatureCollection {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    id: number;
    properties: CellFeatureProps;
    geometry: { type: "Polygon"; coordinates: number[][][] };
  }[];
}

function polygon(cell: string): number[][][] {
  const ring = cellToBoundary(cell, true);
  return [ring];
}

export function toGeoJSON(values: CellValue[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: values.map((v, id) => ({
      type: "Feature",
      id,
      properties: {
        cell: v.cell,
        bin: v.p === null ? -1 : binFor(v.p),
        p: v.p,
        confidence: v.confidence,
        insufficient: v.confidence === "insufficient",
        presence: false,
        lift: v.lift ?? null,
        liftBin: v.lift === null || v.lift === undefined ? -1 : liftBinFor(v.lift),
      },
      geometry: { type: "Polygon", coordinates: polygon(v.cell) },
    })),
  };
}

export function presenceGeoJSON(cells: string[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: cells.map((cell, id) => ({
      type: "Feature",
      id,
      properties: { cell, bin: -1, p: null, confidence: "none", insufficient: false, presence: true, lift: null, liftBin: -1 },
      geometry: { type: "Polygon", coordinates: polygon(cell) },
    })),
  };
}

export interface CalendarPoint {
  /** Week (1-52) or month (1-12), per `granularity`. */
  period: number;
  p: number | null;
  confidence: ConfidenceLevel;
  /** True when this period is shown for awareness only (no number). */
  presenceOnly: boolean;
}

export interface CalendarSeries {
  granularity: "week" | "month";
  points: CalendarPoint[];
  /** Spatial basis: the cell used (or "region"), and its size. */
  basis: { cell: string | null; resolution_km: number | null };
}

/**
 * The calendar at a point (the row of the containing cell in each segment) or, with no point,
 * the regional calendar (`region_p`). Weeks with no segment are withheld and come back as
 * "none". Presence-only segments never contribute numbers.
 */
export function calendar(map: SpeciesMapFile, point: { lat: number; lon: number } | null): CalendarSeries {
  const allMonthly = map.segments.length > 0 && map.segments.every((s) => s.granularity === "month");
  const granularity = allMonthly ? "month" : "week";
  const n = granularity === "month" ? 12 : 52;
  const points: CalendarPoint[] = [];
  let basis: CalendarSeries["basis"] = { cell: null, resolution_km: null };
  for (let period = 1; period <= n; period++) {
    let found: CalendarPoint = { period, p: null, confidence: "none", presenceOnly: false };
    for (const seg of map.segments) {
      const segPeriod =
        seg.granularity === granularity ? period : granularity === "week" ? monthOfWeek(map.year_basis, period) : null;
      if (segPeriod === null) continue;
      const j = seg.periods.indexOf(segPeriod);
      if (j < 0) continue;
      if (isPresenceOnly(seg)) {
        found = { period, p: null, confidence: "none", presenceOnly: true };
        break;
      }
      if (point) {
        const cell = latLngToCell(point.lat, point.lon, seg.resolution);
        const i = seg.cells.indexOf(cell);
        if (basis.cell === null || basis.resolution_km !== seg.resolution_km) basis = { cell, resolution_km: seg.resolution_km };
        if (i < 0) {
          found = { period, p: null, confidence: "none", presenceOnly: false };
          break;
        }
        const confidence = confidenceLevel(seg.confidence[i]?.[j]);
        const raw = seg.p[i]?.[j] ?? null;
        found = {
          period,
          p: confidence === "insufficient" || raw === null ? null : raw / map.p_scale,
          confidence,
          presenceOnly: false,
        };
      } else {
        const raw = seg.region_p[j] ?? null;
        found = { period, p: raw === null ? null : raw / map.p_scale, confidence: raw === null ? "none" : "high", presenceOnly: false };
      }
      break;
    }
    points.push(found);
  }
  return { granularity, points, basis };
}

/** Best periods (highest published p), for "best weeks" summaries. */
export function bestPeriods(series: CalendarSeries, count = 3): CalendarPoint[] {
  return series.points
    .filter((pt) => pt.p !== null && pt.confidence !== "insufficient")
    .sort((a, b) => (b.p ?? 0) - (a.p ?? 0))
    .slice(0, count);
}

/** Bounding box [w, s, e, n] of a set of cells, for fitting the map. */
export function cellsBounds(cells: string[]): [number, number, number, number] | null {
  if (cells.length === 0) return null;
  let w = Infinity;
  let s = Infinity;
  let e = -Infinity;
  let n = -Infinity;
  for (const c of cells) {
    for (const [lat, lng] of cellToBoundary(c)) {
      w = Math.min(w, lng);
      e = Math.max(e, lng);
      s = Math.min(s, lat);
      n = Math.max(n, lat);
    }
  }
  return [w, s, e, n];
}
