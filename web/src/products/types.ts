/**
 * Static products, format 2 (docs/design/static-products.md). The data session owns the
 * format; these types mirror it. Everything here is already policy-filtered upstream.
 */

export const SUPPORTED_FORMAT = 2;

/** h(igh), m(edium), l(ow), i(nsufficient), - (none). */
export type ConfidenceCode = "h" | "m" | "l" | "i" | "-";

export interface License {
  license_ids: string[];
  noncommercial: boolean;
  share_alike: boolean;
  fully_open: boolean;
  attribution: string[];
}

export interface RegionInfo {
  id: string;
  name: string;
  /** [lon_min, lat_min, lon_max, lat_max] */
  bbox: [number, number, number, number];
}

export interface PlaceRef {
  name: string;
  kind: string;
  lat: number;
  lon: number;
  file: string;
}

export interface StaticIndex {
  format: number;
  region: RegionInfo;
  version: string;
  baseline: { model_version: string; built_at: string };
  published_at?: string;
  year_basis: number;
  p_scale: number;
  paths_relative_to?: string;
  taxa: string;
  maps: Record<string, string>;
  places: Record<string, PlaceRef>;
}

export type TaxonMode = "forecast" | "awareness";

/**
 * A representative photo for a taxon, chosen when the data is published (NEEDS.md §15).
 * Only openly licensed photos are published; the credit must be shown with the image.
 */
export interface TaxonPhoto {
  /** Small square thumbnail: an absolute https URL, or a path relative to the region root. */
  url: string;
  /** A larger version (about 500 px), same rules as `url`. */
  url_medium?: string | null;
  /** Licence code, e.g. "cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa". */
  license: string;
  /** Credit as the source gives it, e.g. "(c) Jane Doe, some rights reserved (CC BY)". */
  attribution: string;
  /** The photo's page at its source (e.g. iNaturalist). */
  source_url?: string | null;
  /** Where it comes from, e.g. "iNaturalist". */
  source?: string | null;
}

export interface TaxonEntry {
  id: string;
  scientific_name: string | null;
  common_name: string | null;
  aliases: string[];
  group: string | null;
  tier: number;
  mode: TaxonMode;
  records: number;
  /** Absent or null when there's no usable photo. */
  photo?: TaxonPhoto | null;
}

export interface MapSegment {
  tier: number;
  granularity: "week" | "month";
  resolution: number;
  resolution_km: number;
  /** ISO weeks (1-52) or months (1-12), per granularity. */
  periods: number[];
  cells: string[];
  /** p[cell][period], integers to divide by p_scale; null = no estimate. */
  p: (number | null)[][];
  /** One string per cell, one character per period. */
  confidence: string[];
  ref: { resolution: number | null; p: Record<string, (number | null)[]> };
  region_p: (number | null)[];
}

export interface MapTaxon {
  taxon_id: string;
  scientific_name?: string | null;
  common_name?: string | null;
  group?: string | null;
  tier: number;
  mode?: TaxonMode;
  [key: string]: unknown;
}

export interface SpeciesMapFile {
  format: number;
  taxon: MapTaxon;
  effort_group: string;
  method: string;
  label: string;
  license: License;
  year_basis: number;
  p_scale: number;
  segments: MapSegment[];
}

/** A list row in `item_fields` order. */
export type PlaceItemRow = [string, number, number | null, number | null, ConfidenceCode, number];

export interface PlaceGroupInfo {
  taxon_group: string;
  effort_class: string;
  label: string;
  method: string;
  license: License;
}

export interface PlaceWeekGroup {
  most_likely?: PlaceItemRow[];
  special_here?: PlaceItemRow[];
  peaking_now?: PlaceItemRow[];
}

export interface PlaceWeek {
  week: number;
  groups: Record<string, PlaceWeekGroup>;
  awareness: string[];
  area_fallback: string[];
}

export interface PlaceFile {
  format: number;
  place: {
    place_id: string;
    name: string;
    kind: string;
    notes?: string | null;
    habitat?: string[];
    [key: string]: unknown;
  };
  year_basis: number;
  p_scale: number;
  item_fields: string[];
  resolutions_km: number[];
  awareness_message: string;
  taxa: Record<string, { scientific_name: string | null; common_name: string | null; group: string | null }>;
  groups: Record<string, PlaceGroupInfo>;
  weeks: PlaceWeek[];
}
