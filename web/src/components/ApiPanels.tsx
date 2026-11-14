import type { ReactNode } from "react";
import type { Driver, Forecast, HourlyForecast, RecentActivity, RecentItem, Timing, Where } from "../api/client";
import { useServices } from "../context";
import { capitalize, km, oddsMultiplier, percent, shortDate, times } from "../lib/format";
import { LEVEL_TEXT, delayText } from "../lib/policy";
import { useAsync } from "../lib/useAsync";
import { Async } from "./Status";
import { Link } from "react-router";

export function humanize(s: string): string {
  const t = s.replace(/[_:]+/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function NoApi({ what }: { what: string }) {
  return <p className="muted">{what} come from the live service, which this site isn't connected to right now.</p>;
}

function DriverList({ drivers }: { drivers: Driver[] }) {
  if (drivers.length === 0) return null;
  const sorted = [...drivers].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  return (
    <ul className="drivers">
      {sorted.map((d) => {
        const m = oddsMultiplier(d.contribution);
        const up = d.contribution > 0.01;
        const down = d.contribution < -0.01;
        return (
          <li key={`${d.term}-${d.signal}`} className={up ? "up" : down ? "down" : "flat"}>
            <span className="driver-dir" aria-hidden="true">
              {up ? "▲" : down ? "▼" : "•"}
            </span>
            <span className="driver-name">{humanize(d.signal)}</span>
            {d.value !== null && d.value !== undefined && (
              <span className="muted small"> ({Number(d.value.toFixed(2))})</span>
            )}
            <span className="driver-effect">
              {up ? `raises the odds ${times(m)}` : down ? `lowers the odds ${times(m)}` : "little effect"}
            </span>
            {d.hypothesis && <span className="badge">expected from species profile</span>}
          </li>
        );
      })}
    </ul>
  );
}

/** Today's (or a chosen day's) forecast at a place or point, with its drivers ("why"). */
export function ForecastPanel({ taxonId, where, date }: { taxonId: string; where: Where; date: string }) {
  const { api } = useServices();
  const key = JSON.stringify(where);
  const state = useAsync(api.enabled ? () => api.forecast(taxonId, where, date) : null, [api, taxonId, key, date]);
  if (!api.enabled) return <NoApi what="Daily forecasts" />;
  return (
    <Async state={state} what="Daily forecast" loading="Loading forecast…">
      {(f: Forecast) => (
        <div className="forecast">
          <p className="big-number">
            {percent(f.p)} <span className="unit">chance per outing on {shortDate(f.day)}</span>
          </p>
          <p>
            <span className="badge">{LEVEL_TEXT[f.level] ?? `Level ${f.level}`}</span>
            {f.level > 0 && <span className="muted"> · usual for this week: {percent(f.p_level0)}</span>}
          </p>
          <p className="muted small">For the {km(f.resolution_km)} area around this location.</p>
          {(f.drivers ?? []).length > 0 ? (
            <>
              <h4>Why</h4>
              <DriverList drivers={f.drivers ?? []} />
            </>
          ) : (
            <p className="muted small">
              {f.level === 0
                ? "No daily factors are modelled for this species yet, so this is the usual chance for this week. It doesn't mean conditions don't matter."
                : "No single factor stands out today."}
            </p>
          )}
          <Notes notes={f.notes} />
        </div>
      )}
    </Async>
  );
}

function Notes({ notes }: { notes?: string[] }) {
  if (!notes || notes.length === 0) return null;
  return (
    <ul className="notes muted small">
      {notes.map((n) => (
        <li key={n}>{n.charAt(0).toUpperCase() + n.slice(1)}.</li>
      ))}
    </ul>
  );
}

const hourFmt = (iso: string) => {
  const m = /T(\d{2}):/.exec(iso);
  return m ? `${m[1]}:00` : iso;
};

/** The day's chance by local hour, where a time-of-day pattern is known. */
export function HourlyPanel({ taxonId, where, date }: { taxonId: string; where: Where; date: string }) {
  const { api } = useServices();
  const key = JSON.stringify(where);
  const state = useAsync(api.enabled ? () => api.hourly(taxonId, where, date) : null, [api, taxonId, key, date]);
  if (!api.enabled) return <NoApi what="Hourly timings" />;
  return (
    <Async
      state={state}
      what="Hourly timing"
      notAvailable={<p className="muted">Hourly timing isn't available for this species.</p>}
    >
      {(h: HourlyForecast) => {
        const hours = h.hours ?? [];
        const best = h.best ?? [];
        const factors = h.factors ?? {};
        const flat = hours.every((s) => Math.abs(s.multiplier - 1) < 0.02);
        if (hours.length === 0 || flat) {
          return (
            <>
              <p className="muted">
                No time-of-day pattern is known for this species here, so every hour looks the same.
              </p>
              <Notes notes={h.notes} />
            </>
          );
        }
        const max = Math.max(...hours.map((s) => s.multiplier));
        return (
          <div className="hourly">
            {best.length > 0 && (
              <p>
                Best hours ({h.timezone}): <strong>{best.map(hourFmt).join(", ")}</strong>
              </p>
            )}
            <ol className="hour-bars" aria-label="Relative odds by hour">
              {hours.map((s) => (
                <li key={s.start} title={`${hourFmt(s.start)}: ${times(s.multiplier)} a typical hour`}>
                  <span className="hour-bar" style={{ height: `${Math.max(4, (s.multiplier / max) * 100)}%` }} />
                  <span className="hour-label">{hourFmt(s.start).slice(0, 2)}</span>
                  <span className="sr-only">
                    {hourFmt(s.start)}: {times(s.multiplier)} a typical hour
                    {Object.keys(s.factors ?? {}).length > 0 &&
                      ` (${Object.entries(s.factors ?? {})
                        .map(([k, v]) => `${humanize(k)}: ${v}`)
                        .join(", ")})`}
                  </span>
                </li>
              ))}
            </ol>
            <p className="muted small">Bars show the odds relative to a typical hour of that day.</p>
            {Object.keys(factors).length > 0 && (
              <ul className="factors small">
                {Object.entries(factors).map(([factor, levels]) => (
                  <li key={factor}>
                    <strong>{humanize(factor)}:</strong>{" "}
                    {Object.entries(levels)
                      .map(([lvl, m]) => `${humanize(lvl)} ${times(m)}`)
                      .join(" · ")}
                  </li>
                ))}
              </ul>
            )}
            <Notes notes={h.notes} />
          </div>
        );
      }}
    </Async>
  );
}

/** When in the day (and tide) a species is recorded, relative to its group (region-wide). */
/** Readable names for the timing signals; anything else is humanized. */
const SIGNAL_LABELS: Record<string, string> = {
  "astro.diel_phase": "Time of day",
  "astro.hours_since_sunset": "Hours since sunset",
  "astro.moonlight": "Moonlight",
  "tide.height_m": "Tide height",
  "tide.stage": "Tide stage",
};

function signalLabel(signal: string): string {
  return SIGNAL_LABELS[signal] ?? humanize(signal.replace(/^[a-z]+\./, ""));
}

function categoryLabel(signal: string, category: string): string {
  const q = /^Q(\d)$/.exec(category);
  if (q && signal.startsWith("tide.height")) {
    return { "1": "Lowest", "2": "Low", "3": "Middle", "4": "High", "5": "Highest" }[q[1] ?? ""] ?? category;
  }
  return humanize(category);
}

export function TimingPanel({ taxonId, region }: { taxonId: string; region: string }) {
  const { api } = useServices();
  const state = useAsync(api.enabled ? () => api.timing(taxonId, region) : null, [api, taxonId, region]);
  if (!api.enabled) return null;
  return (
    <Async state={state} notAvailable={<p className="muted">No time-of-day records are published for this species.</p>}>
      {(t: Timing) => (
        <div className="timing">
          <div className="timing-grid">
            {Object.entries(t.signals).map(([signal, cats]) => (
              <div key={signal}>
                <h4>{signalLabel(signal)}</h4>
                <ul className="index-list">
                  {cats.map((c) => (
                    <li key={c.category}>
                      <span className="index-name">{categoryLabel(signal, c.category)}</span>
                      <span className="index-value">
                        {c.index !== null && (
                          <span className="index-bar" aria-hidden="true">
                            <span
                              className={c.index > 1.1 ? "up" : c.index < 0.9 ? "down" : undefined}
                              style={{ width: `${Math.min(100, (c.index / 2) * 100)}%` }}
                            />
                          </span>
                        )}
                        {c.index === null ? "not enough data" : times(c.index)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <p className="muted small">{t.note}</p>
        </div>
      )}
    </Async>
  );
}

function RecentList({ region, items, kind }: { region: string; items: RecentItem[]; kind: "up" | "recent" }) {
  return (
    <ul className="item-list">
      {items.map((it) => (
        <li key={`${it.taxon_id}-${it.effort_group}`} className="item">
          <div className="item-main">
            <Link to={`/r/${region}/species/${encodeURIComponent(it.taxon_id)}`} className="item-name">
              {capitalize(it.common_name || it.scientific_name || it.taxon_id)}
            </Link>
            <span className="item-meta">
              {kind === "up" ? (
                <>
                  {percent(it.p_now)} today <span className="muted">(usually {percent(it.p_usual)})</span>
                  {it.odds_boost ? <span className="muted"> · odds {times(it.odds_boost)}</span> : null}
                </>
              ) : (
                <>
                  reported on {it.recent_detections} of {it.recent_outings} outings
                </>
              )}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** "Picking up now" and "reported recently", with the publication delay always shown. */
export function RecentPanel({
  region,
  load,
  deps,
}: {
  region: string;
  load: () => Promise<RecentActivity>;
  deps: unknown[];
}) {
  const { api } = useServices();
  const state = useAsync(api.enabled ? load : null, [api, ...deps]);
  if (!api.enabled) return <NoApi what="Recent sightings" />;
  return (
    <Async state={state} what="Recent activity">
      {(r: RecentActivity) => {
        const pickingUp = r.picking_up ?? [];
        const reported = r.reported_recently ?? [];
        return (
          <div className="recent">
            <p className="delay-note">
              Sightings through <strong>{shortDate(r.data_through)}</strong> (last {r.window_days} days,{" "}
              {km(r.resolution_km)} area). Recent records are published with a delay: at least {delayText(0)} for openly
              mapped species, longer for sensitive ones, which never appear here.
            </p>
            <Section title="Picking up now" empty="Nothing is picking up beyond its usual level right now.">
              {pickingUp.length > 0 && <RecentList region={region} items={pickingUp} kind="up" />}
            </Section>
            <Section title="Reported recently" empty="No recent reports published for this area.">
              {reported.length > 0 && <RecentList region={region} items={reported} kind="recent" />}
            </Section>
            <Notes notes={r.notes} />
          </div>
        );
      }}
    </Async>
  );
}

function Section({ title, empty, children }: { title: string; empty: string; children: ReactNode }) {
  return (
    <section className="subsection">
      <h3>{title}</h3>
      {children || <p className="muted small">{empty}</p>}
    </section>
  );
}
