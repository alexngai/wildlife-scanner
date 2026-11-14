/**
 * "Today vs usual" on the map: each cell's forecast for a day against its usual chance for the
 * week (both as the API publishes them, from one /forecast/map call), and which factors drive
 * the change across cells.
 */
import type { CellForecastApi, MapForecast } from "../api/client";
import { oddsMultiplier } from "./format";
import { liftBinFor } from "./maps";

/** Below / about / above usual. */
export type Direction = -1 | 0 | 1;

export function directionOf(ratio: number | null): Direction {
  if (ratio === null) return 0;
  if (ratio >= 1.1) return 1;
  if (ratio <= 1 / 1.1) return -1;
  return 0;
}

/** The day's chance against the usual chance for the week; null when either is missing. */
export function todayRatio(c: { p?: number | null; p_level0?: number | null }): number | null {
  const usual = c.p_level0;
  if (c.p === null || c.p === undefined || usual === null || usual === undefined || usual <= 0) return null;
  return c.p / usual;
}

export interface TodayCell {
  p: number;
  usual: number;
  ratio: number | null;
  /** Colour bin on the diverging ramp (as the "compared" view), or -1. */
  bin: number;
}

/** Per-cell values to colour the map by. */
export function todayByCell(f: MapForecast): Map<string, TodayCell> {
  const out = new Map<string, TodayCell>();
  for (const c of f.cells ?? []) {
    const ratio = todayRatio(c);
    out.set(c.cell, { p: c.p, usual: c.p_level0, ratio, bin: ratio === null ? -1 : liftBinFor(ratio) });
  }
  return out;
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
  /** True when no daily factors are modelled (every cell is its usual chance). */
  baselineOnly: boolean;
  factors: FactorSummary[];
}

export function summarizeConditions(level: number, cells: CellForecastApi[]): ConditionsSummary {
  const out: ConditionsSummary = { cells: cells.length, up: 0, down: 0, same: 0, baselineOnly: false, factors: [] };
  const bySignal = new Map<string, { up: number; down: number; sum: number; n: number; hypothesis: boolean }>();
  let anyDriver = false;
  for (const c of cells) {
    const d = directionOf(todayRatio(c));
    if (d > 0) out.up += 1;
    else if (d < 0) out.down += 1;
    else out.same += 1;
    for (const drv of c.drivers ?? []) {
      anyDriver = true;
      const s = bySignal.get(drv.signal) ?? { up: 0, down: 0, sum: 0, n: 0, hypothesis: false };
      if (drv.contribution > 0.01) s.up += 1;
      else if (drv.contribution < -0.01) s.down += 1;
      s.sum += drv.contribution;
      s.n += 1;
      s.hypothesis ||= Boolean(drv.hypothesis);
      bySignal.set(drv.signal, s);
    }
  }
  out.baselineOnly = level === 0 && !anyDriver;
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
