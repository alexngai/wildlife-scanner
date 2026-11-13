import { BIN_LABELS, LIFT_LABELS } from "../lib/maps";
import { liftRampFor, rampFor, type MapMetric } from "./mapColors";

export function Legend({
  theme,
  presence,
  metric = "chance",
}: {
  theme: "light" | "dark";
  presence?: boolean;
  metric?: MapMetric;
}) {
  if (presence) {
    return (
      <ul className="legend" aria-label="Map legend">
        <li>
          <span className="swatch swatch-presence" aria-hidden="true" /> Present in this wider area
        </li>
      </ul>
    );
  }
  const lift = metric === "lift";
  const ramp = lift ? liftRampFor(theme) : rampFor(theme);
  const labels = lift ? LIFT_LABELS : BIN_LABELS;
  return (
    <ul
      className="legend"
      aria-label={lift ? "Map legend: chance compared with the wider area" : "Map legend: chance per outing"}
    >
      {labels.map((label, i) => (
        <li key={label}>
          <span className="swatch" style={{ background: ramp[i] }} aria-hidden="true" /> {label}
        </li>
      ))}
      <li>
        <span className="swatch swatch-insufficient" aria-hidden="true" /> Not enough data
      </li>
      {lift ? (
        <li>
          <span className="swatch swatch-none" aria-hidden="true" /> No comparison
        </li>
      ) : null}
      <li>
        <span className="swatch swatch-low" style={{ background: ramp[3] }} aria-hidden="true" /> Paler: low confidence
      </li>
    </ul>
  );
}
