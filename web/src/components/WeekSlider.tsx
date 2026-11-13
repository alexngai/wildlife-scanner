import { useEffect, useId, useState } from "react";
import { monthLabel, monthOfWeek, weekLabel, weekOf } from "../lib/weeks";

const STEP_MS = 700;

export function WeekSlider({
  week,
  year,
  onChange,
  monthly,
}: {
  week: number;
  year: number;
  onChange: (w: number) => void;
  /** The current week is served by a monthly segment: label it by month. */
  monthly?: boolean;
}) {
  const id = useId();
  const text = monthly ? monthLabel(monthOfWeek(year, week)) : `Week ${week}: ${weekLabel(year, week)}`;
  const thisWeek = weekOf(new Date());
  const [playing, setPlaying] = useState(false);
  // Step one week at a time while playing; each step waits for the new week to render.
  useEffect(() => {
    if (!playing) return;
    const t = window.setTimeout(() => onChange(week >= 52 ? 1 : week + 1), STEP_MS);
    return () => window.clearTimeout(t);
  }, [playing, week, onChange]);
  return (
    <div className="week-slider">
      <label htmlFor={id} className="label">
        Time of year: <strong>{text}</strong>
      </label>
      <div className="week-row">
        <button
          type="button"
          className="play"
          onClick={() => setPlaying((p) => !p)}
          aria-pressed={playing}
          aria-label={playing ? "Pause the weeks" : "Play through the weeks"}
        >
          <span aria-hidden="true">{playing ? "❚❚" : "▶"}</span>
        </button>
        <button type="button" onClick={() => onChange(week <= 1 ? 52 : week - 1)} aria-label="Previous week">
          ‹
        </button>
        <input
          id={id}
          type="range"
          min={1}
          max={52}
          step={1}
          value={week}
          aria-valuetext={text}
          onChange={(e) => {
            setPlaying(false);
            onChange(Number(e.target.value));
          }}
        />
        <button type="button" onClick={() => onChange(week >= 52 ? 1 : week + 1)} aria-label="Next week">
          ›
        </button>
      </div>
      {week !== thisWeek && (
        <button type="button" className="link-button" onClick={() => onChange(thisWeek)}>
          Back to this week
        </button>
      )}
    </div>
  );
}
