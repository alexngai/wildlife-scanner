import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { loadConfig } from "./config";
import { makeServices } from "./context";
import { migrateOldKeys } from "./lib/storage";
import { applyTheme, storedTheme } from "./lib/theme";
import "./styles/app.css";

// Settings saved under the old project name move to the new keys before anything reads them.
migrateOldKeys();
applyTheme(storedTheme());

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");

void loadConfig().then((config) => {
  createRoot(root).render(
    <StrictMode>
      <App services={makeServices(config)} />
    </StrictMode>,
  );
});
