import type { ReactNode } from "react";
import { Link } from "react-router";
import { km, methodLabel, times } from "../lib/format";
import { useLifeList } from "../lib/lifelist";
import { newForYou, type GroupView, type ListItem, type ListsView } from "../lib/lists";
import { ConfidenceBadge, Chance } from "./Confidence";
import { LicenseNote } from "./License";

function SeenToggle({ id, name }: { id: string; name: string }) {
  const { seen, toggle } = useLifeList();
  const on = seen.has(id);
  return (
    <button
      type="button"
      className={`seen-toggle${on ? " on" : ""}`}
      aria-pressed={on}
      aria-label={`${name}: ${on ? "on your life list" : "add to your life list"}`}
      onClick={() => toggle(id)}
    >
      {on ? "✓ Seen" : "+ Seen"}
    </button>
  );
}

function Item({ region, it, extra }: { region: string; it: ListItem; extra?: ReactNode }) {
  return (
    <li className="item">
      <div className="item-main">
        <Link to={`/r/${region}/species/${encodeURIComponent(it.taxonId)}`} className="item-name">
          {it.name}
        </Link>
        <span className="item-meta">
          <Chance p={it.p} level={it.confidence} /> {extra}
          <ConfidenceBadge level={it.confidence === "high" ? "none" : it.confidence} />
          {it.coarser && it.resolutionKm !== null && (
            <span className="muted small"> · from the wider {km(it.resolutionKm)} area</span>
          )}
        </span>
      </div>
      <SeenToggle id={it.taxonId} name={it.name} />
    </li>
  );
}

function List({
  title,
  hint,
  items,
  region,
  extra,
  empty,
}: {
  title: string;
  hint: string;
  items: ListItem[];
  region: string;
  extra?: (it: ListItem) => ReactNode;
  empty: string;
}) {
  return (
    <section className="subsection">
      <h4>{title}</h4>
      <p className="muted small">{hint}</p>
      {items.length === 0 ? (
        <p className="muted small">{empty}</p>
      ) : (
        <ul className="item-list">
          {items.map((it) => (
            <Item key={it.taxonId} region={region} it={it} extra={extra?.(it)} />
          ))}
        </ul>
      )}
    </section>
  );
}

function Group({ region, g }: { region: string; g: GroupView }) {
  const { seen } = useLifeList();
  const fresh = newForYou(g, seen);
  return (
    <section className="group card">
      <h3>{g.label}</h3>
      <p className="muted small">Chances {methodLabel(g.method)}; compare them only within this list.</p>
      <List
        title="Most likely"
        hint="The species you're most likely to record."
        items={g.mostLikely}
        region={region}
        empty="Nothing published for this week."
      />
      <List
        title="Special here"
        hint="Much more likely here than in the surrounding area."
        items={g.specialHere}
        region={region}
        extra={(it) => (it.lift ? <span className="muted small">· {times(it.lift)} the area average</span> : null)}
        empty="Nothing stands out here this week."
      />
      <List
        title="Peaking now"
        hint="Well above their usual level for the year."
        items={g.peakingNow}
        region={region}
        extra={(it) =>
          it.seasonalIndex ? <span className="muted small">· {times(it.seasonalIndex)} its yearly average</span> : null
        }
        empty="Nothing is peaking this week."
      />
      <List
        title="New for you"
        hint={`From the lists above, species not on your life list (${seen.size} seen, saved only in this browser).`}
        items={fresh}
        region={region}
        empty="You've seen everything on these lists."
      />
      <LicenseNote license={g.license} />
    </section>
  );
}

export function ListsPanel({ region, view }: { region: string; view: ListsView }) {
  return (
    <div className="lists">
      {view.groups.length === 0 && <p className="muted">No species lists are published for this week.</p>}
      {view.groups.map((g) => (
        <Group key={g.id} region={region} g={g} />
      ))}
      {view.awareness.length > 0 && (
        <section className="group card awareness" aria-labelledby="aware-h">
          <h3 id="aware-h">Also in the wider area</h3>
          <p className="muted small">{view.awarenessMessage}</p>
          <ul className="plain-list">
            {view.awareness.map((a) => (
              <li key={a.taxonId}>
                <Link to={`/r/${region}/species/${encodeURIComponent(a.taxonId)}`}>{a.name}</Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      {view.label && <p className="muted small">{view.label}</p>}
    </div>
  );
}

