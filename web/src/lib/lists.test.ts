import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { PlaceFile } from "../products/types";
import { fixtureApi } from "../../tests/fixtureFetch";
import { listsFromApi, listsFromPlaceFile, newForYou } from "./lists";
import type { PlaceLists } from "../api/client";

const file = JSON.parse(
  readFileSync(
    resolve(__dirname, "../../tests/fixtures/bucket/region=testland/static/places/test-cove.fixture.json"),
    "utf8",
  ),
) as PlaceFile;

describe("place lists", () => {
  it("decodes compact rows by item_fields", () => {
    const view = listsFromPlaceFile(file, 20);
    expect(view).not.toBeNull();
    const birds = view!.groups.find((g) => g.id === "birds:casual")!;
    expect(birds.label).toBe("birds · casual sightings");
    const it = birds.mostLikely[0]!;
    expect(it.name).toBe("Common Testbird");
    expect(it.lift).toBeCloseTo(1.2);
    expect(it.seasonalIndex).toBeCloseTo(1.5);
    expect(it.confidence).toBe("high");
    expect(view!.awareness.map((a) => a.name)).toEqual(["Shy Testcat"]);
  });

  it("marks coarser-area items and insufficient confidence", () => {
    const fish = listsFromPlaceFile(file, 20)!.groups.find((g) => g.id === "fishes:casual")!;
    expect(fish.mostLikely[0]!.coarser).toBe(true);
    expect(fish.mostLikely[0]!.resolutionKm).toBeCloseTo(9.85);
    expect(fish.mostLikely[0]!.confidence).toBe("insufficient");
  });

  it("computes new-for-you from the published lists and the local life list", () => {
    const birds = listsFromPlaceFile(file, 20)!.groups.find((g) => g.id === "birds:casual")!;
    expect(newForYou(birds, new Set()).map((i) => i.taxonId)).toEqual(["testus-primus"]);
    expect(newForYou(birds, new Set(["testus-primus"]))).toEqual([]);
  });

  it("reads API lists into the same view", () => {
    const api: PlaceLists = {
      date: "2026-05-20",
      week: 21,
      groups: [
        {
          group: "birds:casual",
          taxon_group: "birds",
          effort_class: "casual",
          label: "birds",
          method: "observer_visit",
          most_likely: [
            {
              taxon_id: "x",
              scientific_name: "X x",
              common_name: null,
              group: "birds",
              p: 0.5,
              lift: null,
              seasonal_index: null,
              confidence: "medium",
              resolution_km: 3.7,
            },
          ],
        },
      ],
      awareness: [],
      area_fallback: ["x"],
    } as unknown as PlaceLists;
    const view = listsFromApi(api);
    expect(view.groups[0]!.mostLikely[0]!).toMatchObject({ name: "X x", confidence: "medium", coarser: true });
    void fixtureApi;
  });
});
