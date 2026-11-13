import { FetchError, FormatError, NotAvailableError } from "../lib/errors";
import type { PlaceFile, SpeciesMapFile, StaticIndex, TaxonEntry } from "./types";
import { SUPPORTED_FORMAT } from "./types";

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

  private json<T extends { format?: number }>(url: string): Promise<T> {
    return this.memo(url, async () => {
      const data = JSON.parse(await this.getText(url)) as T;
      if (!Array.isArray(data) && data.format !== SUPPORTED_FORMAT) throw new FormatError(data.format);
      return data;
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
    return this.json<StaticIndex>(join(this.regionRoot(region), `version=${version}/static/index.json`));
  }

  async taxa(region: string): Promise<TaxonEntry[]> {
    const idx = await this.index(region);
    return this.memo(`taxa:${region}:${idx.version}`, async () => {
      const text = await this.getText(join(this.regionRoot(region), idx.taxa));
      return JSON.parse(text) as TaxonEntry[];
    });
  }

  /** One species' year of maps; NotAvailable when the species isn't published (or is unknown). */
  async speciesMap(region: string, taxonId: string): Promise<SpeciesMapFile> {
    const idx = await this.index(region);
    const path = Object.hasOwn(idx.maps, taxonId) ? idx.maps[taxonId] : undefined;
    if (!path) throw new NotAvailableError();
    return this.json<SpeciesMapFile>(join(this.regionRoot(region), path));
  }

  async place(region: string, placeId: string): Promise<PlaceFile> {
    const idx = await this.index(region);
    const ref = Object.hasOwn(idx.places, placeId) ? idx.places[placeId] : undefined;
    if (!ref) throw new NotAvailableError();
    return this.json<PlaceFile>(join(this.regionRoot(region), ref.file));
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
