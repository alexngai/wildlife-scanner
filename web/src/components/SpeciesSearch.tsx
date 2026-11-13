import { useId, useMemo, useState } from "react";
import { Link } from "react-router";
import { displayName, groupLabel } from "../lib/format";
import { searchTaxa } from "../lib/search";
import type { TaxonEntry } from "../products/types";

export function SpeciesSearch({ region, taxa }: { region: string; taxa: TaxonEntry[] }) {
  const [q, setQ] = useState("");
  const id = useId();
  const results = useMemo(() => searchTaxa(taxa, q), [taxa, q]);
  return (
    <div className="search">
      <label htmlFor={id} className="label">
        Search species
      </label>
      <input
        id={id}
        type="search"
        value={q}
        placeholder="Common or scientific name"
        autoComplete="off"
        onChange={(e) => setQ(e.target.value)}
        aria-describedby={`${id}-count`}
      />
      <p id={`${id}-count`} className="sr-only" aria-live="polite">
        {q ? `${results.length} ${results.length === 1 ? "result" : "results"}` : ""}
      </p>
      {q && results.length === 0 && (
        <p className="muted">
          No match. Some species are not shown at all to protect them; others may have too few records.
        </p>
      )}
      {results.length > 0 && (
        <ul className="result-list">
          {results.map((t) => (
            <li key={t.id}>
              <Link to={`/r/${region}/species/${encodeURIComponent(t.id)}`} className="result">
                <span className="result-name">{displayName(t)}</span>
                {t.common_name && t.scientific_name && <em className="muted small"> {t.scientific_name}</em>}
                <span className="muted small result-meta">
                  {groupLabel(t.group)}
                  {t.mode === "awareness" && " · awareness only"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
