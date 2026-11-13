import type { TaxonEntry } from "../products/types";
import { searchTaxa } from "./search";

const t = (id: string, common: string | null, sci: string, aliases: string[] = []): TaxonEntry => ({
  id,
  common_name: common,
  scientific_name: sci,
  aliases,
  group: "birds",
  tier: 0,
  mode: "forecast",
  records: 1,
});

const taxa = [t("a", "Sea Otter", "Enhydra lutris"), t("b", "Otter Trawl Gull", "Larus x"), t("c", null, "Ottera z", ["Ötter alias"])];

describe("species search", () => {
  it("ranks prefix matches first, then word prefixes", () => {
    expect(searchTaxa(taxa, "otter").map((x) => x.id)).toEqual(["b", "c", "a"]);
    expect(searchTaxa(taxa, "sea").map((x) => x.id)).toEqual(["a"]);
  });
  it("ignores case and accents and matches scientific names", () => {
    expect(searchTaxa(taxa, "ENHYDRA")[0]!.id).toBe("a");
    expect(searchTaxa(taxa, "otter alias")[0]!.id).toBe("c");
  });
  it("returns nothing for empty queries", () => {
    expect(searchTaxa(taxa, "  ")).toEqual([]);
  });
});
