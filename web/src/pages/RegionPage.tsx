import { useEffect } from "react";
import { Link, useParams } from "react-router";
import { SpeciesSearch } from "../components/SpeciesSearch";
import { Async } from "../components/Status";
import { rememberRegion, useRegionIndex, useTaxa } from "../hooks";
import { displayName, shortDate } from "../lib/format";
import { usePageTitle } from "../lib/usePageTitle";

const KIND: Record<string, string> = { dive_site: "Dive site", park: "Park", zone: "Area", trail: "Trail", beach: "Beach" };

export function RegionPage() {
  const { region = "" } = useParams();
  const index = useRegionIndex(region);
  const taxa = useTaxa(region);
  usePageTitle(index?.status === "ok" ? index.data.region.name : index?.status === "error" ? "Not available" : null);
  useEffect(() => {
    if (index?.status === "ok") rememberRegion(region);
  }, [index?.status, region]);

  return (
    <Async state={index} what="This region">
      {(idx) => (
        <div className="page">
          <h1>{idx.region.name}</h1>
          <p className="muted small">
            Data published {shortDate(idx.published_at ?? idx.baseline.built_at)} · seasonal model built{" "}
            {shortDate(idx.baseline.built_at)}
          </p>
          <section aria-labelledby="search-h" className="section">
            <h2 id="search-h" className="sr-only">
              Species
            </h2>
            <Async state={taxa} what="Species list">
              {(list) => (
                <>
                  <SpeciesSearch region={region} taxa={list} />
                  {list.length > 0 && (
                    <details className="browse">
                      <summary>Most recorded species</summary>
                      <ul className="plain-list">
                        {list.slice(0, 15).map((t) => (
                          <li key={t.id}>
                            <Link to={`/r/${region}/species/${encodeURIComponent(t.id)}`}>{displayName(t)}</Link>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </>
              )}
            </Async>
          </section>
          <section aria-labelledby="places-h" className="section">
            <h2 id="places-h">Places</h2>
            <p>
              <Link className="button" to={`/r/${region}/nearby`}>
                What's near me?
              </Link>
            </p>
            <ul className="card-list">
              {Object.entries(idx.places).map(([id, p]) => (
                <li key={id}>
                  <Link className="card card-link" to={`/r/${region}/places/${encodeURIComponent(id)}`}>
                    <span className="card-title">{p.name}</span>
                    <span className="muted small">{KIND[p.kind] ?? p.kind.replace(/_/g, " ")}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </Async>
  );
}
