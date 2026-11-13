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
