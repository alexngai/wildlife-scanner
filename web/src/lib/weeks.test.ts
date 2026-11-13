import { isoWeekParts, monthOfWeek, parseIsoDate, weekLabel, weekOf, weekStart } from "./weeks";

describe("ISO weeks", () => {
  it.each([
    ["2026-01-01", 2026, 1], // Thursday
    ["2027-01-01", 2026, 53], // Friday: last ISO week of 2026
    ["2024-12-30", 2025, 1], // Monday belongs to 2025-W01
    ["2026-05-20", 2026, 21],
  ])("%s is %i-W%i", (iso, year, week) => {
    const d = parseIsoDate(iso);
    expect(d).not.toBeNull();
    expect(isoWeekParts(d as Date)).toEqual({ year, week });
  });

  it("folds week 53 into 52", () => {
    expect(weekOf(new Date(2027, 0, 1))).toBe(52);
  });

  it("finds Mondays and months", () => {
    expect(weekStart(2026, 1).toISOString().slice(0, 10)).toBe("2025-12-29");
    expect(monthOfWeek(2026, 1)).toBe(1);
    expect(monthOfWeek(2026, 27)).toBe(7);
    expect(weekLabel(2026, 21)).toBe("May 18 – May 24");
  });
});
