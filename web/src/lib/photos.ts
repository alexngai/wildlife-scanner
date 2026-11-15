/**
 * Species photos: only openly licensed ones are shown, always with their credit. Photos are
 * chosen when the data is published; taxa.json carries each one's id, extension, licence and
 * credit, and index.json the URL templates (static format 4). The app re-checks every part.
 */
import type { PhotoTemplates, TaxonPhoto } from "../products/types";

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

/** Only these go into a URL: a numeric id, a short alphanumeric extension (possibly empty), a size word. */
const ID = /^\d{1,15}$/;
const EXT = /^[A-Za-z0-9]{0,8}$/;
const SIZE = /^[A-Za-z0-9_-]{1,20}$/;

function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(id|size|ext)\}/g, (_, k: string) => values[k] ?? "");
}

/**
 * The photo as it can be shown, or null when its licence, id or templates aren't acceptable.
 * `resolve` turns a filled template into a URL (https as is, or a bucket-relative path).
 */
export function usablePhoto(
  photo: TaxonPhoto | null | undefined,
  templates: PhotoTemplates | null | undefined,
  resolve: (path: string) => string | null,
): ShownPhoto | null {
  if (!photo || !templates || typeof templates.image !== "string") return null;
  const lic = LICENSES[String(photo.license).toLowerCase()];
  if (!lic || typeof photo.attribution !== "string" || !photo.attribution.trim()) return null;
  const id = String(photo.id);
  const ext = typeof photo.ext === "string" ? photo.ext : "";
  const { thumb: thumbSize, medium: mediumSize } = templates.sizes ?? {};
  if (!ID.test(id) || !EXT.test(ext) || !SIZE.test(String(thumbSize)) || !SIZE.test(String(mediumSize))) return null;
  // `ext` is used exactly as published: some old uploads have none (their URL ends in "square.").
  const thumb = resolve(fill(templates.image, { id, size: String(thumbSize), ext }));
  if (!thumb) return null;
  const large = resolve(fill(templates.image, { id, size: String(mediumSize), ext })) ?? thumb;
  const page = templates.page ? fill(templates.page, { id, size: "", ext }) : null;
  return {
    thumb,
    large,
    attribution: photo.attribution.trim(),
    license: lic.label,
    licenseUrl: lic.url,
    sourceUrl: page && /^https:\/\//i.test(page) ? page : null,
    source: templates.source ?? null,
  };
}

/** One line of credit, e.g. "(c) Jane Doe, some rights reserved (CC BY) · iNaturalist". */
export function creditText(p: ShownPhoto): string {
  const lic = p.attribution.includes(p.license) ? "" : ` (${p.license})`;
  return `${p.attribution}${lic}${p.source ? ` · ${p.source}` : ""}`;
}
