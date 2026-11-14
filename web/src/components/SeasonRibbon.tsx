import { peakRuns, type RibbonWeek } from "../lib/maps";
import { monthLabel, monthOfWeek } from "../lib/weeks";

const W = 2;
const GAP = 0.5;
const H = 16;

function runText(year: number, [a, b]: [number, number]): string {
  const ma = monthLabel(monthOfWeek(year, a));
  const mb = monthLabel(monthOfWeek(year, b));
  return ma === mb ? ma : `${ma}–${mb}`;
}

/** A sentence for screen readers: when the species is most often recorded across the region. */
export function ribbonSummary(ribbon: RibbonWeek[], year: number): string {
  if (ribbon.every((r) => r.kind === "none")) return "No seasonal pattern published.";
  const runs = peakRuns(ribbon);
  const presence = ribbon.some((r) => r.kind === "presence");
  const parts: string[] = [];
  if (runs.length > 0) {
    const only = runs.length === 1 ? runs[0] : undefined;
    const all = only !== undefined && only[1] - only[0] >= 45;
    parts.push(all ? "Recorded about equally all year" : `Most recorded ${[...new Set(runs.map((r) => runText(year, r)))].slice(0, 3).join(" and ")}`);
  }
  if (presence) parts.push("awareness only at some times of year");
  if (ribbon.some((r) => r.kind === "none")) parts.push("not shown at other times");
  return `${parts.join("; ")}.`;
}

/**
 * A tiny 52-week strip of region-wide values: bar height relative to the species' own peak,
 * so it shows timing, not how common one species is against another. Withheld weeks are left
 * empty; awareness-only weeks are a flat band with no number.
 */
export function SeasonRibbon({ ribbon, year, week }: { ribbon: RibbonWeek[]; year: number; week?: number }) {
  const max = Math.max(0, ...ribbon.map((r) => (r.kind === "value" ? r.p : 0)));
  const width = 52 * (W + GAP);
  return (
    <svg
      className="ribbon"
      viewBox={`0 0 ${width} ${H}`}
      width={width}
      height={H}
      role="img"
      aria-label={`Season: ${ribbonSummary(ribbon, year)}`}
    >
      {ribbon.map((r, i) => {
        const x = i * (W + GAP);
        if (r.kind === "presence") return <rect key={i} x={x} y={H - 3} width={W} height={3} className="ribbon-presence" />;
        if (r.kind === "none" || max <= 0) return null;
        const h = Math.max(1, (r.p / max) * H);
        return <rect key={i} x={x} y={H - h} width={W} height={h} className="ribbon-bar" />;
      })}
      {week !== undefined && <rect x={(week - 1) * (W + GAP) - 0.25} y={0} width={0.75} height={H} className="ribbon-now" />}
    </svg>
  );
}
