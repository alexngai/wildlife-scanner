/**
 * Which static-product formats this app reads, and how.
 *
 * Every file says its `format` (taxa.json, a plain list, takes its index's). Each readable format
 * has an adapter that turns a file of that format into the shape the app uses (the current
 * format's). That way a breaking change can be rolled out without breaking the live site:
 *
 *   1. ship an app that reads N and N+1 (add N+1 here, make it current, and convert N up to it);
 *   2. publish N+1 (the publisher can check `/compat.json`, which lists `SUPPORTED_FORMATS`);
 *   3. once nothing serves N any more, drop its adapter.
 *
 * An unknown format (e.g. a newer one than this build knows) raises FormatError, which asks the
 * reader to reload for the latest app. Adapters keep each file's `format` as published (taxa.json
 * is read with its index's format).
 */
// No imports: vite.config.ts reads this file to write /compat.json.

/** A file in a format this build doesn't read (e.g. newer data than the app knows). */
export class FormatError extends Error {
  constructor(found: unknown) {
    super(`unsupported data format ${String(found)}`);
    this.name = "FormatError";
  }
}

/** The format whose shape the app's types describe (products/types.ts). */
export const CURRENT_FORMAT = 4;

/** Which kind of file is being read; adapters may convert each differently. */
export type FileKind = "index" | "taxa" | "map" | "place" | "placeWeek";

/** Converts one file of a given format into the current format's shape. */
export type Adapter = (kind: FileKind, data: unknown) => unknown;

export type FormatRegistry = Readonly<Record<number, Adapter>>;

const same: Adapter = (_kind, data) => data;

/**
 * The formats this build reads. Format 4 is current, so it passes through unchanged. When format
 * 5 arrives: set CURRENT_FORMAT = 5, update the types, add `5: same`, and turn this entry into a
 * 4 → 5 converter.
 */
export const DEFAULT_FORMATS: FormatRegistry = { 4: same };

export function supportedFormats(registry: FormatRegistry = DEFAULT_FORMATS): number[] {
  return Object.keys(registry)
    .map(Number)
    .sort((a, b) => a - b);
}

export const SUPPORTED_FORMATS = supportedFormats();

/** What `/compat.json` says, for the publisher's check before it moves CURRENT. */
export function compatInfo(registry: FormatRegistry = DEFAULT_FORMATS): { formats: number[]; current: number } {
  return { formats: supportedFormats(registry), current: CURRENT_FORMAT };
}

/** The file in the current shape; FormatError when its format isn't one this build reads. */
export function adapt<T>(registry: FormatRegistry, kind: FileKind, format: unknown, data: unknown): T {
  const adapter = typeof format === "number" ? registry[format] : undefined;
  if (!adapter) throw new FormatError(format);
  return adapter(kind, data) as T;
}
