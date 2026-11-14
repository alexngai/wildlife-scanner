import type { CellForecastApi, MapForecast } from "../api/client";
import { directionOf, summarizeConditions, todayByCell, todayRatio } from "./conditions";

const cell = (id: string, p: number, p_level0: number, drivers: CellForecastApi["drivers"] = []): CellForecastApi => ({
  cell: id,
  p,
  p_level0,
  drivers,
});

describe("today vs usual", () => {
  it("compares the day's chance with the usual chance", () => {
    expect(todayRatio({ p: 0.4, p_level0: 0.2 })).toBeCloseTo(2);
    expect(todayRatio({ p: 0.4, p_level0: 0 })).toBeNull();
    expect(directionOf(2)).toBe(1);
    expect(directionOf(1.05)).toBe(0);
    expect(directionOf(0.5)).toBe(-1);
    expect(directionOf(null)).toBe(0);
  });

  it("bins every cell on the diverging ramp", () => {
    const f = { level: 1, cells: [cell("a", 0.6, 0.2), cell("b", 0.1, 0.3), cell("c", 0.3, 0.3)] } as MapForecast;
    const by = todayByCell(f);
    expect([by.get("a")?.bin, by.get("b")?.bin, by.get("c")?.bin]).toEqual([4, 0, 2]);
  });

  it("summarises directions and factors across cells", () => {
    const temp = { term: "t", signal: "water_temperature", value: 14, contribution: 0.4, hypothesis: true };
    const wind = { term: "w", signal: "wind_speed", value: 9, contribution: -0.1, hypothesis: false };
    const s = summarizeConditions(1, [
      cell("a", 0.5, 0.3, [temp, wind]),
      cell("b", 0.2, 0.3, [{ ...temp, contribution: -0.5 }, wind]),
      cell("c", 0.3, 0.3),
    ]);
    expect([s.up, s.down, s.same, s.baselineOnly]).toEqual([1, 1, 1, false]);
    expect(s.factors.map((x) => x.signal)).toEqual(["wind_speed", "water_temperature"]);
    expect(s.factors[1]).toMatchObject({ up: 1, down: 1, hypothesis: true });
  });

  it("recognises a baseline-only day", () => {
    expect(summarizeConditions(0, [cell("a", 0.3, 0.3)]).baselineOnly).toBe(true);
  });
});
