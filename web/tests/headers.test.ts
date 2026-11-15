import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { DEFAULT_BASEMAP, DEFAULT_LAYERS } from "../src/config";
import { compatInfo } from "../src/products/formats";

const headers = readFileSync(resolve(__dirname, "../public/_headers"), "utf8");
const csp = /Content-Security-Policy: (.+)/.exec(headers)?.[1] ?? "";
const directive = (name: string) =>
  (
    csp
      .split(";")
      .map((d) => d.trim().split(/\s+/))
      .find(([n]) => n === name) ?? []
  ).slice(1);
const production = JSON.parse(readFileSync(resolve(__dirname, "../deploy/config.production.json"), "utf8")) as Record<
  string,
  unknown
>;
const origin = (url: string) => new URL(url.replace(/\{[^}]+\}/g, "x")).origin;

describe("production headers", () => {
  it("allow the production data bucket and API", () => {
    for (const key of ["staticBase", "apiBase"]) {
      expect(directive("connect-src")).toContain(origin(String(production[key])));
    }
    expect(directive("img-src")).toContain(origin(String(production.staticBase)));
  });

  it("allow every default map layer, the base map and iNaturalist's open-data photos", () => {
    for (const layer of DEFAULT_LAYERS)
      for (const tile of layer.tiles) {
        expect(directive("connect-src")).toContain(origin(tile));
        expect(directive("img-src")).toContain(origin(tile));
      }
    expect(directive("connect-src")).toContain(origin(DEFAULT_BASEMAP.light));
    expect(directive("img-src")).toContain("https://inaturalist-open-data.s3.amazonaws.com");
  });

  it("keep scripts to the site itself and forbid framing", () => {
    expect(directive("script-src")).toEqual(["'self'"]);
    expect(directive("frame-ancestors")).toEqual(["'none'"]);
    expect(directive("object-src")).toEqual(["'none'"]);
  });

  it("serve /compat.json uncached and readable by the publisher", () => {
    expect(headers).toMatch(/\/compat\.json\n\s+Cache-Control: no-cache\n\s+Access-Control-Allow-Origin: \*/);
    expect(compatInfo().formats.length).toBeGreaterThan(0);
  });
});
