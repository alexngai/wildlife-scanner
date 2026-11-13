import type { ReactNode } from "react";
import { FormatError, isNotAvailable } from "../lib/errors";
import { NOT_AVAILABLE_DETAIL, NOT_AVAILABLE_TEXT } from "../lib/policy";
import type { AsyncState } from "../lib/useAsync";

/** The single "not available" view: identical for unknown, withheld and missing data. */
export function NotAvailable({ what, detail = NOT_AVAILABLE_DETAIL }: { what?: string; detail?: string }) {
  return (
    <div className="notice notice-na" role="status">
      <p className="na-title">{what ? `${what}: ${NOT_AVAILABLE_TEXT.toLowerCase()}` : NOT_AVAILABLE_TEXT}</p>
      <p className="muted">{detail}</p>
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="loading muted" role="status" aria-live="polite">
      {label}
    </p>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg =
    error instanceof FormatError
      ? "This data was published in a newer format. Reload the page to get the latest version of the app."
      : "Something went wrong loading this. Check your connection and try again.";
  return (
    <div className="notice notice-error" role="alert">
      <p>{msg}</p>
    </div>
  );
}

/** Render an async state: loading, not available, error, or the content. */
export function Async<T>({
  state,
  children,
  what,
  loading,
  notAvailable,
}: {
  state: AsyncState<T> | null;
  children: (data: T) => ReactNode;
  what?: string;
  loading?: string;
  notAvailable?: ReactNode;
}) {
  if (!state) return null;
  if (state.status === "loading") return <Loading label={loading} />;
  if (state.status === "error") {
    if (isNotAvailable(state.error)) return <>{notAvailable ?? <NotAvailable what={what} />}</>;
    return <ErrorBox error={state.error} />;
  }
  return <>{children(state.data)}</>;
}
