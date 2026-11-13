import { useEffect, useRef } from "react";
import { Link, NavLink, Outlet, useLocation, useParams } from "react-router";
import { useServices } from "../context";
import { useThemeContext } from "../themeContext";
import { useFreshness } from "../lib/useFreshness";
import type { ThemeChoice } from "../lib/theme";

const NEXT: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
const THEME_LABEL: Record<ThemeChoice, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };

export function Layout() {
  const { region } = useParams();
  const { choice, setChoice } = useThemeContext();
  const { config } = useServices();
  const { pathname } = useLocation();
  const newer = useFreshness(region);
  const mainRef = useRef<HTMLElement>(null);
  const firstRender = useRef(true);
  // After client-side navigation, move focus to the new page so screen readers start there.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus({ preventScroll: false });
    window.scrollTo({ top: 0 });
  }, [pathname]);
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
      {newer && (
        <div className="update-banner" role="status">
          <span>New data has been published.</span>
          <button type="button" className="button" onClick={() => window.location.reload()}>
            Show the latest
          </button>
        </div>
      )}
      <main id="main" tabIndex={-1} ref={mainRef}>
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
