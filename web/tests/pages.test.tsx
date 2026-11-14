import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { fixtureApi } from "./fixtureFetch";
import { renderApp } from "./render";
import { resetLifeListCache } from "../src/lib/lifelist";
import { weekOf } from "../src/lib/weeks";

// MapLibre needs WebGL; unit tests check what the map is given instead.
vi.mock("../src/components/MapView", () => ({
  default: (props: {
    label: string;
    data: { features: unknown[] };
    metric?: string;
    places?: unknown[];
    markers?: unknown[];
  }) => (
    <div
      data-testid="map"
      aria-label={props.label}
      data-cells={props.data.features.length}
      data-metric={props.metric}
      data-places={props.places?.length}
      data-markers={props.markers?.length ?? 0}
    />
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
      api: {
        "/species/testus-primus/forecast": fixtureApi("forecast"),
        "/species/testus-primus/forecast/hourly": fixtureApi("hourly"),
      },
    });
    expect(await screen.findByText("42%")).toBeInTheDocument();
    expect(screen.getByText("Adjusted for today's conditions")).toBeInTheDocument();
    expect(screen.getByText("Water temperature")).toBeInTheDocument();
    expect(screen.getByText(/raises the odds 1\.4×/)).toBeInTheDocument();
    expect(screen.getByText(/lowers the odds 0\.8×/)).toBeInTheDocument();
    expect(await screen.findByText(/Best hours/)).toBeInTheDocument();
  });

  it("switches the map to 'compared with wider area' and lists cells as a table", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/r/testland/species/testus-primus?week=20");
    const map = await screen.findByTestId("map");
    expect(map).toHaveAttribute("data-metric", "chance");
    expect(map).toHaveAttribute("data-places", "2");
    await user.click(screen.getByRole("button", { name: "Compared with wider area", pressed: false }));
    expect(screen.getByTestId("map")).toHaveAttribute("data-metric", "lift");
    expect(screen.getByRole("list", { name: /compared with the wider area/ })).toBeInTheDocument();
    expect(router.state.location.search).toContain("view=compare");

    await user.click(screen.getByText("Show the map as a table"));
    const table = screen.getByText("Show the map as a table").closest("details")!.querySelector("table")!;
    expect(within(table).getByRole("columnheader", { name: "Against wider area" })).toBeInTheDocument();
    const choose = within(table).getAllByRole("button", { name: /^Choose/ });
    expect(choose.length).toBe(15);
    await user.click(choose[0]!);
    expect(router.state.location.search).toMatch(/lat=.*lon=/);
    expect((await screen.findAllByText(/At the point you chose/)).length).toBe(2); // calendar and forecast
  });

  it("overlays today's conditions on the highest cells, on request", async () => {
    const user = userEvent.setup();
    const week = weekOf(new Date());
    const { requested } = renderApp(`/r/testland/species/testus-primus?week=${week}`, {
      api: { "/species/testus-primus/forecast": fixtureApi("forecast") },
    });
    await screen.findByTestId("map");
    expect(requested.some((u) => u.includes("/forecast"))).toBe(false); // nothing until asked
    await user.click(screen.getByRole("button", { name: "Today's conditions", pressed: false }));
    expect(await screen.findByText(/conditions raise the chance in/)).toHaveTextContent(
      /raise the chance in 12, lower it in 0/,
    );
    expect(screen.getByTestId("map")).toHaveAttribute("data-markers", "12");
    expect(screen.getByText("Water temperature")).toBeInTheDocument();
    expect(requested.filter((u) => u.includes("/forecast")).length).toBe(12);
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
  it("lists species one group at a time, awareness species without numbers, and keeps a local life list", async () => {
    const user = userEvent.setup();
    const { requested } = renderApp("/r/testland/places/test-cove?week=20");
    expect(await screen.findByRole("heading", { level: 1, name: "Test Cove" })).toBeInTheDocument();
    const aware = screen.getByRole("heading", { name: "Also in the wider area" }).closest("section")!;
    expect(within(aware).getByText("Shy Testcat")).toBeInTheDocument();
    expect(aware.textContent).not.toMatch(/\d+%/);

    // The busiest group is shown first; others are a choice away.
    const group = screen.getByLabelText("Group");
    expect(group).toHaveDisplayValue(/birds/);
    await user.selectOptions(group, "fishes:casual");
    expect(screen.getAllByText("not enough data").length).toBeGreaterThan(0);
    await user.selectOptions(group, "birds:casual");

    await user.click(screen.getByRole("button", { name: /New for you/ }));
    const list = document.querySelector(".item-list") as HTMLElement;
    expect(within(list).getByRole("link", { name: "Common Testbird" })).toBeInTheDocument();
    await user.click(within(list).getByRole("button", { name: "Seen Common Testbird", pressed: false }));
    expect(JSON.parse(localStorage.getItem("wildlife-radar:life-list:v1")!)).toEqual(["testus-primus"]);
    expect(screen.getByText(/You've seen everything on these lists/)).toBeInTheDocument();
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
    expect(within(results).getByRole("link", { name: /Seasonal Testfish/ })).toHaveAttribute(
      "href",
      "/r/testland/species/testus-secundus",
    );
  });

  it("shows a season ribbon on search results, but not for awareness species", async () => {
    const user = userEvent.setup();
    renderApp("/r/testland");
    await user.type(await screen.findByLabelText("Search species"), "test");
    const results = document.querySelector(".result-list") as HTMLElement;
    const bird = within(results).getByRole("link", { name: /Common Testbird/ });
    expect(await within(bird).findByRole("img", { name: /Season: Most recorded (April|May)/ })).toBeInTheDocument();
    const cat = within(results).getByRole("link", { name: /Shy Testcat/ });
    expect(within(cat).queryByRole("img")).toBeNull();
  });

  it("compares places for one group on request", async () => {
    const user = userEvent.setup();
    const { requested } = renderApp("/r/testland");
    await user.click(await screen.findByRole("button", { name: "Compare places" }));
    expect(requested.join()).toContain("places/test-park");
    expect(await screen.findByLabelText(/Compare for/)).toHaveDisplayValue(
      /(birds|fishes) · casual sightings \(2 places\)/,
    );
    const list = document.querySelector(".hotspot-list") as HTMLElement;
    expect(within(list).getAllByRole("link")).toHaveLength(2);
    expect(within(list).getAllByText(/species per outing/).length).toBeGreaterThan(0);
    expect(await screen.findByTestId("map")).toHaveAttribute("data-places", "2");
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
