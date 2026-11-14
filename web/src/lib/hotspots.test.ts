import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { PlaceFile } from "../products/types";
import { hotspotGroups, hotspots, type HotspotPlace } from "./hotspots";

const load = (id: string) =>
  JSON.parse(
    readFileSync(
      resolve(__dirname, `../../tests/fixtures/bucket/region=testland/static/places/${id}.fixture.json`),
      "utf8",
    ),
  ) as PlaceFile;

const places: HotspotPlace[] = [
  { id: "test-cove", name: "Test Cove", lat: 36.62, lon: -121.9, file: load("test-cove") },
  { id: "test-park", name: "Test Park", lat: 36.55, lon: -121.95, file: load("test-park") },
];

describe("hotspots", () => {
  it("offers effort groups with lists that week, most widely available first", () => {
    expect(hotspotGroups(places, 20).map((g) => [g.id, g.places])).toEqual([
      ["birds:casual", 2],
      ["fishes:casual", 2],
    ]);
    // Testfish has no list in its withheld weeks.
    expect(hotspotGroups(places, 2).map((g) => g.id)).toEqual(["birds:casual"]);
  });

  it("scores places within one group by summing the most-likely chances", () => {
    const rows = hotspots(places, 20, "birds:casual");
    expect(rows).toHaveLength(2);
    expect(rows[0]!.score).toBeCloseTo(0.7, 2);
    expect(rows[0]!.special?.taxonId).toBe("testus-primus");
    expect(hotspots(places, 2, "fishes:casual").every((r) => r.score === null)).toBe(true);
  });
});
