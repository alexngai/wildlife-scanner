import { useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading"; data?: undefined; error?: undefined }
  | { status: "ok"; data: T; error?: undefined }
  | { status: "error"; data?: undefined; error: unknown };

/**
 * Run `load` whenever `deps` change; results from an older request are ignored.
 * Pass `null` as the loader to stay idle (e.g. while waiting for a location).
 */
export function useAsync<T>(load: (() => Promise<T>) | null, deps: readonly unknown[]): AsyncState<T> | null {
  // A fresh token per change of deps identifies the request a result belongs to
  // (state derived from the previous render's deps, as the React docs recommend).
  const [prev, setPrev] = useState<{ deps: readonly unknown[]; token: object }>(() => ({ deps, token: {} }));
  let token = prev.token;
  if (!sameDeps(prev.deps, deps)) {
    token = {};
    setPrev({ deps, token });
  }
  const [result, setResult] = useState<{ token: object; state: AsyncState<T> } | null>(null);
  const idle = load === null;
  useEffect(() => {
    if (!load) return;
    let live = true;
    load().then(
      (data) => live && setResult({ token, state: { status: "ok", data } }),
      (error: unknown) => live && setResult({ token, state: { status: "error", error } }),
    );
    return () => {
      live = false;
    };
    // `load` is a fresh closure every render; the deps decide when to rerun.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, idle]);
  if (idle) return null;
  if (!result || result.token !== token) return { status: "loading" };
  return result.state;
}

function sameDeps(a: readonly unknown[], b: readonly unknown[]): boolean {
  return a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
}
