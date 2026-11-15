/// <reference types="vitest/config" />
import { createReadStream, existsSync, statSync } from "node:fs";
import { resolve, normalize, sep } from "node:path";
import type { Connect, Plugin } from "vite";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { compatInfo } from "./src/products/formats.ts";

/**
 * `/compat.json`: the static-product formats this build reads ({"formats": [...], "current": N}).
 * The publisher can fetch it from the live site and refuse to publish a format it doesn't list.
 */
function compatFile(): Plugin {
  const body = JSON.stringify(compatInfo()) + "\n";
  const serve: Connect.NextHandleFunction = (req, res, next) => {
    if ((req.url ?? "").split("?")[0] !== "/compat.json") return next();
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Cache-Control", "no-cache");
    res.end(body);
  };
  return {
    name: "wildlife-scanner-compat",
    configureServer: (server) => void server.middlewares.use(serve),
    configurePreviewServer: (server) => void server.middlewares.use(serve),
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "compat.json", source: body });
    },
  };
}

/**
 * Serve a local "folder bucket" (see docs/deploy.md) at /data, the way the CDN will serve it.
 * WS_BUCKET_DIR picks the folder: the repo's data/bucket by default, or the synthetic test
 * fixtures (tests/fixtures/bucket) for e2e runs.
 */
function folderBucket(): Plugin {
  const root = resolve(process.env.WS_BUCKET_DIR ?? resolve(import.meta.dirname, "../data/bucket"));
  const handler: Connect.NextHandleFunction = (req, res, next) => {
    const url = decodeURIComponent((req.url ?? "/").split("?")[0] ?? "/");
    const file = normalize(resolve(root, "." + url));
    if (!file.startsWith(root + sep) || !existsSync(file) || !statSync(file).isFile()) {
      res.statusCode = 404;
      res.end("not found");
      return;
    }
    const type: Record<string, string> = {
      ".json": "application/json",
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".png": "image/png",
      ".webp": "image/webp",
      ".svg": "image/svg+xml",
    };
    const ext = /\.[a-z0-9]+$/i.exec(file)?.[0].toLowerCase() ?? "";
    res.setHeader("Content-Type", type[ext] ?? "text/plain");
    res.setHeader("Cache-Control", file.endsWith("CURRENT") ? "no-cache" : "max-age=60");
    createReadStream(file).pipe(res);
    void next;
  };
  return {
    name: "wildlife-scanner-folder-bucket",
    configureServer(server) {
      server.middlewares.use("/data", handler);
    },
    configurePreviewServer(server) {
      server.middlewares.use("/data", handler);
    },
  };
}

const apiTarget = process.env.WS_API_URL ?? "http://127.0.0.1:8000";
const proxy = {
  "/api": { target: apiTarget, changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api/, "") },
};

export default defineConfig({
  plugins: [react(), folderBucket(), compatFile()],
  server: { proxy },
  preview: { proxy },
  build: { sourcemap: true, chunkSizeWarningLimit: 1200 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
    css: false,
  },
});
