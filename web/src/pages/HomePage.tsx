import { Link } from "react-router";
import { Async } from "../components/Status";
import { lastRegion, useRegions } from "../hooks";
import { shortDate } from "../lib/format";

export function HomePage() {
  const regions = useRegions();
  const last = lastRegion();
  return (
    <div className="page">
      <h1>Where and when to see wildlife</h1>
      <p className="lede">
        Seasonal maps, calendars and daily forecasts for any species, built from public biodiversity records. Pick a
        region to start.
      </p>
      <section aria-labelledby="regions-h">
        <h2 id="regions-h">Regions</h2>
        <Async state={regions} what="Regions">
          {(list) =>
            list.length === 0 ? (
              <p className="muted">No regions are published yet.</p>
            ) : (
              <ul className="card-list">
                {list.map((r) => (
                  <li key={r.id}>
                    <Link className="card card-link" to={`/r/${r.id}`}>
                      <span className="card-title">
                        {r.info?.name ?? r.id}
                        {r.id === last && <span className="badge">Last used</span>}
                      </span>
                      <span className="muted small">
                        {r.index
                          ? `${Object.keys(r.index.maps).length} species mapped · published ${shortDate(r.index.published_at ?? r.index.baseline.built_at)}`
                          : "Not available right now"}
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
