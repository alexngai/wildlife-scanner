import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { fixtureApi } from "./fixtureFetch";
import { renderApp } from "./render";
import { resetLifeListCache } from "../src/lib/lifelist";

// MapLibre needs WebGL; unit tests check what the map is given instead.
vi.mock("../src/components/MapView", () => ({
  default: (props: { label: string; data: { features: unknown[] } }) => (
    <div data-testid="map" aria-label={props.label} data-cells={props.data.features.length} />
  ),
}));

beforeEach(() => resetLifeListCache());

describe("species page", () => {
  it("shows the map, calendar, meaning and licence for an openly mapped species", async () => {
    renderApp("/r/testland/species/testus-primus?week=20");
    expect(await screen.findByRole("heading", { level: 1, name: "Common Testbird" })).toBeInTheDocument();
    expect(screen.getByText(/What the number means/)).toBeInTheDocument();
    expect(screen.getByText(/Synthetic test label/)).toBeInTheDocument();
    expect(await screen.findByTestId("map")).toHaveAttribute("data-cells", "37");
    expect(screen.getByRole("img", { name: /Seasonal calendar/ })).toBeInTheDocument();
    expect(screen.getByText(/Non-commercial use only/)).toBeInTheDocument();
    expect(screen.getByText(/published after at least 24 hours/)).toBeInTheDocument();
    expect(document.title).toBe("Common Testbird · wildlife-radar");
  });

  it("shows awareness species without any numbers or calendar", async () => {
    const { container } = renderApp("/r/testland/species/rarus-tertius");
    expect(await screen.findByText(/Shown for awareness only/)).toBeInTheDocument();
    await screen.findByTestId("map");
    expect(container.textContent).not.toMatch(/\d+%/);
    expect(screen.queryByRole("img", { name: /Seasonal calendar/ })).toBeNull();
    expect(screen.queryByText(/Daily forecast/)).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();
  });

  it("says a withheld week is not available, and an awareness season has no numbers", async () => {
    renderApp("/r/testland/species/testus-secundus?week=2");
    expect(await screen.findByText(/Week 2: not available/)).toBeInTheDocument();
  });

  it("makes unknown species look exactly like withheld ones", async () => {
    const a = renderApp("/r/testland/species/never-heard-of-it");
    const na = await screen.findByText(/This species: not available/);
    const text = na.closest(".notice")?.textContent;
    a.unmount();
    renderApp("/r/testland/species/withheld-one");
    expect((await screen.findByText(/This species: not available/)).closest(".notice")?.textContent).toBe(text);
  });

  it("shows the daily forecast with its drivers for a chosen place", async () => {
    renderApp("/r/testland/species/testus-primus?place=test-cove", {
      api: { "/species/testus-primus/forecast": fixtureApi("forecast"), "/species/testus-primus/forecast/hourly": fixtureApi("hourly") },
    });
    expect(await screen.findByText("42%")).toBeInTheDocument();
    expect(screen.getByText("Adjusted for today's conditions")).toBeInTheDocument();
    expect(screen.getByText("Water temperature")).toBeInTheDocument();
    expect(screen.getByText(/raises the odds 1\.4×/)).toBeInTheDocument();
    expect(screen.getByText(/lowers the odds 0\.8×/)).toBeInTheDocument();
    expect(await screen.findByText(/Best hours/)).toBeInTheDocument();
  });

  it("explains when the API isn't configured", async () => {
    renderApp("/r/testland/species/testus-primus?place=test-cove", { config: { apiBase: "" } });
    expect(await screen.findByText(/Daily forecasts come from the live service/)).toBeInTheDocument();
  });

  it("says when no daily factors are modelled yet", async () => {
    const f = fixtureApi("forecast") as Record<string, unknown>;
    renderApp("/r/testland/species/testus-primus?place=test-cove", {
      api: { "/species/testus-primus/forecast": { ...f, level: 0, p_level0: 0.42, drivers: [] } },
    });
    expect(await screen.findByText(/No daily factors are modelled for this species yet/)).toBeInTheDocument();
  });
});

describe("place page", () => {
  it("lists species, awareness species without numbers, and keeps a local life list", async () => {
    const user = userEvent.setup();
    const { requested } = renderApp("/r/testland/places/test-cove?week=20");
    expect(await screen.findByRole("heading", { level: 1, name: "Test Cove" })).toBeInTheDocument();
    const aware = screen.getByRole("heading", { name: "Also in the wider area" }).closest("section")!;
    expect(within(aware).getByText("Shy Testcat")).toBeInTheDocument();
    expect(aware.textContent).not.toMatch(/\d+%/);
    expect(screen.getAllByText("not enough data").length).toBeGreaterThan(0);

    const newSection = screen.getAllByRole("heading", { name: "New for you" })[0]!.closest("section")!;
    expect(within(newSection).getByRole("link", { name: "Common Testbird" })).toBeInTheDocument();
    await user.click(within(newSection).getByRole("button", { name: "Seen Common Testbird", pressed: false }));
    expect(JSON.parse(localStorage.getItem("wildlife-radar:life-list:v1")!)).toEqual(["testus-primus"]);
    expect(within(newSection).queryByRole("link", { name: "Common Testbird" })).toBeNull();
    expect(requested.join()).not.toContain("testus-primus,"); // life list never sent
  });

  it("shows recent activity with its data delay this week", async () => {
    renderApp("/r/testland/places/test-cove", { api: { "/places/test-cove/recent": fixtureApi("recent") } });
    expect(await screen.findByText(/Sightings through/)).toHaveTextContent("May 19, 2026");
    expect(screen.getByText(/published with a delay/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Picking up now" })).toBeInTheDocument();
  });
});

describe("region and search", () => {
  it("searches species by name", async () => {
    const user = userEvent.setup();
    renderApp("/r/testland");
    await user.type(await screen.findByLabelText("Search species"), "testf");
    const results = document.querySelector(".result-list") as HTMLElement;
    expect(within(results).getAllByRole("link")).toHaveLength(1);
    expect(within(results).getByRole("link", { name: /Seasonal Testfish/ })).toHaveAttribute("href", "/r/testland/species/testus-secundus");
  });

  it("offers configured regions", async () => {
    renderApp("/");
    expect(await screen.findByRole("link", { name: /Testland/ })).toHaveAttribute("href", "/r/testland");
  });

  it("has the AGPL source link and non-commercial notice everywhere", async () => {
    renderApp("/about");
    expect(screen.getAllByRole("link", { name: /Source code|github\.com/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/non-commercial/i).length).toBeGreaterThan(0);
  });
});
