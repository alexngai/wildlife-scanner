import { existsSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(__dirname, "fixtures");

export function fixtureApi(name: string): unknown {
  return JSON.parse(readFileSync(join(root, "api", `${name}.json`), "utf8"));
}

/**
 * A fetch that serves the synthetic bucket at /data and canned API answers at /api.
 * Records every URL requested so tests can assert what left the "browser".
 */
export function makeFixtureFetch(apiRoutes: Record<string, unknown | ((url: URL) => unknown)> = {}) {
  const requested: string[] = [];
  const fetcher = (async (input: RequestInfo | URL) => {
    const href = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    requested.push(href);
    const url = new URL(href, "http://localhost");
    if (url.pathname.startsWith("/data/")) {
      const file = join(root, "bucket", decodeURIComponent(url.pathname.slice("/data/".length)));
      if (!existsSync(file) || !statSync(file).isFile()) return new Response("not found", { status: 404 });
      return new Response(readFileSync(file, "utf8"), { status: 200 });
    }
    if (url.pathname.startsWith("/api/")) {
      const path = url.pathname.slice("/api".length);
      for (const [pattern, body] of Object.entries(apiRoutes)) {
        if (new RegExp(`^${pattern}$`).test(path)) {
          const value = typeof body === "function" ? (body as (u: URL) => unknown)(url) : body;
          if (value === 404) return new Response('{"detail":"Not available"}', { status: 404 });
          return new Response(JSON.stringify(value), { status: 200 });
        }
      }
      return new Response('{"detail":"Not available"}', { status: 404 });
    }
    return new Response("not found", { status: 404 });
  }) as typeof fetch;
  return { fetcher, requested };
}
