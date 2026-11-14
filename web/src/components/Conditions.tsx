import { cellToLatLng } from "h3-js";
import { useMemo } from "react";
import { useServices } from "../context";
import {
  directionOf,
  summarizeConditions,
  todayRatio,
  type CellForecast,
  type ConditionsSummary,
} from "../lib/conditions";
import { percent, shortDate, times } from "../lib/format";
import type { FeatureCollection } from "../lib/maps";
import { useAsync, type AsyncState } from "../lib/useAsync";
import { humanize } from "./ApiPanels";
import type { MapMarker } from "./MapView";

/** How many of the week's highest cells get a daily forecast (one API call each). */
export const CONDITION_CELLS = 12;

/**
 * Daily forecasts for the week's highest cells. `load` is false until the person asks, so no
 * request is made by default.
 */
export function useConditions(
  taxonId: string,
  data: FeatureCollection,
  date: string,
  load: boolean,
): { state: AsyncState<CellForecast[]> | null; markers: MapMarker[]; summary: ConditionsSummary | null } {
  const { api } = useServices();
  const cells = useMemo(
    () =>
      data.features
        .filter((f) => f.properties.p !== null)
        .sort((a, b) => (b.properties.p ?? 0) - (a.properties.p ?? 0))
        .slice(0, CONDITION_CELLS)
        .map((f) => {
          const [lat, lon] = cellToLatLng(f.properties.cell);
          return { cell: f.properties.cell, lat, lon };
        }),
    [data],
  );
  const key = cells.map((c) => c.cell).join(",");
  const state = useAsync(
    load && api.enabled && cells.length > 0
      ? async () => {
          const settled = await Promise.allSettled(
            cells.map((c) => api.forecast(taxonId, { lat: c.lat, lon: c.lon }, date)),
          );
          const ok = cells.flatMap((c, i): CellForecast[] => {
            const r = settled[i];
            return r?.status === "fulfilled" ? [{ ...c, forecast: r.value }] : [];
          });
          if (ok.length === 0 && settled[0]?.status === "rejected") throw settled[0].reason;
          return ok;
        }
      : null,
    [api, taxonId, date, key, load],
  );
  const results = state?.status === "ok" ? state.data : null;
  const markers = useMemo(
    () =>
      (results ?? []).map((r): MapMarker => {
        const ratio = todayRatio(r.forecast);
        return {
          lat: r.lat,
          lon: r.lon,
          direction: directionOf(ratio),
          text:
            ratio === null
              ? `${shortDate(r.forecast.day)}: ${percent(r.forecast.p)}`
              : `${shortDate(r.forecast.day)}: ${percent(r.forecast.p)}, usually ${percent(r.forecast.p_level0)} (${times(ratio)})`,
        };
      }),
    [results],
  );
  const summary = useMemo(() => (results ? summarizeConditions(results) : null), [results]);
  return { state, markers, summary };
}

export function ConditionsSummaryView({ summary, date }: { summary: ConditionsSummary; date: string }) {
  if (summary.cells === 0)
    return <p className="muted small">No forecast is available for these cells on {shortDate(date)}.</p>;
  if (summary.baselineOnly === summary.cells) {
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
        On <strong>{shortDate(date)}</strong>, in the {summary.cells} highest cells: conditions raise the chance in{" "}
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
