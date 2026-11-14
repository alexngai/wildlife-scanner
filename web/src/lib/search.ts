import type { TaxonEntry } from "../products/types";

export function fold(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/**
 * Client-side name search over taxa.json. Matches common and scientific names, aliases and
 * ids; ranks exact, then prefix, then word-prefix, then substring matches, then by records.
 */
export function searchTaxa(taxa: TaxonEntry[], query: string, limit = 20): TaxonEntry[] {
  const q = fold(query);
  if (!q) return [];
  const scored: { t: TaxonEntry; score: number; i: number }[] = [];
  taxa.forEach((t, i) => {
    const names = [t.common_name, t.scientific_name, ...(t.aliases ?? []), t.id.replace(/-/g, " ")]
      .filter((n): n is string => !!n)
      .map(fold);
    let best = 0;
    for (const n of names) {
      if (n === q) best = Math.max(best, 4);
      else if (n.startsWith(q)) best = Math.max(best, 3);
      else if (n.split(" ").some((w) => w.startsWith(q))) best = Math.max(best, 2);
      else if (n.includes(q)) best = Math.max(best, 1);
    }
    if (best > 0) scored.push({ t, score: best, i });
  });
  // taxa.json is ordered most-recorded first, so the original index breaks ties.
  scored.sort((a, b) => b.score - a.score || a.i - b.i);
  return scored.slice(0, limit).map((s) => s.t);
}
