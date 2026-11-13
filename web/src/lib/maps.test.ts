import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { latLngToCell } from "h3-js";
import type { SpeciesMapFile } from "../products/types";
import {
  calendar,
  cellsForPeriod,
  isPresenceOnly,
  liftBinFor,
  liftFor,
  presenceCells,
  segmentForWeek,
  toGeoJSON,
} from "./maps";

const load = (id: string) =>
  JSON.parse(
    readFileSync(resolve(__dirname, `../../tests/fixtures/bucket/region=testland/static/maps/${id}.fixture.json`), "utf8"),
  ) as SpeciesMapFile;

describe("species maps", () => {
  const primus = load("testus-primus");
  const secundus = load("testus-secundus");
  const rarus = load("rarus-tertius");

  it("finds the segment for a week, and none for withheld weeks", () => {
    expect(segmentForWeek(primus, 20)?.j).toBe(19);
    expect(segmentForWeek(secundus, 2)).toBeNull(); // weeks 1-4 are in no segment
    const summer = segmentForWeek(secundus, 27);
    expect(summer?.segment.granularity).toBe("month");
    expect(summer?.period).toBe(7);
    expect(summer && isPresenceOnly(summer.segment)).toBe(true);
  });

  it("keeps insufficient cells without a number (never zero)", () => {
    const hit = segmentForWeek(primus, 20);
    if (!hit) throw new Error("no segment");
    const values = cellsForPeriod(hit.segment, hit.j, primus.p_scale);
    const insufficient = values.filter((v) => v.confidence === "insufficient");
    expect(insufficient.length).toBeGreaterThan(0);
    expect(insufficient.every((v) => v.p === null)).toBe(true);
    const geo = toGeoJSON(values);
    expect(geo.features.find((f) => f.properties.insufficient)?.properties.bin).toBe(-1);
    expect(values.filter((v) => v.p !== null).every((v) => v.p! > 0 && v.p! <= 1)).toBe(true);
  });

  it("builds regional and point calendars from published values only", () => {
    const regional = calendar(primus, null);
    expect(regional.granularity).toBe("week");
    expect(regional.points).toHaveLength(52);
    const seg = primus.segments[0]!;
    expect(regional.points[19]!.p).toBeCloseTo(seg.region_p[19]! / primus.p_scale);

    const cell = seg.cells[1]!; // not an insufficient row (every 9th)
    const [lat, lng] = [36.6, -121.9];
    const atPoint = calendar(primus, { lat, lon: lng });
    const i = seg.cells.indexOf(latLngToCell(lat, lng, seg.resolution));
    expect(i).toBeGreaterThanOrEqual(0);
    expect(atPoint.basis.cell).toBe(seg.cells[i]);
    void cell;
  });

  it("hides numbers for awareness segments in calendars", () => {
    const cal = calendar(secundus, null);
    expect(cal.points[26]!.presenceOnly).toBe(true);
    expect(cal.points[26]!.p).toBeNull();
    expect(cal.points[1]!.p).toBeNull(); // withheld
    expect(cal.points[1]!.presenceOnly).toBe(false);
  });

  it("gives presence cells for awareness species without numbers", () => {
    expect(presenceCells(rarus).length).toBe(rarus.segments[0]!.cells.length);
    expect(presenceCells(primus)).toEqual([]);
  });

  it("computes lift against the reference cell", () => {
    const seg = primus.segments[0]!;
    const lift = liftFor(seg, 1, 19);
    expect(lift).not.toBeNull();
    expect(lift!).toBeGreaterThan(0);
  });

  it("carries lift into cell features, binned around 'about the same'", () => {
    const hit = segmentForWeek(primus, 20)!;
    const geo = toGeoJSON(cellsForPeriod(hit.segment, hit.j, primus.p_scale));
    const withP = geo.features.filter((f) => f.properties.p !== null);
    expect(withP.every((f) => f.properties.lift !== null && f.properties.liftBin >= 0)).toBe(true);
    const insufficient = geo.features.filter((f) => f.properties.insufficient);
    expect(insufficient.every((f) => f.properties.lift === null && f.properties.liftBin === -1)).toBe(true);
    expect([0.3, 0.6, 1, 1.5, 3].map(liftBinFor)).toEqual([0, 1, 2, 3, 4]);
  });
});
