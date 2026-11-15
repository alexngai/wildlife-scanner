// Copies deploy/config.production.json into dist/config.json for the production site
// (wildlifescanner.com). Run after `vite build`; Cloudflare Pages runs `npm run build:production`.
// The dev and test config in public/config.json is what `npm run build` ships otherwise.
import { copyFileSync, existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const from = join(root, "deploy", "config.production.json");
const to = join(root, "dist", "config.json");
if (!existsSync(join(root, "dist"))) throw new Error("dist/ is missing: run the build first");
const config = JSON.parse(readFileSync(from, "utf8"));
for (const key of ["staticBase", "apiBase", "sourceUrl"]) {
  if (typeof config[key] !== "string" || !config[key].startsWith("https://")) {
    throw new Error(`config.production.json: ${key} must be an https URL`);
  }
}
copyFileSync(from, to);
console.log(`production config → ${to}`);
