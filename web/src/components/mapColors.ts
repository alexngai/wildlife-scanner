/**
 * Sequential ramps for chance per outing (bins in lib/maps P_BINS). Light theme: pale → dark
 * (more = darker); dark theme: dim → bright. Both are viridis-derived, so they stay readable
 * for common colour-vision deficiencies.
 */
const LIGHT = ["#fde725", "#a0da39", "#4ac16d", "#1fa187", "#277f8e", "#3a528b"];
const DARK = ["#3a528b", "#277f8e", "#1fa187", "#4ac16d", "#a0da39", "#fde725"];

export function rampFor(theme: "light" | "dark"): string[] {
  return theme === "dark" ? DARK : LIGHT;
}

/**
 * Diverging ramp for "compared with the wider area" (bins in lib/maps LIFT_BINS): purple below,
 * neutral grey about the same, orange above. Purple–orange stays distinct for red–green colour
 * vision deficiencies.
 */
const LIFT_LIGHT = ["#5e3c99", "#b2abd2", "#d9d9d9", "#fdb863", "#e66101"];
const LIFT_DARK = ["#8e6cc9", "#6d6491", "#555a61", "#b9813a", "#ff8a3d"];

export function liftRampFor(theme: "light" | "dark"): string[] {
  return theme === "dark" ? LIFT_DARK : LIFT_LIGHT;
}

export type MapMetric = "chance" | "lift";
