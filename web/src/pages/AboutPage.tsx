import { useServices } from "../context";
import { CONFIDENCE_TEXT, LEVEL_TEXT, TIER_DELAY, TIER_NAME } from "../lib/policy";
import { setLifeList, useLifeList } from "../lib/lifelist";
import { useAsync } from "../lib/useAsync";
import { Async } from "../components/Status";
import { usePageTitle } from "../lib/usePageTitle";

export function AboutPage() {
  const { config, api } = useServices();
  const sources = useAsync(api.enabled ? () => api.sources() : null, [api]);
  const { seen } = useLifeList();
  usePageTitle("About");
  return (
    <div className="page">
      <header className="page-head">
        <h1>About wildlife-radar</h1>
      </header>
      <section className="card prose" aria-label="Introduction">
        <p>
          wildlife-radar forecasts where and when you might encounter wildlife, for any species, from public
          biodiversity records. It is a <strong>free, non-commercial, educational</strong> project run by an individual.
        </p>
      </section>
      <section className="card prose">
        <h2>Source code</h2>
        <p>
          The code is free software under the{" "}
          <a href="https://www.gnu.org/licenses/agpl-3.0.html" rel="license noreferrer" target="_blank">
            GNU Affero General Public License v3
          </a>
          . Get the source of this site and its data service at{" "}
          <a href={config.sourceUrl} rel="noreferrer" target="_blank">
            {config.sourceUrl.replace(/^https?:\/\//, "")}
          </a>
          .
        </p>
      </section>
      <section className="card prose">
        <h2>What the numbers mean</h2>
        <p>
          Numbers are the chance of recording a species <em>per outing</em> (or per checklist, dive or survey unit, as
          each list says) in an area and week, from historical records corrected for where observers go. They are
          estimates, not guarantees, and are comparable only within one list.
        </p>
        <ul>
          {Object.entries(LEVEL_TEXT).map(([lvl, text]) => (
            <li key={lvl}>
              <strong>{text}</strong>
              {lvl === "0" && ": how often it's recorded at this time of year."}
              {lvl === "1" &&
                ": the seasonal estimate adjusted for the day's conditions, where a model passed its backtest."}
              {lvl === "2" && ": also adjusted for what's been reported recently, where a model passed its backtest."}
            </li>
          ))}
        </ul>
        <p>
          Confidence levels: {Object.values(CONFIDENCE_TEXT).slice(0, 4).join(", ")}. "Not enough data" never means the
          species is absent.
        </p>
      </section>
      <section className="card prose">
        <h2>Sensitive species</h2>
        <p>
          Some species are protected from disturbance, collection or persecution. They're shown at a coarser scale,
          later, or for awareness only (presence in a wider area with no numbers or timings), or not at all. Species we
          don't show look the same as species we have no data for.
        </p>
        <div className="data-table">
          <table>
            <caption>Minimum delay before recent sightings are shown</caption>
            <thead>
              <tr>
                <th scope="col">Species</th>
                <th scope="col">Delay</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(TIER_DELAY).map(([tier, delay]) => (
                <tr key={tier}>
                  <th scope="row">{TIER_NAME[Number(tier)]}</th>
                  <td>{delay}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card prose">
        <h2 id="data">Data licences and attribution</h2>
        <p>
          Every map and list shows its own licence and attribution. Much of the data is licensed{" "}
          <a href="https://creativecommons.org/licenses/by-nc/4.0/" rel="license noreferrer" target="_blank">
            CC BY-NC 4.0
          </a>
          , so it may not be used commercially. Records come through GBIF and iNaturalist; condition signals from NOAA.
        </p>
        <Async state={sources}>
          {(list) => (
            <ul>
              {list.map((s) => (
                <li key={s.source_id}>
                  <a href={s.terms_url} rel="noreferrer" target="_blank">
                    {s.name}
                  </a>
                  : {s.attribution}
                </li>
              ))}
            </ul>
          )}
        </Async>
        <p>
          Base map: map data © OpenStreetMap contributors (ODbL), tiles from the configured map provider (credited on
          each map).
        </p>
      </section>
      <section className="card prose">
        <h2>Privacy</h2>
        <ul>
          <li>Your life list is stored only in this browser. It is never sent to our service or anyone else.</li>
          <li>
            "Nearby" asks for your location only when you press the button, rounds it to about 100 m, and doesn't keep
            it.
          </li>
          <li>
            Map images (base map, satellite imagery, terrain and depth layers) load from the providers credited on each
            map, so they see which area you're looking at, as with any web map.
          </li>
          <li>No accounts, no tracking, no ads.</li>
        </ul>
        <p>
          Your life list has {seen.size} species.{" "}
          {seen.size > 0 && (
            <button
              type="button"
              className="link-button"
              onClick={() => {
                if (window.confirm("Clear your life list from this browser?")) setLifeList([]);
              }}
            >
              Clear it
            </button>
          )}
        </p>
      </section>
    </div>
  );
}
