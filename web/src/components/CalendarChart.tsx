import { percent } from "../lib/format";
import type { CalendarSeries } from "../lib/maps";
import { CONFIDENCE_TEXT } from "../lib/policy";
import { monthLabel, weekLabel, weekOf } from "../lib/weeks";

const W = 640;
const H = 140;
const PAD = { l: 34, r: 6, t: 8, b: 22 };

/**
 * Seasonal calendar: one bar per published week (or month). Insufficient periods are drawn
 * as hatched placeholders, withheld ones are left empty; nothing is interpolated.
 */
export function CalendarChart({
  series,
  year,
  currentPeriod,
  title,
}: {
  series: CalendarSeries;
  year: number;
  currentPeriod?: number;
  title: string;
}) {
  const n = series.points.length;
  const max = Math.max(0.05, ...series.points.map((p) => p.p ?? 0));
  const bw = (W - PAD.l - PAD.r) / n;
  const y = (v: number) => PAD.t + (H - PAD.t - PAD.b) * (1 - v / max);
  const periodName = (p: number) =>
    series.granularity === "month" ? monthLabel(p) : `Week ${p} (${weekLabel(year, p)})`;
  const ticks = [0, max / 2, max];
  const monthStarts =
    series.granularity === "month"
      ? series.points.map((p) => p.period)
      : Array.from({ length: 12 }, (_, m) => {
          const w = weekOf(new Date(year, m, 1));
          return m === 0 && w > 50 ? 1 : w; // Jan 1 can fall in the previous ISO year
        });
  return (
    <figure className="calendar">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="cal-title" preserveAspectRatio="none">
        <title id="cal-title">{title}</title>
        <defs>
          <pattern id="hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="4" className="hatch-line" />
          </pattern>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={PAD.l - 4} y={y(t) + 3} className="axis" textAnchor="end">
              {percent(t)}
            </text>
          </g>
        ))}
        {series.points.map((pt, i) => {
          const x = PAD.l + i * bw;
          const current = pt.period === currentPeriod;
          if (pt.presenceOnly) return null;
          if (pt.confidence === "insufficient") {
            return (
              <rect
                key={pt.period}
                x={x + 0.5}
                y={PAD.t}
                width={bw - 1}
                height={H - PAD.t - PAD.b}
                fill="url(#hatch)"
                className="bar-na"
              >
                <title>{`${periodName(pt.period)}: not enough data`}</title>
              </rect>
            );
          }
          if (pt.p === null) return null;
          return (
            <rect
              key={pt.period}
              x={x + 0.5}
              y={y(pt.p)}
              width={Math.max(1, bw - 1)}
              height={Math.max(0.5, H - PAD.b - y(pt.p))}
              className={`bar conf-bar-${pt.confidence}${current ? " bar-current" : ""}`}
            >
              <title>{`${periodName(pt.period)}: ${percent(pt.p)} (${CONFIDENCE_TEXT[pt.confidence]})`}</title>
            </rect>
          );
        })}
        {monthStarts.map((p, m) => (
          <text
            key={p}
            x={PAD.l + (p - 1) * bw + (series.granularity === "month" ? bw / 2 : 0)}
            y={H - 6}
            className="axis"
            textAnchor={series.granularity === "month" ? "middle" : "start"}
          >
            {monthLabel(m + 1, "short").charAt(0)}
          </text>
        ))}
      </svg>
      <figcaption className="muted small">
        Chance per outing by {series.granularity}. Hatched: not enough data. Gaps: not published.
      </figcaption>
      <details className="data-table">
        <summary>Show as a table</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">{series.granularity === "month" ? "Month" : "Week"}</th>
              <th scope="col">Chance per outing</th>
              <th scope="col">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {series.points.map((pt) => (
              <tr key={pt.period}>
                <th scope="row">{periodName(pt.period)}</th>
                <td>
                  {pt.presenceOnly
                    ? "awareness only"
                    : pt.confidence === "insufficient"
                      ? "not enough data"
                      : pt.p === null
                        ? "not published"
                        : percent(pt.p)}
                </td>
                <td>{pt.presenceOnly || pt.p === null ? "–" : CONFIDENCE_TEXT[pt.confidence]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
