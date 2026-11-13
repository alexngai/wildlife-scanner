/**
 * Typed client for the wildlife-radar API. Types are generated from the API's OpenAPI schema
 * (`npm run gen:api`, from web/api/openapi.json). A 404 always means "not available": unknown
 * and withheld species are indistinguishable by design.
 */
import { FetchError, NotAvailableError } from "../lib/errors";
import { roundCoord } from "../lib/geo";
import type { components } from "./schema";

export type Schemas = components["schemas"];
export type Forecast = Schemas["Forecast"];
export type HourlyForecast = Schemas["HourlyForecast"];
export type RecentActivity = Schemas["RecentActivity"];
export type RecentItem = Schemas["RecentItem"];
export type PlaceLists = Schemas["PlaceLists"];
export type Calendar = Schemas["Calendar"];
export type Driver = Schemas["Driver"];

export interface TimingCategory {
  category: string;
  records: number;
  group_records: number;
  index: number | null;
  ci: [number, number] | null;
}

export interface Timing {
  signals: Record<string, TimingCategory[]>;
  hypotheses: { term: string; signal: string; expected: string; peak: string; verdict: string }[];
  note: string;
}

export interface ApiRegion {
  region: string;
  name: string;
  bbox: [number, number, number, number];
}

export interface SourceInfo {
  source_id: string;
  name: string;
  attribution: string;
  terms_url: string;
}

/** Where to forecast for: a published place, or a point (rounded before sending). */
export type Where = { placeId: string } | { lat: number; lon: number };

function whereParams(where: Where): Record<string, string> {
  if ("placeId" in where) return { place_id: where.placeId };
  return { lat: String(roundCoord(where.lat)), lon: String(roundCoord(where.lon)) };
}

export class ApiClient {
  constructor(
    readonly base: string,
    private readonly fetcher: typeof fetch = (...args) => fetch(...args),
  ) {}

  get enabled(): boolean {
    return this.base.length > 0;
  }

  private async get<T>(path: string, params: Record<string, string | undefined> = {}): Promise<T> {
    if (!this.enabled) throw new NotAvailableError();
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, v);
    const q = qs.toString();
    const url = `${this.base.replace(/\/+$/, "")}${path}${q ? `?${q}` : ""}`;
    const res = await this.fetcher(url, { headers: { Accept: "application/json" } });
    if (res.status === 404) throw new NotAvailableError();
    if (!res.ok) throw new FetchError(res.status, url);
    return (await res.json()) as T;
  }

  regions(): Promise<ApiRegion[]> {
    return this.get("/regions");
  }

  sources(): Promise<SourceInfo[]> {
    return this.get("/sources");
  }

  forecast(taxonId: string, where: Where, date?: string): Promise<Forecast> {
    return this.get(`/species/${encodeURIComponent(taxonId)}/forecast`, { ...whereParams(where), date });
  }

  hourly(taxonId: string, where: Where, date?: string): Promise<HourlyForecast> {
    return this.get(`/species/${encodeURIComponent(taxonId)}/forecast/hourly`, { ...whereParams(where), date });
  }

  timing(taxonId: string, region?: string): Promise<Timing> {
    return this.get(`/species/${encodeURIComponent(taxonId)}/timing`, { region });
  }

  placeRecent(placeId: string, date?: string): Promise<RecentActivity> {
    return this.get(`/places/${encodeURIComponent(placeId)}/recent`, { date });
  }

  nearbyRecent(lat: number, lon: number, date?: string): Promise<RecentActivity> {
    return this.get("/nearby/recent", { lat: String(roundCoord(lat)), lon: String(roundCoord(lon)), date });
  }

  /** Lists at a point. The life list is deliberately not sent; "new for you" is computed locally. */
  nearbyLists(lat: number, lon: number, date?: string): Promise<PlaceLists> {
    return this.get("/nearby", { lat: String(roundCoord(lat)), lon: String(roundCoord(lon)), date });
  }
}
