import type { Forecast } from "../api/client";
import { directionOf, summarizeConditions, todayRatio, type CellForecast } from "./conditions";

const f = (p: number, p0: number, drivers: Forecast["drivers"] = [], level = 1) =>
  ({ p, p_level0: p0, level, drivers }) as unknown as Forecast;
const cell = (forecast: Forecast): CellForecast => ({ cell: "x", lat: 0, lon: 0, forecast });

describe("conditions over map cells", () => {
  it("compares today's chance with the usual chance", () => {
    expect(todayRatio(f(0.4, 0.2))).toBeCloseTo(2);
    expect(directionOf(2)).toBe(1);
    expect(directionOf(1.05)).toBe(0);
    expect(directionOf(0.5)).toBe(-1);
    expect(directionOf(null)).toBe(0);
  });

  it("summarises directions and factors across cells", () => {
    const temp = { term: "t", signal: "water_temperature", value: 14, contribution: 0.4, hypothesis: true };
    const wind = { term: "w", signal: "wind_speed", value: 9, contribution: -0.1, hypothesis: false };
    const s = summarizeConditions([
      cell(f(0.5, 0.3, [temp, wind])),
      cell(f(0.2, 0.3, [{ ...temp, contribution: -0.5 }, wind])),
      cell(f(0.3, 0.3, [], 0)),
    ]);
    expect([s.up, s.down, s.same, s.baselineOnly]).toEqual([1, 1, 1, 1]);
    expect(s.factors.map((x) => x.signal)).toEqual(["wind_speed", "water_temperature"]);
    expect(s.factors[1]).toMatchObject({ up: 1, down: 1, hypothesis: true });
  });
});
