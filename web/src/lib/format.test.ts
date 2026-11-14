import { displayName, oddsMultiplier, percent, times } from "./format";

describe("format", () => {
  it("never shows false precision", () => {
    expect(percent(0.004)).toBe("<1%");
    expect(percent(0.426)).toBe("43%");
    expect(percent(0.999)).toBe(">99%");
    expect(percent(null)).toBe("–");
    expect(times(1.234)).toBe("1.2×");
    expect(times(12.6)).toBe("13×");
  });
  it("converts log-odds to an odds multiplier", () => {
    expect(oddsMultiplier(Math.log(2))).toBeCloseTo(2);
  });
  it("prefers common names", () => {
    expect(displayName({ common_name: null, scientific_name: "A b", id: "a-b" })).toBe("A b");
  });
});
