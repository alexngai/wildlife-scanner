/**
 * "Today's conditions" over a few map cells: each cell's forecast for a day against its usual
 * chance for the week (both as the API publishes them), and which factors drive the change.
 */
import type { Forecast } from "../api/client";
import { oddsMultiplier } from "./format";

export interface CellForecast {
  cell: string;
  lat: number;
  lon: number;
  forecast: Forecast;
}

/** Below / about / above usual, with the same thresholds as the "compared" view. */
export type Direction = -1 | 0 | 1;

export function directionOf(ratio: number | null): Direction {
  if (ratio === null) return 0;
  if (ratio >= 1.1) return 1;
  if (ratio <= 1 / 1.1) return -1;
  return 0;
}

/** Today's chance against the usual chance for the week; null when either is missing. */
export function todayRatio(f: Forecast): number | null {
  const usual = f.p_level0;
  if (f.p === null || f.p === undefined || usual === null || usual === undefined || usual <= 0) return null;
  return f.p / usual;
}

export interface FactorSummary {
  signal: string;
  /** Cells where the factor raises / lowers the odds. */
  up: number;
  down: number;
  /** Typical odds multiplier across the cells (geometric mean). */
  multiplier: number;
  hypothesis: boolean;
}

export interface ConditionsSummary {
  cells: number;
  up: number;
  down: number;
  same: number;
  /** Cells whose forecast is the usual chance only (no daily factors modelled). */
  baselineOnly: number;
  factors: FactorSummary[];
}

export function summarizeConditions(results: CellForecast[]): ConditionsSummary {
  const out: ConditionsSummary = { cells: results.length, up: 0, down: 0, same: 0, baselineOnly: 0, factors: [] };
  const bySignal = new Map<string, { up: number; down: number; sum: number; n: number; hypothesis: boolean }>();
  for (const { forecast: f } of results) {
    if (f.level === 0 && (f.drivers ?? []).length === 0) out.baselineOnly += 1;
    const d = directionOf(todayRatio(f));
    if (d > 0) out.up += 1;
    else if (d < 0) out.down += 1;
    else out.same += 1;
    for (const drv of f.drivers ?? []) {
      const s = bySignal.get(drv.signal) ?? { up: 0, down: 0, sum: 0, n: 0, hypothesis: false };
      if (drv.contribution > 0.01) s.up += 1;
      else if (drv.contribution < -0.01) s.down += 1;
      s.sum += drv.contribution;
      s.n += 1;
      s.hypothesis ||= Boolean(drv.hypothesis);
      bySignal.set(drv.signal, s);
    }
  }
  out.factors = [...bySignal.entries()]
    .map(([signal, s]) => ({
      signal,
      up: s.up,
      down: s.down,
      multiplier: oddsMultiplier(s.sum / s.n),
      hypothesis: s.hypothesis,
    }))
    .sort((a, b) => Math.abs(Math.log(b.multiplier)) - Math.abs(Math.log(a.multiplier)));
  return out;
}
