import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const api = (name: string) => readFileSync(`tests/fixtures/api/${name}.json`, "utf8");

async function mockBackend(page: Page) {
  // Runtime config: the fixture region, no external basemap (tests run offline).
  await page.route("**/config.json", (r) =>
    r.fulfill({ json: { staticBase: "/data", apiBase: "/api", regions: ["testland"], basemap: "none" } }),
  );
  await page.route("**/api/**", (r) => {
    const path = new URL(r.request().url()).pathname.replace(/^\/api/, "");
    const table: Record<string, string> = {
      "/species/testus-primus/forecast": api("forecast"),
      "/species/testus-primus/forecast/hourly": api("hourly"),
      "/places/test-cove/recent": api("recent"),
      "/nearby/recent": api("recent"),
      "/regions": api("regions"),
    };
    const body = table[path];
    return body
      ? r.fulfill({ status: 200, contentType: "application/json", body })
      : r.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"Not available"}' });
  });
}

test.beforeEach(async ({ page }) => {
  await mockBackend(page);
});

test("region → search → species map, calendar and forecast", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("link", { name: /Testland/ }).click();
  await page.getByLabel("Search species").fill("testbird");
  await page
    .locator(".result-list")
    .getByRole("link", { name: /Common Testbird/ })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Common Testbird" })).toBeVisible();
  await expect(page.locator(".map canvas")).toBeVisible();
  await expect(page.getByRole("img", { name: /Seasonal calendar/ })).toBeVisible();

  // Move the week slider; the label follows.
  await page.getByRole("button", { name: "Next week" }).click();
  await expect(page).toHaveURL(/week=\d+/);

  // Choose a place for the daily forecast and its drivers.
  await page.getByLabel("Location").selectOption("test-cove");
  await expect(page.getByText("42%")).toBeVisible();
  await expect(page.getByText("Water temperature")).toBeVisible();
  await expect(page.getByText(/Best hours/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("awareness species never show numbers", async ({ page }) => {
  await page.goto("/r/testland/species/rarus-tertius");
  await expect(page.getByText(/Shown for awareness only/)).toBeVisible();
  await expect(page.locator(".map canvas")).toBeVisible();
  await expect(page.locator("main")).not.toContainText("%");
});

test("place page: lists, life list, recent activity with delay", async ({ page }) => {
  await page.goto("/r/testland/places/test-cove?week=20");
  await expect(page.getByRole("heading", { level: 1, name: "Test Cove" })).toBeVisible();
  const seen = page.getByRole("button", { name: "Seen Common Testbird", pressed: false }).first();
  await seen.click();
  await page.reload();
  await expect(page.getByRole("button", { name: "Seen Common Testbird", pressed: true }).first()).toBeVisible();
  // Recent activity (with its delay) shows for the current week.
  await page.goto("/r/testland/places/test-cove");
  await expect(page.getByText(/Sightings through/)).toBeVisible();
});

test("unknown species and deep links work (SPA routing)", async ({ page }) => {
  await page.goto("/r/testland/species/not-a-real-one");
  await expect(page.getByText("This species: not available")).toBeVisible();
});

test("light, dark and system themes", async ({ page }) => {
  await page.goto("/about");
  const theme = page.getByRole("group", { name: "Theme" });
  await expect(theme.getByRole("button", { name: "System theme" })).toHaveAttribute("aria-pressed", "true");
  await theme.getByRole("button", { name: "Light theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await theme.getByRole("button", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "System theme" }).click();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.+/);
});

test("nearby uses (rounded) geolocation", async ({ page, context }) => {
  await context.grantPermissions(["geolocation"]);
  await context.setGeolocation({ latitude: 36.6123456, longitude: -121.9012345 });
  const requests: string[] = [];
  page.on("request", (r) => requests.push(r.url()));
  await page.goto("/r/testland/nearby");
  await page.getByRole("button", { name: "Use my location" }).click();
  await expect(page.getByRole("heading", { name: "Closest places" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Test Cove/ }).first()).toBeVisible();
  await expect(page.getByText(/Sightings through/)).toBeVisible();
  const sent = requests.filter((u) => u.includes("/api/nearby"));
  expect(sent.length).toBeGreaterThan(0);
  for (const u of sent) expect(u).toContain("lat=36.612&lon=-121.901");
});

test("species photos load, and a missing one falls back to the placeholder", async ({ page }) => {
  await page.goto("/r/testland");
  await page.getByLabel("Search species").fill("test");
  const results = page.locator(".result-list");
  const bird = results.getByRole("link", { name: /Common Testbird/ }).locator("img.thumb");
  await expect(bird).toBeVisible();
  await expect
    .poll(() => bird.evaluate((img) => (img as unknown as { naturalWidth: number }).naturalWidth))
    .toBeGreaterThan(0);
  // Its file is gone (404): the image is replaced by the group placeholder.
  const fish = results.getByRole("link", { name: /Seasonal Testfish/ });
  await expect(fish.locator(".thumb-empty")).toBeVisible();
  await expect(fish.locator("img")).toHaveCount(0);
});

test("runs under the production Content-Security-Policy without violations", async ({ page }) => {
  const csp = /Content-Security-Policy: (.+)/.exec(readFileSync("public/_headers", "utf8"))?.[1] ?? "";
  expect(csp).not.toBe("");
  // vite preview doesn't apply _headers (Cloudflare Pages does), so add the policy to each page here.
  await page.route(
    (url) =>
      !url.pathname.startsWith("/data") && !url.pathname.startsWith("/api") && !/\.[a-z0-9]+$/i.test(url.pathname),
    async (route) => {
      const res = await route.fetch();
      await route.fulfill({ response: res, headers: { ...res.headers(), "content-security-policy": csp } });
    },
  );
  const violations: string[] = [];
  page.on("console", (m) => {
    if (/Content Security Policy|Refused to/i.test(m.text())) violations.push(m.text());
  });
  for (const path of [
    "/r/testland/species/testus-primus?week=20&place=test-cove",
    "/r/testland/places/test-cove?week=20",
    "/r/testland",
  ]) {
    await page.goto(path);
    await expect(page.locator("main h1")).toBeVisible();
    await page.waitForLoadState("networkidle");
  }
  await expect(page.locator(".map canvas").first())
    .toBeVisible()
    .catch(() => undefined);
  expect(violations).toEqual([]);
});

test("publishes the formats it reads at /compat.json", async ({ request }) => {
  const res = await request.get("/compat.json");
  expect(res.ok()).toBe(true);
  const body = (await res.json()) as { formats: number[]; current: number };
  expect(body.formats).toContain(body.current);
});
