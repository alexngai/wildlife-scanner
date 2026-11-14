import { StaticClient } from "../products/client";
import type { TaxonPhoto } from "../products/types";
import { creditText, usablePhoto } from "./photos";

const client = new StaticClient("https://static.example.org", async () => new Response(""));
const resolve = (p: string) => client.assetUrl("testland", p);
const base: TaxonPhoto = {
  url: "static/photos/x.jpg",
  license: "cc-by",
  attribution: "(c) A. Person, some rights reserved (CC BY)",
};

describe("species photos", () => {
  it("shows only openly licensed photos with a credit", () => {
    expect(usablePhoto(base, resolve)?.license).toBe("CC BY");
    expect(usablePhoto({ ...base, license: "cc-by-nc-sa" }, resolve)?.license).toBe("CC BY-NC-SA");
    for (const license of ["", "all-rights-reserved", "cc-by-nd", "cc-by-nc-nd"])
      expect(usablePhoto({ ...base, license }, resolve)).toBeNull();
    expect(usablePhoto({ ...base, license: null as unknown as string }, resolve)).toBeNull();
    expect(usablePhoto({ ...base, attribution: " " }, resolve)).toBeNull();
    expect(usablePhoto(null, resolve)).toBeNull();
  });

  it("resolves bucket paths, keeps https URLs, and refuses anything else", () => {
    expect(usablePhoto(base, resolve)?.thumb).toBe("https://static.example.org/region=testland/static/photos/x.jpg");
    const abs = "https://inaturalist-open-data.s3.amazonaws.com/photos/1/square.jpg";
    expect(usablePhoto({ ...base, url: abs }, resolve)?.thumb).toBe(abs);
    for (const url of ["javascript:alert(1)", "http://insecure.example/x.jpg", "//evil.example/x.jpg", "../../x.jpg"])
      expect(usablePhoto({ ...base, url }, resolve)).toBeNull();
    expect(usablePhoto({ ...base, source_url: "javascript:x" }, resolve)?.sourceUrl).toBeNull();
  });

  it("uses the larger image when there is one, and credits once", () => {
    const p = usablePhoto({ ...base, url_medium: "static/photos/x-medium.jpg", source: "iNaturalist" }, resolve)!;
    expect(p.large).toMatch(/x-medium\.jpg$/);
    expect(creditText(p)).toBe("(c) A. Person, some rights reserved (CC BY) · iNaturalist");
  });
});

describe("photo credit text", () => {
  it("names the licence once even when the source's credit continues after it", async () => {
    const { render, screen } = await import("@testing-library/react");
    const { PhotoCredit } = await import("../components/SpeciesPhoto");
    const p = usablePhoto(
      { ...base, license: "cc-by-nc", attribution: "(c) Matt K, some rights reserved (CC BY-NC), uploaded by Matt K" },
      resolve,
    )!;
    const { container } = render(<PhotoCredit photo={p} />);
    expect(container.textContent).toBe("Photo (c) Matt K, some rights reserved, uploaded by Matt K (CC BY-NC)");
    expect(screen.getByRole("link", { name: "CC BY-NC" })).toBeInTheDocument();
  });
});
