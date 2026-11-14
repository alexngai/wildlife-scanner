/**
 * Species photos: only openly licensed ones are shown, always with their credit. Photos are
 * chosen when the data is published (NEEDS.md §15); the app re-checks the licence and URL.
 */
import type { TaxonPhoto } from "../products/types";

/** Licences we can show here (a non-commercial site). No "all rights reserved", no ND. */
const LICENSES: Record<string, { label: string; url: string | null }> = {
  cc0: { label: "CC0", url: "https://creativecommons.org/publicdomain/zero/1.0/" },
  "cc-by": { label: "CC BY", url: "https://creativecommons.org/licenses/by/4.0/" },
  "cc-by-sa": { label: "CC BY-SA", url: "https://creativecommons.org/licenses/by-sa/4.0/" },
  "cc-by-nc": { label: "CC BY-NC", url: "https://creativecommons.org/licenses/by-nc/4.0/" },
  "cc-by-nc-sa": { label: "CC BY-NC-SA", url: "https://creativecommons.org/licenses/by-nc-sa/4.0/" },
};

export interface ShownPhoto {
  thumb: string;
  large: string;
  attribution: string;
  license: string;
  licenseUrl: string | null;
  sourceUrl: string | null;
  source: string | null;
}

/** The photo as it can be shown, or null when its licence or URL isn't acceptable. */
export function usablePhoto(
  photo: TaxonPhoto | null | undefined,
  resolve: (path: string) => string | null,
): ShownPhoto | null {
  if (!photo || typeof photo.url !== "string" || typeof photo.attribution !== "string") return null;
  const lic = LICENSES[String(photo.license).toLowerCase()];
  if (!lic || !photo.attribution.trim()) return null;
  const thumb = resolve(photo.url);
  if (!thumb) return null;
  const large = (photo.url_medium && resolve(photo.url_medium)) || thumb;
  const sourceUrl = photo.source_url && /^https:\/\//i.test(photo.source_url) ? photo.source_url : null;
  return {
    thumb,
    large,
    attribution: photo.attribution.trim(),
    license: lic.label,
    licenseUrl: lic.url,
    sourceUrl,
    source: photo.source ?? null,
  };
}

/** One line of credit, e.g. "(c) Jane Doe, some rights reserved (CC BY) · iNaturalist". */
export function creditText(p: ShownPhoto): string {
  const lic = p.attribution.includes(p.license) ? "" : ` (${p.license})`;
  return `${p.attribution}${lic}${p.source ? ` · ${p.source}` : ""}`;
}
