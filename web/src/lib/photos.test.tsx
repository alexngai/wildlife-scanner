import { render, screen } from "@testing-library/react";
import { PhotoCredit } from "../components/SpeciesPhoto";
import { StaticClient } from "../products/client";
import type { PhotoTemplates, TaxonPhoto } from "../products/types";
import { creditText, usablePhoto } from "./photos";

const client = new StaticClient("https://static.example.org", async () => new Response(""));
const resolve = (p: string) => client.assetUrl("testland", p);
const INAT: PhotoTemplates = {
  image: "https://inaturalist-open-data.s3.amazonaws.com/photos/{id}/{size}.{ext}",
  page: "https://www.inaturalist.org/photos/{id}",
  sizes: { thumb: "square", medium: "small" },
  source: "iNaturalist",
};
const base: TaxonPhoto = {
  id: 12345678,
  ext: "jpg",
  license: "cc-by",
  attribution: "(c) A. Person, some rights reserved (CC BY)",
};

describe("species photos (format 4: id + templates)", () => {
  it("builds the thumbnail, larger image and page from the templates", () => {
    const p = usablePhoto(base, INAT, resolve)!;
    expect(p.thumb).toBe("https://inaturalist-open-data.s3.amazonaws.com/photos/12345678/square.jpg");
    expect(p.large).toBe("https://inaturalist-open-data.s3.amazonaws.com/photos/12345678/small.jpg");
    expect(p.sourceUrl).toBe("https://www.inaturalist.org/photos/12345678");
    expect(p.source).toBe("iNaturalist");
    expect(p.license).toBe("CC BY");
  });

  it("keeps the extension as published, including none at all", () => {
    expect(usablePhoto({ ...base, ext: "JPG" }, INAT, resolve)!.thumb).toMatch(/\/square\.JPG$/);
    expect(usablePhoto({ ...base, ext: "" }, INAT, resolve)!.thumb).toMatch(/\/12345678\/square\.$/);
  });

  it("shows only openly licensed photos with a credit", () => {
    expect(usablePhoto({ ...base, license: "cc-by-nc-sa" }, INAT, resolve)?.license).toBe("CC BY-NC-SA");
    for (const license of ["", "all-rights-reserved", "cc-by-nd", "cc-by-nc-nd"])
      expect(usablePhoto({ ...base, license }, INAT, resolve)).toBeNull();
    expect(usablePhoto({ ...base, license: null as unknown as string }, INAT, resolve)).toBeNull();
    expect(usablePhoto({ ...base, attribution: " " }, INAT, resolve)).toBeNull();
    expect(usablePhoto(null, INAT, resolve)).toBeNull();
    expect(usablePhoto(base, null, resolve)).toBeNull(); // no templates in the index
  });

  it("refuses ids, extensions and templates that could change the URL", () => {
    expect(usablePhoto({ ...base, id: "1/../../x" as unknown as number }, INAT, resolve)).toBeNull();
    expect(usablePhoto({ ...base, ext: "jpg?x=1" }, INAT, resolve)).toBeNull();
    expect(usablePhoto(base, { ...INAT, image: "javascript:alert({id})" }, resolve)).toBeNull();
    expect(usablePhoto(base, { ...INAT, image: "http://insecure.example/{id}.{ext}" }, resolve)).toBeNull();
    expect(usablePhoto(base, { ...INAT, page: "javascript:{id}" }, resolve)?.sourceUrl).toBeNull();
  });

  it("resolves bucket-relative templates against the region root", () => {
    const local = { ...INAT, image: "static/photos/{id}-{size}.{ext}" };
    expect(usablePhoto(base, local, resolve)!.thumb).toBe(
      "https://static.example.org/region=testland/static/photos/12345678-square.jpg",
    );
  });

  it("credits once even when the source's credit continues after the licence", () => {
    const p = usablePhoto(
      { ...base, license: "cc-by-nc", attribution: "(c) A. Photographer, some rights reserved (CC BY-NC), uploaded by A. Photographer" },
      INAT,
      resolve,
    )!;
    expect(creditText(p)).toBe("(c) A. Photographer, some rights reserved (CC BY-NC), uploaded by A. Photographer · iNaturalist");
    const { container } = render(<PhotoCredit photo={p} />);
    expect(container.textContent).toBe(
      "Photo (c) A. Photographer, some rights reserved, uploaded by A. Photographer (CC BY-NC) · iNaturalist",
    );
    expect(screen.getByRole("link", { name: "CC BY-NC" })).toBeInTheDocument();
  });
});
