import { cellToLatLng } from "h3-js";
import { useMemo } from "react";
import { km, percent, times } from "../lib/format";
import { nearestPlaces } from "../lib/geo";
import type { FeatureCollection } from "../lib/maps";
import { CONFIDENCE_TEXT } from "../lib/policy";
import type { PlaceRef } from "../products/types";

const NEAR_KM = 10;

/**
 * The week's map as a table: the highest-chance published cells, each described by its nearest
 * named place, with a button that picks that cell (the keyboard alternative to tapping the map).
 * Only published cells and values appear, as on the map.
 */
export function MapTable({
  data,
  places,
  selectedCell,
  onChoose,
  limit = 15,
  sortBy = "chance",
}: {
  data: FeatureCollection;
  places: Record<string, PlaceRef>;
  selectedCell: string | null;
  onChoose: (pt: { lat: number; lon: number }) => void;
  limit?: number;
  /** Rank by chance, or by chance against the wider area. */
  sortBy?: "chance" | "lift";
}) {
  const rows = useMemo(
    () =>
      data.features
        .filter((f) => f.properties.p !== null && (sortBy === "chance" || f.properties.lift !== null))
        .sort((a, b) =>
          sortBy === "lift"
            ? (b.properties.lift ?? 0) - (a.properties.lift ?? 0)
            : (b.properties.p ?? 0) - (a.properties.p ?? 0),
        )
        .slice(0, limit)
        .map((f) => {
          const [lat, lon] = cellToLatLng(f.properties.cell);
          const near = nearestPlaces(places, { lat, lon }, 1)[0];
          return {
            cell: f.properties.cell,
            p: f.properties.p ?? 0,
            confidence: f.properties.confidence,
            lift: f.properties.lift,
            lat,
            lon,
            where: near && near.km <= NEAR_KM ? `Near ${near.place.name} (${km(near.km)})` : `${lat.toFixed(2)}, ${lon.toFixed(2)}`,
          };
        }),
    [data, places, limit, sortBy],
  );
  const total = data.features.filter((f) => f.properties.p !== null).length;
  const anyLift = rows.some((r) => r.lift !== null);
  const ranked = sortBy === "lift" ? "most above their wider area" : "with the highest chance";
  if (rows.length === 0) return null;
  return (
    <details className="data-table map-table">
      <summary>Show the map as a table</summary>
      <p className="muted small">
        {rows.length < total ? `The ${rows.length} cells ${ranked}, of ${total}.` : `All ${total} cells.`}{" "}
        Choose one to see its calendar and forecast.
      </p>
      <table>
        <thead>
          <tr>
            <th scope="col">Where</th>
            <th scope="col">Chance per outing</th>
            {anyLift && <th scope="col">Against wider area</th>}
            <th scope="col">Confidence</th>
            <th scope="col">
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.cell} aria-current={r.cell === selectedCell ? "location" : undefined}>
              <th scope="row">{r.where}</th>
              <td>{percent(r.p)}</td>
              {anyLift && <td>{times(r.lift)}</td>}
              <td>{CONFIDENCE_TEXT[r.confidence]}</td>
              <td>
                <button type="button" className="link-button" onClick={() => onChoose({ lat: r.lat, lon: r.lon })}>
                  Choose<span className="sr-only"> {r.where}</span>
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
