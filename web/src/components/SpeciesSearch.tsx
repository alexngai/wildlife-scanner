import { useEffect, useId, useMemo, useState } from "react";
import { Link } from "react-router";
import { useServices } from "../context";
import { displayName, groupLabel } from "../lib/format";
import { seasonRibbon, type RibbonWeek } from "../lib/maps";
import { searchTaxa } from "../lib/search";
import { useAsync } from "../lib/useAsync";
import { weekOf } from "../lib/weeks";
import type { TaxonEntry } from "../products/types";
import { SearchIcon } from "./Icons";
import { SeasonRibbon } from "./SeasonRibbon";
import { PhotoCredits, SpeciesThumb } from "./SpeciesPhoto";
import { usePhotos } from "../hooks";

/** Ribbons are drawn for this many results, each from its species map file. */
const RIBBONS = 8;
const SETTLE_MS = 350;

function useSettled<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return settled;
}

/** Season ribbons for the given taxa; a species whose map can't be read just has none. */
function useRibbons(region: string, ids: string[]): Map<string, RibbonWeek[]> {
  const { products } = useServices();
  const key = ids.join(",");
  const state = useAsync(
    key
      ? async () => {
          const settled = await Promise.allSettled(
            key.split(",").map(async (id) => [id, seasonRibbon(await products.speciesMap(region, id))] as const),
          );
          return new Map(settled.flatMap((r) => (r.status === "fulfilled" ? [r.value] : [])));
        }
      : null,
    [products, region, key],
  );
  return state?.status === "ok" ? state.data : EMPTY;
}
const EMPTY = new Map<string, RibbonWeek[]>();

export function SpeciesSearch({
  region,
  taxa,
  popular = [],
}: {
  region: string;
  taxa: TaxonEntry[];
  /** Shown as quick picks while the search box is empty. */
  popular?: TaxonEntry[];
}) {
  const [q, setQ] = useState("");
  const id = useId();
  const results = useMemo(() => searchTaxa(taxa, q), [taxa, q]);
  const photos = usePhotos(region);
  const settledQ = useSettled(q, SETTLE_MS);
  // Awareness species get no ribbon: presence only, no timing.
  const ribbonIds = useMemo(
    () =>
      settledQ === q
        ? results
            .slice(0, RIBBONS)
            .filter((t) => t.mode !== "awareness")
            .map((t) => t.id)
        : [],
    [results, settledQ, q],
  );
  const ribbons = useRibbons(region, ribbonIds);
  const year = new Date().getFullYear();
  const week = weekOf(new Date());
  return (
    <div className="search">
      <label htmlFor={id} className="label">
        Search species
      </label>
      <div className="search-box">
        <SearchIcon />
        <input
          id={id}
          type="search"
          value={q}
          placeholder="Search by common or scientific name"
          autoComplete="off"
          onChange={(e) => setQ(e.target.value)}
          aria-describedby={`${id}-count`}
        />
      </div>
      <p id={`${id}-count`} className="sr-only" aria-live="polite">
        {q ? `${results.length} ${results.length === 1 ? "result" : "results"}` : ""}
      </p>
      {!q && popular.length > 0 && (
        <div className="popular">
          <p className="muted small">Most recorded here</p>
          <ul className="chip-list">
            {popular.map((t) => (
              <li key={t.id}>
                <Link to={`/r/${region}/species/${encodeURIComponent(t.id)}`}>{displayName(t)}</Link>
              </li>
            ))}
          </ul>
        </div>
      )}
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
                <SpeciesThumb photo={photos.get(t.id)} group={t.group} />
                <span className="result-text">
                  <span className="result-name">{displayName(t)}</span>
                  {t.common_name && t.scientific_name && <em className="muted small"> {t.scientific_name}</em>}
                  <span className="muted small result-meta">
                    {groupLabel(t.group)}
                    {t.mode === "awareness" && " · awareness only"}
                  </span>
                </span>
                {ribbons.has(t.id) && (
                  <span className="result-ribbon">
                    <SeasonRibbon ribbon={ribbons.get(t.id) ?? []} year={year} week={week} />
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {results.length > 0 && (
        <PhotoCredits
          items={results.flatMap((t) => {
            const photo = photos.get(t.id);
            return photo ? [{ name: displayName(t), photo }] : [];
          })}
        />
      )}
    </div>
  );
}
