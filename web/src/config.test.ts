import { DEFAULT_CONFIG, mergeConfig } from "./config";

describe("config", () => {
  it("merges runtime overrides and ignores junk", () => {
    const c = mergeConfig(DEFAULT_CONFIG, { apiBase: "", regions: ["a", 3], basemap: { light: "https://x/style.json" } });
    expect(c.apiBase).toBe("");
    expect(c.regions).toEqual(["a"]);
    expect(c.basemap.light).toBe("https://x/style.json");
    expect(c.basemap.dark).toBe("https://x/style.json");
    expect(mergeConfig(DEFAULT_CONFIG, { basemap: "none" }).basemap.light).toBe("none");
    expect(mergeConfig(DEFAULT_CONFIG, null)).toBe(DEFAULT_CONFIG);
  });
});
