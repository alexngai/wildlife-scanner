import { useId, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { km, methodLabel, times } from "../lib/format";
import { useLifeList } from "../lib/lifelist";
import { newForYou, type GroupView, type ListItem, type ListsView } from "../lib/lists";
import { Chance, ConfidenceMeter } from "./Confidence";
import { CheckIcon, PlusIcon } from "./Icons";
import { LicenseNote } from "./License";
import { PhotoCredits, SpeciesThumb } from "./SpeciesPhoto";
import { usePhotos } from "../hooks";
import type { ShownPhoto } from "../lib/photos";

/** Rows shown before "Show all". */
const FIRST = 10;
const AWARE_FIRST = 12;

type Tab = "likely" | "special" | "peaking" | "new";

function SeenToggle({ id, name }: { id: string; name: string }) {
  const { seen, toggle } = useLifeList();
  const on = seen.has(id);
  return (
    <button
      type="button"
      className={`seen-toggle${on ? " on" : ""}`}
      aria-pressed={on}
      title={on ? "On your life list (saved in this browser)" : "Add to your life list (saved in this browser)"}
      onClick={() => toggle(id)}
    >
      {on ? <CheckIcon /> : <PlusIcon />}
      <span className="sr-only">Seen {name}</span>
    </button>
  );
}

function Item({
  region,
  it,
  rank,
  extra,
  photo,
  group,
}: {
  region: string;
  it: ListItem;
  rank?: number;
  extra?: ReactNode;
  photo?: ShownPhoto;
  group?: string;
}) {
  return (
    <li className="item">
      {rank !== undefined && (
        <span className="item-rank" aria-hidden="true">
          {rank}
        </span>
      )}
      <SpeciesThumb photo={photo} group={group} />
      <div className="item-main">
        <Link to={`/r/${region}/species/${encodeURIComponent(it.taxonId)}`} className="item-name">
          {it.name}
        </Link>
        <span className="item-meta">
          <Chance p={it.p} level={it.confidence} />
          <ConfidenceMeter level={it.confidence} />
          {extra}
          {it.coarser && it.resolutionKm !== null && <span>from the wider {km(it.resolutionKm)} area</span>}
        </span>
      </div>
      <SeenToggle id={it.taxonId} name={it.name} />
    </li>
  );
}

/** The busiest group (most species likely) is the most useful default. */
function busiest(groups: GroupView[]): GroupView | undefined {
  const score = (g: GroupView) => g.mostLikely.reduce((s, i) => s + i.p, 0);
  return [...groups].sort((a, b) => score(b) - score(a))[0];
}

const LIKELY = {
  id: "likely" as Tab,
  label: "Most likely",
  hint: "The species you're most likely to record.",
  empty: "Nothing published for this week.",
};

const TABS: { id: Tab; label: string; hint: string; empty: string }[] = [
  LIKELY,
  {
    id: "special",
    label: "Special here",
    hint: "Much more likely here than in the surrounding area.",
    empty: "Nothing stands out here this week.",
  },
  {
    id: "peaking",
    label: "Peaking now",
    hint: "Well above their usual level for the year.",
    empty: "Nothing is peaking this week.",
  },
  {
    id: "new",
    label: "New for you",
    hint: "Species on these lists that aren't on your life list (saved only in this browser).",
    empty: "You've seen everything on these lists.",
  },
];

export function ListsPanel({ region, view }: { region: string; view: ListsView }) {
  const selectId = useId();
  const { seen } = useLifeList();
  const photos = usePhotos(region);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("likely");
  const [all, setAll] = useState(false);
  const [allAware, setAllAware] = useState(false);
  const groups = useMemo(() => [...view.groups].sort((a, b) => a.label.localeCompare(b.label)), [view.groups]);
  const g = groups.find((x) => x.id === groupId) ?? busiest(view.groups);

  const items: Record<Tab, ListItem[]> = g
    ? { likely: g.mostLikely, special: g.specialHere, peaking: g.peakingNow, new: newForYou(g, seen) }
    : { likely: [], special: [], peaking: [], new: [] };
  const current = TABS.find((t) => t.id === tab) ?? LIKELY;
  const rows = items[tab];
  const shown = all ? rows : rows.slice(0, FIRST);
  const extra = (it: ListItem): ReactNode =>
    tab === "special" && it.lift ? (
      <span>{times(it.lift)} the area average</span>
    ) : tab === "peaking" && it.seasonalIndex ? (
      <span>{times(it.seasonalIndex)} its yearly average</span>
    ) : null;

  return (
    <div className="lists">
      {!g ? (
        <p className="muted">No species lists are published for this week.</p>
      ) : (
        <>
          <div className="list-controls">
            {groups.length > 1 ? (
              <label className="field" htmlFor={selectId}>
                Group
                <select
                  id={selectId}
                  value={g.id}
                  onChange={(e) => {
                    setGroupId(e.target.value);
                    setAll(false);
                  }}
                >
                  {groups.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.label}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="card-title">{g.label}</p>
            )}
            <div className="segmented tabs" role="group" aria-label="List">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  aria-pressed={tab === t.id}
                  onClick={() => {
                    setTab(t.id);
                    setAll(false);
                  }}
                >
                  {t.label}
                  <span className="count">{items[t.id].length}</span>
                </button>
              ))}
            </div>
          </div>
          <section className="group" aria-labelledby={`${selectId}-list`}>
            <h3 id={`${selectId}-list`} className="sr-only">
              {current.label}
            </h3>
            <p className="muted small">
              {current.hint} Chances {methodLabel(g.method)}; compare them only within this list.
            </p>
            {rows.length === 0 ? (
              <p className="muted">{current.empty}</p>
            ) : (
              <ul className="item-list">
                {shown.map((it, i) => (
                  <Item
                    key={it.taxonId}
                    region={region}
                    it={it}
                    photo={photos.get(it.taxonId)}
                    group={g.id.split(":")[0]}
                    rank={tab === "likely" ? i + 1 : undefined}
                    extra={extra(it)}
                  />
                ))}
              </ul>
            )}
            {rows.length > FIRST && (
              <button type="button" className="button secondary small show-more" onClick={() => setAll((v) => !v)}>
                {all ? "Show fewer" : `Show all ${rows.length}`}
              </button>
            )}
            <PhotoCredits
              items={shown.flatMap((it) => {
                const photo = photos.get(it.taxonId);
                return photo ? [{ name: it.name, photo }] : [];
              })}
            />
            <LicenseNote license={g.license} />
          </section>
        </>
      )}
      {view.awareness.length > 0 && (
        <section className="awareness" aria-labelledby={`${selectId}-aware`}>
          <h3 id={`${selectId}-aware`}>Also in the wider area</h3>
          <p className="muted small">{view.awarenessMessage}</p>
          <ul className="chip-list">
            {(allAware ? view.awareness : view.awareness.slice(0, AWARE_FIRST)).map((a) => (
              <li key={a.taxonId}>
                <Link to={`/r/${region}/species/${encodeURIComponent(a.taxonId)}`}>{a.name}</Link>
              </li>
            ))}
          </ul>
          {view.awareness.length > AWARE_FIRST && (
            <button type="button" className="button secondary small show-more" onClick={() => setAllAware((v) => !v)}>
              {allAware ? "Show fewer" : `Show all ${view.awareness.length}`}
            </button>
          )}
        </section>
      )}
      {view.label && <p className="muted small">{view.label}</p>}
    </div>
  );
}
