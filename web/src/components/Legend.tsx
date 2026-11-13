import { BIN_LABELS } from "../lib/maps";
import { rampFor } from "./mapColors";

export function Legend({ theme, presence }: { theme: "light" | "dark"; presence?: boolean }) {
  if (presence) {
    return (
      <ul className="legend" aria-label="Map legend">
        <li>
          <span className="swatch swatch-presence" aria-hidden="true" /> Present in this wider area
        </li>
      </ul>
    );
  }
  const ramp = rampFor(theme);
  return (
    <ul className="legend" aria-label="Map legend: chance per outing">
      {BIN_LABELS.map((label, i) => (
        <li key={label}>
          <span className="swatch" style={{ background: ramp[i] }} aria-hidden="true" /> {label}
        </li>
      ))}
      <li>
        <span className="swatch swatch-insufficient" aria-hidden="true" /> Not enough data
      </li>
      <li>
        <span className="swatch swatch-low" style={{ background: ramp[3] }} aria-hidden="true" /> Paler: low confidence
      </li>
    </ul>
  );
}
