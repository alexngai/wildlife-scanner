import { useMemo } from "react";
import type { MapForecast } from "../api/client";
import { useServices } from "../context";
import { summarizeConditions, todayByCell, type ConditionsSummary, type TodayCell } from "../lib/conditions";
import { shortDate, times } from "../lib/format";
import { useAsync, type AsyncState } from "../lib/useAsync";
import { humanize } from "./ApiPanels";

/**
 * The day's forecast for every cell of the species' map, in one API call. `load` is false until
 * the person picks the "Today vs usual" view, so nothing is requested by default.
 */
export function useConditions(
  taxonId: string,
  region: string,
  date: string,
  load: boolean,
): { state: AsyncState<MapForecast> | null; byCell: Map<string, TodayCell>; summary: ConditionsSummary | null } {
  const { api } = useServices();
  const state = useAsync(load && api.enabled ? () => api.forecastMap(taxonId, region, date) : null, [
    api,
    taxonId,
    region,
    date,
    load,
  ]);
  const data = state?.status === "ok" ? state.data : null;
  const byCell = useMemo(() => (data ? todayByCell(data) : new Map<string, TodayCell>()), [data]);
  const summary = useMemo(() => (data ? summarizeConditions(data.level, data.cells ?? []) : null), [data]);
  return { state, byCell, summary };
}

export function ConditionsSummaryView({ summary, date }: { summary: ConditionsSummary; date: string }) {
  if (summary.cells === 0)
    return <p className="muted small">No forecast is available for these cells on {shortDate(date)}.</p>;
  if (summary.baselineOnly) {
    return (
      <p className="muted small">
        No daily factors are modelled for this species yet, so {shortDate(date)} looks like a usual day for this week.
        That doesn't mean conditions don't matter.
      </p>
    );
  }
  return (
    <div className="conditions" aria-live="polite">
      <p className="small">
        On <strong>{shortDate(date)}</strong>, across {summary.cells} cells: conditions raise the chance in{" "}
        <strong>{summary.up}</strong>, lower it in <strong>{summary.down}</strong>, and leave it about the same in{" "}
        {summary.same}.
      </p>
      {summary.factors.length > 0 && (
        <ul className="drivers">
          {summary.factors.slice(0, 4).map((f) => {
            const up = f.multiplier > 1.01;
            const down = f.multiplier < 0.99;
            return (
              <li key={f.signal} className={up ? "up" : down ? "down" : "flat"}>
                <span className="driver-dir" aria-hidden="true">
                  {up ? "▲" : down ? "▼" : "•"}
                </span>
                <span className="driver-name">{humanize(f.signal)}</span>
                <span className="driver-effect">
                  {up
                    ? `raises the odds about ${times(f.multiplier)}`
                    : down
                      ? `lowers the odds about ${times(f.multiplier)}`
                      : "little effect"}
                  {f.up > 0 && f.down > 0 && ` (up in ${f.up}, down in ${f.down} cells)`}
                </span>
                {f.hypothesis && <span className="badge">expected from species profile</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
