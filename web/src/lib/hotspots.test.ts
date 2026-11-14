import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { PlaceFile, PlaceWeek } from "../products/types";
import { hotspotGroups, hotspots, type HotspotPlace } from "./hotspots";
import { listsFromPlace } from "./lists";

const ROOT = resolve(__dirname, "../../tests/fixtures/bucket/region=testland");
const read = <T>(path: string) => JSON.parse(readFileSync(resolve(ROOT, path), "utf8")) as T;
const header = (id: string) => read<PlaceFile>(`static/places/${id}.fixture.json`);
const at = (id: string, name: string, lat: number, lon: number, week: number): HotspotPlace => {
  const h = header(id);
  return { id, name, lat, lon, lists: listsFromPlace(h, read<PlaceWeek>(h.weeks[week - 1]!)) };
};
const week = (w: number) => [
  at("test-cove", "Test Cove", 36.62, -121.9, w),
  at("test-park", "Test Park", 36.55, -121.95, w),
];

describe("hotspots", () => {
  it("offers effort groups with lists that week, most widely available first", () => {
    expect(hotspotGroups(week(20)).map((g) => [g.id, g.places])).toEqual([
      ["birds:casual", 2],
      ["fishes:casual", 2],
    ]);
    // Testfish has no list in its withheld weeks.
    expect(hotspotGroups(week(2)).map((g) => g.id)).toEqual(["birds:casual"]);
  });

  it("scores places within one group by summing the most-likely chances", () => {
    const rows = hotspots(week(20), "birds:casual");
    expect(rows).toHaveLength(2);
    expect(rows[0]!.score).toBeCloseTo(0.7, 2);
    expect(rows[0]!.special?.taxonId).toBe("testus-primus");
    expect(hotspots(week(2), "fishes:casual").every((r) => r.score === null)).toBe(true);
  });
});
