import { DEFAULT_LAYERS, mergeConfig, DEFAULT_CONFIG } from "../config";
import { effectiveChoice, getLayerChoice, resetLayerChoice, setLayerChoice } from "./mapLayers";

describe("map layers", () => {
  beforeEach(() => resetLayerChoice());

  it("keeps the choice to what the deployment offers", () => {
    expect(effectiveChoice({ base: "satellite", overlays: ["terrain", "gone"], dataOpacity: 0.5 }, DEFAULT_LAYERS, true)).toEqual({
      base: "satellite",
      overlays: ["terrain"],
      dataOpacity: 0.5,
    });
    expect(effectiveChoice({ base: "gone", overlays: [], dataOpacity: 1 }, DEFAULT_LAYERS, true).base).toBe("map");
    expect(effectiveChoice({ base: "map", overlays: [], dataOpacity: 1 }, [], false).base).toBe("plain");
  });

  it("remembers the choice in this browser, with opacity clamped", () => {
    setLayerChoice({ base: "satellite", overlays: ["depth"], dataOpacity: 0 });
    resetLayerChoice();
    expect(getLayerChoice()).toEqual({ base: "satellite", overlays: ["depth"], dataOpacity: 0.2 });
  });

  it("takes layers from config.json, dropping malformed ones", () => {
    const good = { id: "x", name: "X", kind: "overlay", type: "raster", tiles: ["https://t/{z}/{x}/{y}.png"], attribution: "X" };
    const c = mergeConfig(DEFAULT_CONFIG, { layers: [good, { id: "bad" }] });
    expect(c.layers).toEqual([good]);
    expect(mergeConfig(DEFAULT_CONFIG, {}).layers).toBe(DEFAULT_LAYERS);
    expect(mergeConfig(DEFAULT_CONFIG, { layers: [] }).layers).toEqual([]);
  });
});
