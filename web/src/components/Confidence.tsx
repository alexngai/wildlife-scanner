import { percent } from "../lib/format";
import { CONFIDENCE_TEXT, type ConfidenceLevel } from "../lib/policy";

export function ConfidenceBadge({ level }: { level: ConfidenceLevel }) {
  if (level === "none") return null;
  return <span className={`badge conf-${level}`}>{CONFIDENCE_TEXT[level]}</span>;
}

const STEPS: Partial<Record<ConfidenceLevel, number>> = { low: 1, medium: 2, high: 3 };

/** A compact three-step confidence meter for list rows; the level is read out as text. */
export function ConfidenceMeter({ level }: { level: ConfidenceLevel }) {
  const steps = STEPS[level];
  if (!steps) return null;
  return (
    <span className={`conf-meter l${steps}`} title={CONFIDENCE_TEXT[level]}>
      <i />
      <i />
      <i />
      <span className="sr-only">{CONFIDENCE_TEXT[level]}</span>
    </span>
  );
}

/** A chance per outing, or "not enough data": never a zero for insufficient estimates. */
export function Chance({ p, level }: { p: number | null; level: ConfidenceLevel }) {
  if (level === "insufficient" || p === null) return <span className="chance chance-na">not enough data</span>;
  return <span className="chance">{percent(p)}</span>;
}
