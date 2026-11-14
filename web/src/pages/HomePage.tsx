import { Link } from "react-router";
import { ChevronRightIcon, ExploreIcon } from "../components/Icons";
import { Async } from "../components/Status";
import { lastRegion, useRegions } from "../hooks";
import { shortDate } from "../lib/format";
import { usePageTitle } from "../lib/usePageTitle";

export function HomePage() {
  const regions = useRegions();
  const last = lastRegion();
  usePageTitle(null);
  return (
    <div className="page">
      <section className="hero">
        <h1>Where and when to see wildlife</h1>
        <p className="lede">
          Seasonal maps, calendars and daily forecasts for any species, built from public biodiversity records.
        </p>
      </section>
      <section aria-labelledby="regions-h" className="card">
        <div className="card-head">
          <div>
            <h2 id="regions-h">Choose a region</h2>
            <p className="muted small">Each region has its own maps, places and species.</p>
          </div>
        </div>
        <Async state={regions} what="Regions">
          {(list) =>
            list.length === 0 ? (
              <p className="muted">No regions are published yet.</p>
            ) : (
              <ul className="card-list two">
                {list.map((r) => (
                  <li key={r.id}>
                    <Link className="card card-link" to={`/r/${r.id}`}>
                      <span className="place-icon">
                        <ExploreIcon />
                      </span>
                      <span className="card-body">
                        <span className="card-title">
                          {r.info?.name ?? r.id}
                          {r.id === last && <span className="chip accent">Last used</span>}
                        </span>
                        <span className="muted small">
                          {r.index
                            ? `${Object.keys(r.index.places).length} places · data updated ${shortDate(r.index.published_at ?? r.index.baseline.built_at)}`
                            : "Not available right now"}
                        </span>
                      </span>
                      <span className="chevron">
                        <ChevronRightIcon />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )
          }
        </Async>
      </section>
    </div>
  );
}
