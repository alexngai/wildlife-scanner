/**
 * Display policy. The data is filtered upstream; these rules govern how the app shows it:
 * - withheld and unknown species look the same ("not available");
 * - awareness-mode species show presence only, never numbers or timing;
 * - "insufficient" estimates are shown as "not enough data", never as zero;
 * - recent evidence is published with a delay, which is always shown.
 */
import type { ConfidenceCode, TaxonMode } from "../products/types";

export const NOT_AVAILABLE_TEXT = "Not available";
export const NOT_AVAILABLE_DETAIL =
  "There is no published information for this request. Some species are not shown at all to protect them.";

/** Tier 2 and above (coarse / awareness) never show numbers. */
export const AWARENESS_TIER = 2;

export function isAwareness(mode: TaxonMode | undefined, tier: number | undefined): boolean {
  return mode === "awareness" || (tier ?? 0) >= AWARENESS_TIER;
}

/**
 * Minimum delay before recent sightings are published, per policy tier (mirrors
 * src/wildlife_radar/policy/tiers.py; see web/NEEDS.md about publishing these in index.json).
 */
export const TIER_DELAY: Record<number, string> = {
  0: "24 hours",
  1: "7 days",
  2: "30 days",
};

export function delayText(tier: number): string {
  return TIER_DELAY[tier] ?? "an extended period";
}

export const TIER_NAME: Record<number, string> = {
  0: "Openly mapped",
  1: "Generalized",
  2: "Awareness only",
};

export type ConfidenceLevel = "high" | "medium" | "low" | "insufficient" | "none";

const CODES: Record<string, ConfidenceLevel> = {
  h: "high",
  m: "medium",
  l: "low",
  i: "insufficient",
  "-": "none",
};

export function confidenceLevel(code: string | undefined): ConfidenceLevel {
  return (code && CODES[code]) || "none";
}

/** API confidence values are already words; accept both. */
export function normalizeConfidence(value: string | ConfidenceCode | undefined): ConfidenceLevel {
  if (!value) return "none";
  if (value.length === 1) return confidenceLevel(value);
  return (["high", "medium", "low", "insufficient"] as const).find((c) => c === value) ?? "none";
}

export const CONFIDENCE_TEXT: Record<ConfidenceLevel, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
  insufficient: "Not enough data",
  none: "No estimate",
};

export const LEVEL_TEXT: Record<number, string> = {
  0: "Seasonal baseline",
  1: "Adjusted for today's conditions",
  2: "Adjusted for conditions and recent sightings",
};
