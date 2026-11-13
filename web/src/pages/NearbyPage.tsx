import { useState } from "react";
import { Link, useParams } from "react-router";
import { RecentPanel } from "../components/ApiPanels";
import { ListsPanel } from "../components/ListsPanel";
import { Async, Loading } from "../components/Status";
import { useServices } from "../context";
import { useRegionIndex, useRegions } from "../hooks";
import { km } from "../lib/format";
import { inBbox, nearestPlaces, regionForPoint, roundCoord } from "../lib/geo";
import { listsFromApi, listsFromPlaceFile } from "../lib/lists";
import { useAsync } from "../lib/useAsync";
import { weekOf } from "../lib/weeks";
import type { StaticIndex } from "../products/types";
import { usePageTitle } from "../lib/usePageTitle";

type Pos = { lat: number; lon: number };
type GeoState = { status: "idle" } | { status: "locating" } | { status: "ok"; pos: Pos } | { status: "error"; message: string };

/** Places within this distance count as "here" when there is no API to ask about the exact point. */
const NEAR_KM = 15;

export function NearbyPage() {
  const { region = "" } = useParams();
  const index = useRegionIndex(region);
  const [geo, setGeo] = useState<GeoState>({ status: "idle" });
  usePageTitle(index?.status === "ok" ? `Nearby · ${index.data.region.name}` : "Nearby");

  const locate = () => {
    if (!("geolocation" in navigator)) {
      setGeo({ status: "error", message: "This browser can't share its location." });
      return;
    }
    setGeo({ status: "locating" });
    navigator.geolocation.getCurrentPosition(
      (p) => setGeo({ status: "ok", pos: { lat: roundCoord(p.coords.latitude), lon: roundCoord(p.coords.longitude) } }),
      (err) =>
        setGeo({
          status: "error",
          message:
            err.code === err.PERMISSION_DENIED
              ? "Location permission was denied. You can still pick a place from the list."
              : "Couldn't get your location. Try again, or pick a place.",
        }),
      { enableHighAccuracy: false, maximumAge: 600_000, timeout: 15_000 },
    );
  };

  return (
    <div className="page">
      <p className="crumbs">
        <Link to={`/r/${region}`}>← {index?.status === "ok" ? index.data.region.name : "Region"}</Link>
      </p>
      <h1>Nearby</h1>
      <p className="muted small">
        Your location is rounded to about 100 m and used only to answer this request. It isn't stored.
      </p>
      {geo.status !== "ok" && (
        <p>
          <button type="button" className="button" onClick={locate} disabled={geo.status === "locating"}>
            {geo.status === "locating" ? "Locating…" : "Use my location"}
          </button>
        </p>
      )}
      {geo.status === "error" && (
        <p className="notice notice-error" role="alert">
          {geo.message}
        </p>
      )}
      <Async state={index} what="This region">
        {(idx) => (geo.status === "ok" ? <NearbyResults region={region} index={idx} pos={geo.pos} /> : <PlaceLinks region={region} index={idx} />)}
      </Async>
    </div>
  );
}

function PlaceLinks({ region, index }: { region: string; index: StaticIndex }) {
  return (
    <section className="section">
      <h2>Places in {index.region.name}</h2>
      <ul className="plain-list">
        {Object.entries(index.places).map(([id, p]) => (
          <li key={id}>
            <Link to={`/r/${region}/places/${encodeURIComponent(id)}`}>{p.name}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function NearbyResults({ region, index, pos }: { region: string; index: StaticIndex; pos: Pos }) {
  const { api, products } = useServices();
  const regions = useRegions();
  const inside = inBbox(index.region, pos.lat, pos.lon);
  const near = nearestPlaces(index.places, pos, 5);
  const closest = near[0] && near[0].km <= NEAR_KM ? near[0] : null;
  const week = weekOf(new Date());

  const apiLists = useAsync(api.enabled && inside ? () => api.nearbyLists(pos.lat, pos.lon) : null, [api, inside, pos.lat, pos.lon]);
  const placeFile = useAsync(
    !api.enabled && closest ? () => products.place(region, closest.id) : null,
    [api.enabled, products, region, closest?.id],
  );

  if (!inside) {
    const other =
      regions?.status === "ok" ? regionForPoint(regions.data.flatMap((r) => (r.info ? [r.info] : [])), pos.lat, pos.lon) : null;
    return (
      <div className="notice" role="status">
        <p>You're outside {index.region.name}.</p>
        {regions?.status === "loading" && <Loading />}
        {other ? (
          <p>
            <Link to={`/r/${other.id}/nearby`}>Switch to {other.name}</Link>
          </p>
        ) : (
          regions?.status === "ok" && <p className="muted">No published region covers your location yet.</p>
        )}
      </div>
    );
  }

  return (
    <>
      <section className="section" aria-labelledby="near-places-h">
        <h2 id="near-places-h">Closest places</h2>
        <ul className="card-list">
          {near.map(({ id, place, km: d }) => (
            <li key={id}>
              <Link className="card card-link" to={`/r/${region}/places/${encodeURIComponent(id)}`}>
                <span className="card-title">{place.name}</span>
                <span className="muted small">{km(d)} away</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <section className="section" aria-labelledby="near-lists-h">
        <h2 id="near-lists-h">What you might see here this week</h2>
        {api.enabled ? (
          <Async state={apiLists} what="Lists here">
            {(l) => <ListsPanel region={region} view={listsFromApi(l)} />}
          </Async>
        ) : closest ? (
          <>
            <p className="muted small">Lists for {closest.place.name}, the closest place.</p>
            <Async state={placeFile} what="Lists here">
              {(f) => {
                const view = listsFromPlaceFile(f, week);
                return view ? <ListsPanel region={region} view={view} /> : null;
              }}
            </Async>
          </>
        ) : (
          <p className="muted">No published place is close to you. Choose one of the places above.</p>
        )}
      </section>
      <section className="section" aria-labelledby="near-recent-h">
        <h2 id="near-recent-h">Right now</h2>
        <RecentPanel region={region} load={() => api.nearbyRecent(pos.lat, pos.lon)} deps={[pos.lat, pos.lon]} />
      </section>
    </>
  );
}
