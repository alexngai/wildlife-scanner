/**
 * Number formatting. Never show more precision than is meaningful: chances are rounded to
 * whole percent (or "<1%"), ratios to one decimal.
 */
export function percent(p: number | null | undefined): string {
  if (p === null || p === undefined || Number.isNaN(p)) return "–";
  if (p <= 0) return "0%";
  if (p < 0.01) return "<1%";
  if (p > 0.99) return ">99%";
  return `${Math.round(p * 100)}%`;
}

/** "3.2×" for a ratio. */
export function times(r: number | null | undefined): string {
  if (r === null || r === undefined || Number.isNaN(r)) return "–";
  if (r >= 10) return `${Math.round(r)}×`;
  return `${r.toFixed(1)}×`;
}

export function km(value: number): string {
  return value >= 10 ? `${Math.round(value)} km` : `${value.toFixed(1)} km`;
}

/** Odds multiplier from a log-odds contribution. */
export function oddsMultiplier(contribution: number): number {
  return Math.exp(contribution);
}

/** Sentence case for display: published names mix "coyote brush" and "Coyote Brush". */
export function capitalize(name: string): string {
  return name.charAt(0).toUpperCase() + name.slice(1);
}

export function displayName(t: {
  common_name?: string | null;
  scientific_name?: string | null;
  id?: string;
  taxon_id?: string;
}): string {
  return capitalize(t.common_name || t.scientific_name || t.id || t.taxon_id || "Unnamed");
}

const dateFmt = new Intl.DateTimeFormat("en", { year: "numeric", month: "short", day: "numeric" });

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  // Date-only strings are calendar dates: show them without a timezone shift.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateFmt.format(d);
}

/** Human label for a method id like "birding_checklist". */
export function methodLabel(method: string): string {
  const known: Record<string, string> = {
    birding_checklist: "per birding checklist",
    observer_visit: "per outing (casual sightings)",
    dive: "per dive",
    survey_unit: "per survey unit",
  };
  return known[method] ?? `per ${method.replace(/_/g, " ")}`;
}

export function groupLabel(group: string | null | undefined): string {
  if (!group) return "Other";
  return group.charAt(0).toUpperCase() + group.slice(1).replace(/_/g, " ");
}
