import { makeFixtureFetch } from "../../tests/fixtureFetch";
import { StaticClient } from "./client";
import { adapt, compatInfo, DEFAULT_FORMATS, FormatError, supportedFormats, type FormatRegistry } from "./formats";
import type { StaticIndex, TaxonEntry } from "./types";

describe("static-product formats", () => {
  it("reads the current format and refuses others", () => {
    expect(supportedFormats()).toEqual([4]);
    expect(adapt(DEFAULT_FORMATS, "index", 4, { a: 1 })).toEqual({ a: 1 });
    for (const f of [3, 5, "4", undefined]) expect(() => adapt(DEFAULT_FORMATS, "index", f, {})).toThrow(FormatError);
  });

  it("says which formats it reads, for the publisher's check (/compat.json)", () => {
    expect(compatInfo()).toEqual({ formats: [4], current: 4 });
  });

  it("can read two formats during a change: the older one converted up to the current shape", async () => {
    // A future build: format 5 is current, and format 4 files are converted (here, an invented field rename).
    const registry: FormatRegistry = {
      4: (kind, data) => (kind === "taxa" ? (data as TaxonEntry[]).map((t) => ({ ...t, label: t.common_name })) : data),
      5: (_kind, data) => data,
    };
    expect(supportedFormats(registry)).toEqual([4, 5]);

    // The fixtures are format 4: still readable, converted.
    const c4 = new StaticClient("/data", makeFixtureFetch().fetcher, registry);
    const taxa = (await c4.taxa("testland")) as (TaxonEntry & { label?: string })[];
    expect(taxa[0]?.label).toBe("Common Testbird");

    // The same files relabelled as format 5 are read as they are.
    const { fetcher } = makeFixtureFetch();
    const as5 = (async (url: string, init?: RequestInit) => {
      const res = await fetcher(url, init);
      if (!url.endsWith("index.json")) return res;
      const idx = (await res.json()) as StaticIndex;
      return new Response(JSON.stringify({ ...idx, format: 5 }));
    }) as typeof fetch;
    const c5 = new StaticClient("/data", as5, registry);
    expect((await c5.index("testland")).format).toBe(5);
    const taxa5 = (await c5.taxa("testland")) as (TaxonEntry & { label?: string })[];
    expect(taxa5[0]?.label).toBeUndefined(); // format 5 needs no conversion

    // Today's app (format 4 only) refuses the format-5 index and asks for a reload.
    await expect(new StaticClient("/data", as5).index("testland")).rejects.toBeInstanceOf(FormatError);
  });
});
