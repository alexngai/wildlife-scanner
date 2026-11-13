import { makeFixtureFetch } from "../../tests/fixtureFetch";
import { FormatError, NotAvailableError } from "../lib/errors";
import { StaticClient } from "./client";

describe("StaticClient", () => {
  it("follows CURRENT to the index and the files it lists", async () => {
    const { fetcher, requested } = makeFixtureFetch();
    const c = new StaticClient("/data", fetcher);
    const idx = await c.index("testland");
    expect(idx.region.name).toBe("Testland");
    const taxa = await c.taxa("testland");
    expect(taxa.map((t) => t.id)).toContain("testus-primus");
    const map = await c.speciesMap("testland", "testus-primus");
    expect(map.segments).toHaveLength(1);
    expect(requested[0]).toBe("/data/region=testland/CURRENT");
    // Memoised: a second read doesn't refetch.
    await c.speciesMap("testland", "testus-primus");
    expect(requested.filter((u) => u.includes("testus-primus"))).toHaveLength(1);
  });

  it("treats unknown and unlisted species the same: not available", async () => {
    const { fetcher } = makeFixtureFetch();
    const c = new StaticClient("/data", fetcher);
    await expect(c.speciesMap("testland", "no-such-species")).rejects.toBeInstanceOf(NotAvailableError);
    await expect(c.speciesMap("testland", "__proto__")).rejects.toBeInstanceOf(NotAvailableError);
    await expect(c.place("testland", "nowhere")).rejects.toBeInstanceOf(NotAvailableError);
    await expect(c.index("no-region")).rejects.toBeInstanceOf(NotAvailableError);
  });

  it("refuses formats it doesn't know", async () => {
    const fetcher = (async (u: string) =>
      u.endsWith("CURRENT") ? new Response("v1") : new Response(JSON.stringify({ format: 3 }))) as unknown as typeof fetch;
    await expect(new StaticClient("/data", fetcher).index("x")).rejects.toBeInstanceOf(FormatError);
  });
});
