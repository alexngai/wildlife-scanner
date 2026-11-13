import { Link, useParams, useSearchParams } from "react-router";
import { RecentPanel } from "../components/ApiPanels";
import { ListsPanel } from "../components/ListsPanel";
import { Async, NotAvailable } from "../components/Status";
import { WeekSlider } from "../components/WeekSlider";
import { useServices } from "../context";
import { useRegionIndex } from "../hooks";
import { listsFromPlaceFile } from "../lib/lists";
import { useAsync } from "../lib/useAsync";
import { weekOf } from "../lib/weeks";

export function PlacePage() {
  const { region = "", placeId = "" } = useParams();
  const { products, api } = useServices();
  const [params, setParams] = useSearchParams();
  const index = useRegionIndex(region);
  const file = useAsync(() => products.place(region, placeId), [products, region, placeId]);
  const thisWeek = weekOf(new Date());
  const week = Math.min(52, Math.max(1, Number(params.get("week")) || thisWeek));
  const year = new Date().getFullYear();
  return (
    <div className="page">
      <p className="crumbs">
        <Link to={`/r/${region}`}>← {index?.status === "ok" ? index.data.region.name : "Region"}</Link>
      </p>
      <Async state={file} what="This place">
        {(f) => {
          const view = listsFromPlaceFile(f, week);
          return (
            <article>
              <h1>{f.place.name}</h1>
              {f.place.notes && <p className="muted">{f.place.notes}</p>}
              <WeekSlider
                week={week}
                year={year}
                onChange={(w) => setParams(w === thisWeek ? {} : { week: String(w) }, { replace: true })}
              />
              <section aria-labelledby="lists-h" className="section">
                <h2 id="lists-h">What you might see</h2>
                {view ? <ListsPanel region={region} view={view} /> : <NotAvailable what="Lists for this week" />}
              </section>
              {week === thisWeek && (
                <section aria-labelledby="recent-h" className="section">
                  <h2 id="recent-h">Right now</h2>
                  <RecentPanel region={region} load={() => api.placeRecent(placeId)} deps={[placeId]} />
                </section>
              )}
            </article>
          );
        }}
      </Async>
    </div>
  );
}
