/**
 * "Not available" covers unknown, withheld and missing data alike: the app must never let a
 * user tell a withheld species from one that does not exist.
 */
export class NotAvailableError extends Error {
  constructor() {
    super("not available");
    this.name = "NotAvailableError";
  }
}

/** The data was published in a format this build does not understand. */
export { FormatError } from "../products/formats";

/** A network or server problem (as opposed to "not available"). */
export class FetchError extends Error {
  constructor(
    public readonly status: number,
    url: string,
  ) {
    super(`request failed (${status}) for ${url}`);
    this.name = "FetchError";
  }
}

export function isNotAvailable(err: unknown): boolean {
  return err instanceof NotAvailableError;
}
