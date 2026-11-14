// Writes a small, entirely synthetic folder bucket (format 2) and API responses for tests.
// No third-party data: names, places and numbers are invented and deterministic.
// Usage: node scripts/make-fixtures.mjs  (writes tests/fixtures/)
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gridDisk, latLngToCell, cellToParent } from "h3-js";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "..", "tests", "fixtures");
const REGION = "testland";
const VERSION = "20260101T000000";
const P_SCALE = 100000;
const CENTER = { lat: 36.6, lon: -121.9 };

// Seeded PRNG so fixtures are stable.
let seed = 42;
const rand = () => (seed = (seed * 1664525 + 1013904223) % 2 ** 32) / 2 ** 32;

const license = {
  license_ids: ["CC-BY-4.0", "CC-BY-NC-4.0"],
  noncommercial: true,
  share_alike: false,
  fully_open: false,
  attribution: ["Data source: synthetic test fixtures"],
};
const LABEL = "Synthetic test label: chance per outing for the stated method.";

const weeks = Array.from({ length: 52 }, (_, i) => i + 1);
const cells6 = gridDisk(latLngToCell(CENTER.lat, CENTER.lon, 6), 3).sort();
const parents = [...new Set(cells6.map((c) => cellToParent(c, 3)))];

function seasonal(week, peak, width, max) {
  const d = Math.min(Math.abs(week - peak), 52 - Math.abs(week - peak));
  return max * Math.exp(-(d * d) / (2 * width * width));
}

function weekSegment({ tier = 0, periods, peak, width, max, insufficientEvery = 0 }) {
  const p = [];
  const confidence = [];
  cells6.forEach((_, i) => {
    const local = 0.3 + 0.7 * rand();
    p.push(periods.map((w) => Math.round(P_SCALE * Math.max(0.0001, seasonal(w, peak, width, max) * local))));
    confidence.push(
      periods
        .map((w) => (insufficientEvery && i % insufficientEvery === 0 ? "i" : w % 7 === 0 ? "l" : i % 3 ? "h" : "m"))
        .join(""),
    );
  });
  const mean = (j) => Math.round(p.reduce((s, row) => s + row[j], 0) / p.length);
  return {
    tier,
    granularity: "week",
    resolution: 6,
    resolution_km: 3.72,
    periods,
    cells: cells6,
    p,
    confidence,
    ref: { resolution: 3, p: Object.fromEntries(parents.map((c) => [c, periods.map((_, j) => mean(j))])) },
    region_p: periods.map((_, j) => mean(j)),
  };
}

function monthSegment({ tier, months }) {
  const row = months.map((m) => 4000 + m * 100);
  return {
    tier,
    granularity: "month",
    resolution: 3,
    resolution_km: 68.98,
    periods: months,
    cells: parents,
    p: parents.map(() => row),
    confidence: parents.map(() => months.map(() => "h").join("")),
    ref: { resolution: null, p: { region: row } },
    region_p: row,
  };
}

// Synthetic "photos" (simple drawings, no real images) to exercise thumbnails, credits and the
// placeholder fallback: one good, one whose file is missing, one with a licence we can't show.
const photo = (id, license, url = `static/photos/${id}.svg`) => ({
  url,
  url_medium: url,
  license,
  attribution: `(c) Synthetic Fixture, some rights reserved (${String(license).toUpperCase().replace("CC-", "CC ")})`,
  source: "Synthetic",
  source_url: "https://example.org/photos/" + id,
});
const PHOTO_SVG = (hue) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" fill="hsl(${hue} 45% 82%)"/><circle cx="32" cy="34" r="16" fill="hsl(${hue} 45% 40%)"/><circle cx="38" cy="29" r="3" fill="#fff"/></svg>`;

const species = [
  {
    id: "testus-primus",
    scientific_name: "Testus primus",
    common_name: "Common Testbird",
    aliases: ["testbird"],
    group: "birds",
    tier: 0,
    mode: "forecast",
    records: 5000,
    photo: photo("testus-primus", "cc-by"),
    segments: [weekSegment({ periods: weeks, peak: 20, width: 6, max: 0.7, insufficientEvery: 9 })],
  },
  {
    // Openly mapped most of the year, awareness-only (monthly, coarse) in its breeding months,
    // and withheld for weeks 1-4 (no segment covers them).
    id: "testus-secundus",
    scientific_name: "Testus secundus",
    common_name: "Seasonal Testfish",
    aliases: [],
    group: "fishes",
    tier: 0,
    mode: "forecast",
    records: 800,
    photo: photo("testus-secundus", "cc-by-nc", "static/photos/gone.svg"),
    segments: [
      weekSegment({ periods: weeks.filter((w) => w >= 5 && (w < 23 || w > 35)), peak: 40, width: 5, max: 0.3 }),
      monthSegment({ tier: 2, months: [6, 7, 8] }),
    ],
  },
  {
    id: "rarus-tertius",
    scientific_name: "Rarus tertius",
    common_name: "Shy Testcat",
    aliases: [],
    group: "mammals",
    tier: 2,
    mode: "awareness",
    records: 120,
    photo: photo("rarus-tertius", null),
    segments: [monthSegment({ tier: 2, months: weeks.slice(0, 12) })],
  },
];

const places = {
  "test-cove": { name: "Test Cove", kind: "dive_site", lat: 36.62, lon: -121.9 },
  "test-park": { name: "Test Park", kind: "park", lat: 36.55, lon: -121.95 },
};

rmSync(out, { recursive: true, force: true });
const bucket = join(out, "bucket", `region=${REGION}`);
const write = (path, data) => {
  const full = join(bucket, path);
  mkdirSync(dirname(full), { recursive: true });
  writeFileSync(full, typeof data === "string" ? data : JSON.stringify(data));
};

const maps = {};
for (const s of species) {
  const path = `static/maps/${s.id}.fixture.json`;
  maps[s.id] = path;
  write(path, {
    format: 2,
    taxon: {
      taxon_id: s.id,
      scientific_name: s.scientific_name,
      common_name: s.common_name,
      group: s.group,
      tier: s.tier,
      mode: s.mode,
    },
    effort_group: `${s.group}:casual`,
    method: "observer_visit",
    label: LABEL,
    license,
    year_basis: 2026,
    p_scale: P_SCALE,
    segments: s.segments,
  });
}

const taxaInfo = Object.fromEntries(
  species.map((s) => [s.id, { scientific_name: s.scientific_name, common_name: s.common_name, group: s.group }]),
);
const placeFiles = {};
for (const [id, p] of Object.entries(places)) {
  const file = `static/places/${id}.fixture.json`;
  placeFiles[id] = { ...p, file };
  write(file, {
    format: 2,
    place: { place_id: id, name: p.name, kind: p.kind, notes: "A synthetic place for tests." },
    year_basis: 2026,
    p_scale: P_SCALE,
    item_fields: ["taxon_id", "p", "lift_x100", "seasonal_index_x100", "confidence", "res"],
    resolutions_km: [3.72, 9.85],
    awareness_message: "Present in this wider area. Shown for awareness only (synthetic).",
    taxa: taxaInfo,
    groups: {
      "birds:casual": {
        taxon_group: "birds",
        effort_class: "casual",
        label: "birds · casual sightings",
        method: "observer_visit",
        license,
      },
      "fishes:casual": {
        taxon_group: "fishes",
        effort_class: "casual",
        label: "fishes · casual sightings",
        method: "observer_visit",
        license,
      },
    },
    weeks: weeks.map((w) => ({
      week: w,
      groups: {
        "birds:casual": {
          most_likely: [["testus-primus", Math.round(P_SCALE * seasonal(w, 20, 6, 0.7)), 120, 150, "h", 0]],
          special_here:
            w > 10 && w < 30
              ? [["testus-primus", Math.round(P_SCALE * seasonal(w, 20, 6, 0.7)), 250, 150, "h", 0]]
              : [],
          peaking_now: [],
        },
        "fishes:casual": {
          most_likely: w >= 5 && (w < 23 || w > 35) ? [["testus-secundus", 1200, null, 90, "i", 1]] : [],
        },
      },
      awareness: ["rarus-tertius"],
      area_fallback: w >= 5 ? ["testus-secundus"] : [],
    })),
  });
}

write("static/photos/testus-primus.svg", PHOTO_SVG(140));
write("static/photos/rarus-tertius.svg", PHOTO_SVG(30));

write("CURRENT", `${VERSION}\n`);
write(`version=${VERSION}/static/index.json`, {
  format: 2,
  region: { id: REGION, name: "Testland", bbox: [-122.2, 36.3, -121.6, 36.9] },
  version: VERSION,
  baseline: { model_version: "baseline-test", built_at: "2026-01-01T00:00:00+00:00" },
  published_at: "2026-01-01T00:00:00+00:00",
  year_basis: 2026,
  p_scale: P_SCALE,
  paths_relative_to: `region=${REGION}/`,
  taxa: `version=${VERSION}/static/taxa.json`,
  maps,
  places: placeFiles,
});
write(
  `version=${VERSION}/static/taxa.json`,
  species.map((s) => Object.fromEntries(Object.entries(s).filter(([k]) => k !== "segments"))),
);

// Synthetic API responses (shapes from web/api/openapi.json).
const taxonSummary = {
  taxon_id: "testus-primus",
  scientific_name: "Testus primus",
  common_name: "Common Testbird",
  group: "birds",
  records_visits: 5000,
  tier: 0,
  mode: "forecast",
  gate: null,
  effort_groups: [],
};
const api = {
  regions: [{ region: REGION, name: "Testland", bbox: [-122.2, 36.3, -121.6, 36.9] }],
  forecast: {
    taxon: taxonSummary,
    day: "2026-05-20",
    cell: cells6[0],
    resolution_km: 3.72,
    effort_group: "birds:casual",
    method: "observer_visit",
    level: 1,
    p: 0.42,
    p_level0: 0.3,
    drivers: [
      { term: "temp", signal: "water_temperature", value: 14.2, contribution: 0.35, hypothesis: true },
      { term: "wind", signal: "wind_speed", value: 7.5, contribution: -0.2, hypothesis: false },
    ],
    notes: [],
  },
  hourly: {
    taxon: taxonSummary,
    day: "2026-05-20",
    timezone: "America/Los_Angeles",
    p_day: 0.42,
    level: 1,
    hours: Array.from({ length: 24 }, (_, h) => ({
      start: `2026-05-20T${String(h).padStart(2, "0")}:00:00-07:00`,
      p: 0.42,
      multiplier: h >= 6 && h <= 9 ? 2.1 : h >= 20 || h < 5 ? 0.3 : 1,
      factors: { diel: h >= 6 && h <= 9 ? "dawn" : h >= 20 || h < 5 ? "night" : "day" },
    })),
    best: ["2026-05-20T06:00:00-07:00", "2026-05-20T07:00:00-07:00", "2026-05-20T08:00:00-07:00"],
    factors: { diel: { dawn: 2.1, day: 1, night: 0.3 } },
    notes: [],
  },
  recent: {
    day: "2026-05-20",
    cell: parents[0],
    resolution_km: 9.85,
    window_days: 14,
    data_through: "2026-05-19",
    picking_up: [
      {
        taxon_id: "testus-primus",
        scientific_name: "Testus primus",
        common_name: "Common Testbird",
        effort_group: "birds:casual",
        method: "observer_visit",
        recent_detections: 9,
        recent_outings: 20,
        p_usual: 0.3,
        p_now: 0.45,
        level: 2,
        odds_boost: 1.9,
        drivers: [],
      },
    ],
    reported_recently: [
      {
        taxon_id: "testus-primus",
        scientific_name: "Testus primus",
        common_name: "Common Testbird",
        effort_group: "birds:casual",
        method: "observer_visit",
        recent_detections: 9,
        recent_outings: 20,
        p_usual: 0.3,
        p_now: 0.45,
        level: 2,
        odds_boost: null,
        drivers: [],
      },
    ],
    notes: [],
  },
};
mkdirSync(join(out, "api"), { recursive: true });
for (const [name, body] of Object.entries(api))
  writeFileSync(join(out, "api", `${name}.json`), JSON.stringify(body, null, 1));
console.log(`fixtures written to ${out}`);
