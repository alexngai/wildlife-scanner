/** ISO-week helpers. Estimates are per ISO week of the year; week 53 folds into 52. */

const DAY = 86_400_000;

function utc(d: Date): Date {
  return new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
}

/** ISO week (1-53) and its ISO year for a calendar date (local date parts). */
export function isoWeekParts(date: Date): { year: number; week: number } {
  const d = utc(date);
  const dow = d.getUTCDay() || 7; // Mon=1..Sun=7
  d.setUTCDate(d.getUTCDate() + 4 - dow); // Thursday of this week
  const yearStart = Date.UTC(d.getUTCFullYear(), 0, 1);
  const week = Math.ceil(((d.getTime() - yearStart) / DAY + 1) / 7);
  return { year: d.getUTCFullYear(), week };
}

/** The ISO week used to look estimates up (1-52). */
export function weekOf(date: Date): number {
  return Math.min(isoWeekParts(date).week, 52);
}

/** Monday of ISO week `week` of `year`, as a UTC date. */
export function weekStart(year: number, week: number): Date {
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const dow = jan4.getUTCDay() || 7;
  const mondayW1 = jan4.getTime() - (dow - 1) * DAY;
  return new Date(mondayW1 + (week - 1) * 7 * DAY);
}

/** Month (1-12) that an ISO week belongs to, by its Thursday (used for monthly segments). */
export function monthOfWeek(year: number, week: number): number {
  const thursday = new Date(weekStart(year, week).getTime() + 3 * DAY);
  return thursday.getUTCMonth() + 1;
}

const short = new Intl.DateTimeFormat("en", { month: "short", day: "numeric", timeZone: "UTC" });
const monthName = new Intl.DateTimeFormat("en", { month: "long", timeZone: "UTC" });
const monthShort = new Intl.DateTimeFormat("en", { month: "short", timeZone: "UTC" });

/** "May 18 – May 24" for an ISO week of `year`. */
export function weekLabel(year: number, week: number): string {
  const start = weekStart(year, week);
  const end = new Date(start.getTime() + 6 * DAY);
  return `${short.format(start)} – ${short.format(end)}`;
}

export function monthLabel(month: number, style: "long" | "short" = "long"): string {
  const d = new Date(Date.UTC(2001, month - 1, 1));
  return (style === "long" ? monthName : monthShort).format(d);
}

/** Today's date as YYYY-MM-DD in local time. */
export function isoDate(d: Date = new Date()): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

/** Parse YYYY-MM-DD as a local date (no timezone shift). */
export function parseIsoDate(s: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(d.getTime()) ? null : d;
}
