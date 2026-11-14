import { useEffect } from "react";
import { Link, useParams } from "react-router";
import { Hotspots } from "../components/Hotspots";
import { LocateIcon } from "../components/Icons";
import { PlaceCard } from "../components/PlaceCard";
import { SpeciesSearch } from "../components/SpeciesSearch";
import { Async } from "../components/Status";
import { rememberRegion, useRegionIndex, useTaxa } from "../hooks";
import { shortDate } from "../lib/format";
import { usePageTitle } from "../lib/usePageTitle";

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
          <header className="page-head">
            <h1>{idx.region.name}</h1>
            <p className="subtitle small">
              {Object.keys(idx.maps).length.toLocaleString("en")} species mapped · data updated{" "}
              {shortDate(idx.published_at ?? idx.baseline.built_at)}
            </p>
          </header>

          <section aria-labelledby="search-h" className="card">
            <h2 id="search-h" className="sr-only">
              Find a species
            </h2>
            <Async state={taxa} what="Species list">
              {(list) => <SpeciesSearch region={region} taxa={list} popular={list.slice(0, 12)} />}
            </Async>
          </section>

          <section aria-labelledby="places-h" className="card">
            <div className="card-head">
              <div>
                <h2 id="places-h">Places</h2>
                <p className="muted small">What you might see at each place, week by week.</p>
              </div>
              <Link className="button secondary small" to={`/r/${region}/nearby`}>
                <LocateIcon />
                Near me
              </Link>
            </div>
            <ul className="card-list two">
              {Object.entries(idx.places).map(([id, p]) => (
                <li key={id}>
                  <PlaceCard to={`/r/${region}/places/${encodeURIComponent(id)}`} name={p.name} kind={p.kind} />
                </li>
              ))}
            </ul>
          </section>

          <Hotspots region={region} index={idx} />
        </div>
      )}
    </Async>
  );
}
