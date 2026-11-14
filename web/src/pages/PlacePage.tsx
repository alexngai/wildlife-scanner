import { Link, useParams, useSearchParams } from "react-router";
import { RecentPanel } from "../components/ApiPanels";
import { ArrowLeftIcon } from "../components/Icons";
import { ListsPanel } from "../components/ListsPanel";
import { kindLabel } from "../components/PlaceCard";
import { Async, NotAvailable } from "../components/Status";
import { WeekSlider } from "../components/WeekSlider";
import { useServices } from "../context";
import { useRegionIndex } from "../hooks";
import { listsFromPlaceFile } from "../lib/lists";
import { useAsync } from "../lib/useAsync";
import { usePageTitle } from "../lib/usePageTitle";
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
  const kind = index?.status === "ok" ? index.data.places[placeId]?.kind : undefined;
  usePageTitle(file?.status === "ok" ? file.data.place.name : file?.status === "error" ? "Not available" : null);
  return (
    <div className="page">
      <p className="crumbs">
        <Link to={`/r/${region}`}>
          <ArrowLeftIcon />
          {index?.status === "ok" ? index.data.region.name : "Region"}
        </Link>
      </p>
      <Async state={file} what="This place">
        {(f) => {
          const view = listsFromPlaceFile(f, week);
          return (
            <>
              <header className="page-head">
                <h1>{f.place.name}</h1>
                {(kind || f.place.kind) && (
                  <div className="chips">
                    <span className="chip accent">{kindLabel(kind ?? f.place.kind)}</span>
                  </div>
                )}
                {f.place.notes && <p className="subtitle">{f.place.notes}</p>}
              </header>
              <section aria-labelledby="lists-h" className="card">
                <div className="card-head">
                  <h2 id="lists-h">What you might see</h2>
                </div>
                <WeekSlider
                  week={week}
                  year={year}
                  onChange={(w) => setParams(w === thisWeek ? {} : { week: String(w) }, { replace: true })}
                />
                <hr className="divider" />
                {view ? <ListsPanel region={region} view={view} /> : <NotAvailable what="Lists for this week" />}
              </section>
              {week === thisWeek && (
                <section aria-labelledby="recent-h" className="card">
                  <div className="card-head">
                    <h2 id="recent-h">Right now</h2>
                  </div>
                  <RecentPanel region={region} load={() => api.placeRecent(placeId)} deps={[placeId]} />
                </section>
              )}
            </>
          );
        }}
      </Async>
    </div>
  );
}
