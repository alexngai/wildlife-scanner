/**
 * Static products, format 2 (docs/design/static-products.md). The data session owns the
 * format; these types mirror it. Everything here is already policy-filtered upstream.
 */

export const SUPPORTED_FORMAT = 4;

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
  places: Record<string, PlaceRef>;
  /** How to build photo URLs; absent when the region publishes no photos. */
  photos?: PhotoTemplates | null;
}

export type TaxonMode = "forecast" | "awareness";

/**
 * A representative photo for a taxon (format 4): an openly licensed iNaturalist photo, by id.
 * Its URLs are built from the index's `photos` templates; the credit must be shown with it.
 */
export interface TaxonPhoto {
  id: number;
  /** As the source stores it ("jpg", "jpeg", "JPG", "png", …); empty for some old uploads. */
  ext: string;
  /** Licence code, e.g. "cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa". */
  license: string;
  /** Credit as the source gives it, e.g. "(c) Jane Doe, some rights reserved (CC BY)". */
  attribution: string;
}

/** URL templates for photos, in index.json: `{id}`, `{size}` and `{ext}` are filled in. */
export interface PhotoTemplates {
  /** e.g. "https://inaturalist-open-data.s3.amazonaws.com/photos/{id}/{size}.{ext}" */
  image: string;
  /** The photo's page at its source, e.g. "https://www.inaturalist.org/photos/{id}". */
  page?: string | null;
  sizes: { thumb: string; medium: string };
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
  /** The species' map file, relative to the region root; absent when nothing is mapped. */
  map?: string;
  /**
   * The regional season: one level 0-9 per ISO week, relative to the species' own peak; null
   * for withheld weeks. Only open and generalized species, weekly segments.
   */
  season?: (number | null)[] | null;
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

/** One ISO week of a place's lists (`places/<place>.<key>/wNN.json`). */
export interface PlaceWeek {
  format?: number;
  week: number;
  groups: Record<string, PlaceWeekGroup>;
  awareness: string[];
  area_fallback: string[];
}

/** A place header (`places/<place>.<key>.json`): what every week shares. */
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
  /** `weeks[w - 1]` is the path of ISO week w's file, relative to the region root. */
  weeks: string[];
}
