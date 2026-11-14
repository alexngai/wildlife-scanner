import { makeFixtureFetch } from "../../tests/fixtureFetch";
import { NotAvailableError } from "../lib/errors";
import { ApiClient } from "./client";

describe("ApiClient", () => {
  it("rounds locations and never sends a life list", async () => {
    const { fetcher, requested } = makeFixtureFetch({ "/nearby": { week: 1, groups: [] }, "/nearby/recent": {} });
    const api = new ApiClient("/api", fetcher);
    await api.nearbyLists(36.6123456, -121.9876543);
    await api.nearbyRecent(36.6123456, -121.9876543);
    expect(requested).toEqual(["/api/nearby?lat=36.612&lon=-121.988", "/api/nearby/recent?lat=36.612&lon=-121.988"]);
    expect(requested.join()).not.toContain("life_list");
  });

  it("maps 404 to not available, and is disabled without a base URL", async () => {
    const { fetcher } = makeFixtureFetch();
    await expect(new ApiClient("/api", fetcher).forecast("x", { placeId: "p" })).rejects.toBeInstanceOf(
      NotAvailableError,
    );
    const off = new ApiClient("", fetcher);
    expect(off.enabled).toBe(false);
    await expect(off.regions()).rejects.toBeInstanceOf(NotAvailableError);
  });
});
