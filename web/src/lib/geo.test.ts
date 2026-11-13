import { nearestPlaces, regionForPoint, roundCoord } from "./geo";

describe("geo", () => {
  it("rounds locations before sending them", () => {
    expect(roundCoord(36.612345678)).toBe(36.612);
  });
  it("picks the smallest region containing a point", () => {
    const big = { id: "big", name: "Big", bbox: [-125, 30, -110, 40] as [number, number, number, number] };
    const small = { id: "small", name: "Small", bbox: [-122, 36, -121, 37] as [number, number, number, number] };
    expect(regionForPoint([big, small], 36.5, -121.5)?.id).toBe("small");
    expect(regionForPoint([big, small], 50, 0)).toBeNull();
  });
  it("sorts places by distance", () => {
    const near = nearestPlaces(
      { a: { name: "A", kind: "park", lat: 36.6, lon: -121.9, file: "" }, b: { name: "B", kind: "park", lat: 37.6, lon: -121.9, file: "" } },
      { lat: 36.61, lon: -121.9 },
    );
    expect(near.map((n) => n.id)).toEqual(["a", "b"]);
    expect(near[0]!.km).toBeLessThan(2);
  });
});
