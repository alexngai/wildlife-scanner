import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const pages = [
  "/",
  "/r/testland",
  "/r/testland/species/testus-primus?week=20&place=test-cove",
  "/r/testland/species/testus-primus?week=20&view=compare",
  "/r/testland/species/rarus-tertius",
  "/r/testland/places/test-cove?week=20",
  "/r/testland/nearby",
  "/about",
];

for (const theme of ["light", "dark"] as const) {
  for (const path of pages) {
    test(`no serious accessibility violations: ${path} (${theme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: theme });
      await page.route("**/config.json", (r) =>
        r.fulfill({ json: { staticBase: "/data", apiBase: "", regions: ["testland"], basemap: "none" } }),
      );
      await page.goto(path);
      await expect(page.locator("main h1")).toBeVisible();
      await page.waitForLoadState("networkidle");
      // Open on-request sections and "as a table" disclosures so their contents are checked too.
      const compare = page.getByRole("button", { name: "Compare places" });
      if (await compare.count()) {
        await compare.click();
        await expect(page.locator(".hotspot-list")).toBeVisible();
      }
      for (const summary of await page.locator("details.data-table > summary").all()) await summary.click();
      // The map canvas is described by its aria-label; MapLibre's own controls are third-party.
      const results = await new AxeBuilder({ page }).exclude(".maplibregl-ctrl").analyze();
      const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(
        serious.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")})`),
      ).toEqual([]);
    });
  }
}
