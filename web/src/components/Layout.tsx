import { Link, NavLink, Outlet, useParams } from "react-router";
import { useServices } from "../context";
import { useThemeContext } from "../themeContext";
import type { ThemeChoice } from "../lib/theme";

const NEXT: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
const THEME_LABEL: Record<ThemeChoice, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };

export function Layout() {
  const { region } = useParams();
  const { choice, setChoice } = useThemeContext();
  const { config } = useServices();
  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <Link to={region ? `/r/${region}` : "/"} className="brand">
          <span aria-hidden="true" className="brand-mark">
            ◎
          </span>{" "}
          wildlife-radar
        </Link>
        <nav aria-label="Main" className="site-nav">
          {region && <NavLink to={`/r/${region}/nearby`}>Nearby</NavLink>}
          <NavLink to="/" end>
            Regions
          </NavLink>
          <NavLink to="/about">About</NavLink>
          <button
            type="button"
            className="theme-toggle"
            onClick={() => setChoice(NEXT[choice])}
            aria-label={`${THEME_LABEL[choice]}. Switch to ${NEXT[choice]}.`}
          >
            {choice === "dark" ? "☾" : choice === "light" ? "☀" : "◐"}
          </button>
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <p>
          Free and non-commercial: an educational project. Forecasts are estimates from historical records, not
          guarantees. Sensitive species are generalized or hidden.
        </p>
        <p>
          <a href={config.sourceUrl} rel="noreferrer" target="_blank">
            Source code
          </a>{" "}
          (GNU AGPL-3.0) · <Link to="/about#data">Data licences and attribution</Link> · Much of the data is CC BY-NC:
          non-commercial use only.
        </p>
      </footer>
    </div>
  );
}
