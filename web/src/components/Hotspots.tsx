import { lazy, Suspense, useId, useMemo, useState } from "react";
import { Link } from "react-router";
import { useServices } from "../context";
import { percent } from "../lib/format";
import { hotspotGroups, hotspots, type HotspotPlace } from "../lib/hotspots";
import { useAsync } from "../lib/useAsync";
import { weekOf } from "../lib/weeks";
import type { StaticIndex } from "../products/types";
import { useThemeContext } from "../themeContext";
import { Loading } from "./Status";
import { WeekSlider } from "./WeekSlider";

/** Place lists hold the top 20 species per group, so counts at 20 may be more. */
const LIST_TOP = 20;
const MapView = lazy(() => import("./MapView"));
const NO_CELLS = { type: "FeatureCollection" as const, features: [] };

/**
 * "Where to go this week": places compared within one effort group by likely species per
 * outing. Place files are large (every week of lists), so they load only when asked for.
 */
export function Hotspots({ region, index }: { region: string; index: StaticIndex }) {
  const [open, setOpen] = useState(false);
  const count = Object.keys(index.places).length;
  if (count < 2) return null;
  return (
    <section aria-labelledby="hotspots-h" className="section">
      <h2 id="hotspots-h">Where to go</h2>
      {open ? (
        <HotspotsView region={region} index={index} />
      ) : (
        <>
          <p className="muted">Compare the {count} places by how many species you're likely to record, week by week.</p>
          <button type="button" className="button" onClick={() => setOpen(true)}>
            Compare places
          </button>
        </>
      )}
    </section>
  );
}

function HotspotsView({ region, index }: { region: string; index: StaticIndex }) {
  const { products, config } = useServices();
  const { effective: theme } = useThemeContext();
  const selectId = useId();
  const [week, setWeek] = useState(weekOf(new Date()));
  const [chosen, setChosen] = useState<string | null>(null);
  const year = new Date().getFullYear();

  const loaded = useAsync(
    async () => {
      const entries = Object.entries(index.places);
      const files = await Promise.allSettled(entries.map(([id]) => products.place(region, id)));
      return entries.flatMap(([id, ref], i): HotspotPlace[] => {
        const r = files[i];
        return r?.status === "fulfilled" ? [{ id, name: ref.name, lat: ref.lat, lon: ref.lon, file: r.value }] : [];
      });
    },
    [products, region, index],
  );
  const places = loaded?.status === "ok" ? loaded.data : null;
  const groups = useMemo(() => (places ? hotspotGroups(places, week) : []), [places, week]);
  const group = groups.find((g) => g.id === chosen) ?? groups[0] ?? null;
  const rows = useMemo(() => (places && group ? hotspots(places, week, group.id) : []), [places, week, group]);
  const max = Math.max(0, ...rows.map((r) => r.score ?? 0));
  const mapPlaces = useMemo(
    () =>
      rows.map((r) => ({
        id: r.id,
        name: r.name,
        lat: r.lat,
        lon: r.lon,
        value: r.score === null || max <= 0 ? null : r.score / max,
        note: r.score === null ? "no list for this group" : `about ${r.score.toFixed(1)} species per outing`,
      })),
    [rows, max],
  );

  if (!loaded || loaded.status === "loading") return <Loading label="Loading every place's lists…" />;
  if (!places || places.length === 0) return <p className="muted">The place lists couldn't be loaded.</p>;

  return (
    <div className="hotspots">
      <WeekSlider week={week} year={year} onChange={setWeek} />
      {groups.length === 0 ? (
        <p className="muted">No place has lists for this week.</p>
      ) : (
        <>
          <label className="label inline" htmlFor={selectId}>
            Compare for{" "}
            <select id={selectId} value={group?.id ?? ""} onChange={(e) => setChosen(e.target.value)}>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.label} ({g.places} {g.places === 1 ? "place" : "places"})
                </option>
              ))}
            </select>
          </label>
          <p className="muted small">
            Likely species per outing: the chances in each place's top list added up. Compare places only for the same
            group; lists hold the top 20 species, so busy places may have more.
          </p>
          <div className="map-wrap">
            <Suspense fallback={<div className="map map-placeholder map-short">Loading map…</div>}>
              <MapView
                data={NO_CELLS}
                bounds={index.region.bbox}
                theme={theme}
                basemap={config.basemap}
                places={mapPlaces}
                label={`Map of ${rows.length} places sized by likely species per outing for ${group?.label ?? ""}.`}
                short
              />
            </Suspense>
          </div>
          <ol className="hotspot-list">
            {rows.map((r) => (
              <li key={r.id}>
                <Link to={`/r/${region}/places/${encodeURIComponent(r.id)}?week=${week}`} className="card card-link hotspot">
                  <span className="card-title">{r.name}</span>
                  {r.score === null ? (
                    <span className="muted small">No list for this group this week</span>
                  ) : (
                    <>
                      <span className="hotspot-bar" aria-hidden="true">
                        <span style={{ width: `${max > 0 ? (100 * r.score) / max : 0}%` }} />
                      </span>
                      <span className="small">
                        About <strong>{r.score.toFixed(1)}</strong> species per outing
                        {r.peaking > 0 && ` · ${r.peaking >= LIST_TOP ? `${LIST_TOP} or more` : r.peaking} peaking now`}
                      </span>
                      {r.special && (
                        <span className="muted small">
                          Special here: {r.special.name} ({percent(r.special.p)})
                        </span>
                      )}
                    </>
                  )}
                </Link>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}
