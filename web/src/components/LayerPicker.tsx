import { useId } from "react";
import type { MapLayerConfig } from "../config";
import { setLayerChoice, type LayerChoice } from "../lib/mapLayers";
import { LayersIcon } from "./Icons";

/** The map's layer picker: base map, overlays and how strongly the data is drawn. */
export function LayerPicker({
  layers,
  hasBasemap,
  choice,
}: {
  layers: MapLayerConfig[];
  hasBasemap: boolean;
  choice: LayerChoice;
}) {
  const id = useId();
  const bases = [
    ...(hasBasemap ? [{ id: "map", name: "Map" }] : []),
    ...layers.filter((l) => l.kind === "base").map((l) => ({ id: l.id, name: l.name })),
    { id: "plain", name: "Plain" },
  ];
  const overlays = layers.filter((l) => l.kind === "overlay");
  const set = (change: Partial<LayerChoice>) => setLayerChoice({ ...choice, ...change });
  return (
    <details className="layer-picker">
      <summary>
        <LayersIcon />
        Layers
      </summary>
      <div className="layer-panel">
        <fieldset>
          <legend>Base map</legend>
          {bases.map((b) => (
            <label key={b.id}>
              <input
                type="radio"
                name={`${id}-base`}
                value={b.id}
                checked={choice.base === b.id}
                onChange={() => set({ base: b.id })}
              />{" "}
              {b.name}
            </label>
          ))}
        </fieldset>
        {overlays.length > 0 && (
          <fieldset>
            <legend>Overlays</legend>
            {overlays.map((o) => (
              <label key={o.id}>
                <input
                  type="checkbox"
                  checked={choice.overlays.includes(o.id)}
                  onChange={(e) =>
                    set({
                      overlays: e.target.checked
                        ? [...choice.overlays, o.id]
                        : choice.overlays.filter((x) => x !== o.id),
                    })
                  }
                />{" "}
                {o.name}
              </label>
            ))}
          </fieldset>
        )}
        <label className="opacity-row" htmlFor={`${id}-opacity`}>
          Data opacity
        </label>
        <input
          id={`${id}-opacity`}
          type="range"
          min={20}
          max={100}
          step={10}
          value={Math.round(choice.dataOpacity * 100)}
          aria-valuetext={`${Math.round(choice.dataOpacity * 100)}%`}
          onChange={(e) => set({ dataOpacity: Number(e.target.value) / 100 })}
        />
        <p className="muted small">Saved in this browser. Map images come from the providers credited on the map.</p>
      </div>
    </details>
  );
}
