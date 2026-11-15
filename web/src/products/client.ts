import { FetchError, NotAvailableError } from "../lib/errors";
import type { PlaceFile, PlaceWeek, SpeciesMapFile, StaticIndex, TaxonEntry } from "./types";
import { adapt, DEFAULT_FORMATS, type FileKind, type FormatRegistry } from "./formats";

type Fetcher = typeof fetch;

function join(base: string, path: string): string {
  return `${base.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}

/**
 * Reads the static products of one or more regions:
 * `region=<id>/CURRENT` (no-cache) → `index.json` → everything else by path from the index.
 * Files other than CURRENT are immutable, so results are memoised for the session.
 */
export class StaticClient {
  private cache = new Map<string, Promise<unknown>>();

  constructor(
    private readonly base: string,
    private readonly fetcher: Fetcher = (...args) => fetch(...args),
    /** Readable formats and their adapters (formats.ts); tests pass their own. */
    private readonly formats: FormatRegistry = DEFAULT_FORMATS,
  ) {}

  private async getText(url: string, init?: RequestInit): Promise<string> {
    const res = await this.fetcher(url, init);
    if (res.status === 404 || res.status === 403) throw new NotAvailableError();
    if (!res.ok) throw new FetchError(res.status, url);
    return res.text();
  }

  private memo<T>(key: string, load: () => Promise<T>): Promise<T> {
    let hit = this.cache.get(key) as Promise<T> | undefined;
    if (!hit) {
      hit = load();
      this.cache.set(key, hit);
      // Don't keep failures: a later retry should refetch.
      hit.catch(() => this.cache.delete(key));
    }
    return hit;
  }

  /** A JSON file in the current format's shape (see formats.ts); `format` is for files without their own. */
  private json<T>(url: string, kind: FileKind, format?: number): Promise<T> {
    return this.memo(url, async () => {
      const data = JSON.parse(await this.getText(url)) as unknown;
      const own =
        data && typeof data === "object" && !Array.isArray(data) ? (data as { format?: unknown }).format : undefined;
      return adapt<T>(this.formats, kind, own ?? format, data);
    });
  }

  private regionRoot(region: string): string {
    return join(this.base, `region=${encodeURIComponent(region)}`);
  }

  /** The live version of a region (re-read on every call to `index`, never cached by the browser). */
  current(region: string): Promise<string> {
    return this.memo(`CURRENT:${region}`, async () => {
      const text = await this.getText(join(this.regionRoot(region), "CURRENT"), { cache: "no-cache" });
      const version = text.trim();
      if (!version) throw new NotAvailableError();
      return version;
    });
  }

  async index(region: string): Promise<StaticIndex> {
    const version = await this.current(region);
    return this.json<StaticIndex>(join(this.regionRoot(region), `version=${version}/static/index.json`), "index");
  }

  async taxa(region: string): Promise<TaxonEntry[]> {
    const idx = await this.index(region);
    return this.memo(`taxa:${region}:${idx.version}`, async () => {
      const text = await this.getText(join(this.regionRoot(region), idx.taxa));
      // A plain list with no format of its own: it has its index's.
      return adapt<TaxonEntry[]>(this.formats, "taxa", idx.format, JSON.parse(text));
    });
  }

  /** One species' year of maps; NotAvailable when the species isn't published (or is unknown). */
  async speciesMap(region: string, taxonId: string): Promise<SpeciesMapFile> {
    const paths = await this.mapPaths(region);
    const path = paths.get(taxonId);
    if (!path) throw new NotAvailableError();
    return this.json<SpeciesMapFile>(join(this.regionRoot(region), path), "map");
  }

  /** Map paths by taxon, from taxa.json (format 3 keeps them there, not in the index). */
  private async mapPaths(region: string): Promise<Map<string, string>> {
    const idx = await this.index(region);
    return this.memo(`maps:${region}:${idx.version}`, async () => {
      const out = new Map<string, string>();
      for (const t of await this.taxa(region)) if (typeof t.map === "string" && t.map) out.set(t.id, t.map);
      return out;
    });
  }

  /** A place's header: names, groups and the paths of its 52 week files. */
  async place(region: string, placeId: string): Promise<PlaceFile> {
    const idx = await this.index(region);
    const ref = Object.hasOwn(idx.places, placeId) ? idx.places[placeId] : undefined;
    if (!ref) throw new NotAvailableError();
    return this.json<PlaceFile>(join(this.regionRoot(region), ref.file), "place");
  }

  /** One ISO week of a place's lists. */
  async placeWeek(region: string, placeId: string, week: number): Promise<PlaceWeek> {
    const header = await this.place(region, placeId);
    const path = header.weeks[week - 1];
    if (!path) throw new NotAvailableError();
    return this.json<PlaceWeek>(join(this.regionRoot(region), path), "placeWeek");
  }

  /**
   * A URL for a published asset (e.g. a photo): absolute https URLs pass through; a relative
   * path is resolved against the region root, like map and place paths. Anything else is null.
   */
  assetUrl(region: string, path: string): string | null {
    if (/^https:\/\//i.test(path)) return path;
    if (/^[a-z][a-z0-9+.-]*:/i.test(path) || path.startsWith("//") || path.split("/").includes("..")) return null;
    return join(this.regionRoot(region), path);
  }

  /** The live version right now (never memoised): used to notice a newer publish. */
  async latestVersion(region: string): Promise<string> {
    const text = await this.getText(join(this.regionRoot(region), "CURRENT"), { cache: "no-cache" });
    return text.trim();
  }

  /** Forget CURRENT pointers, so the next read picks up a newer publish. */
  refresh(): void {
    for (const key of [...this.cache.keys()]) if (key.startsWith("CURRENT:")) this.cache.delete(key);
  }
}
