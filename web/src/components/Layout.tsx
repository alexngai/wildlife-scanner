import { useEffect, useRef } from "react";
import { Link, Outlet, useLocation, useParams } from "react-router";
import { useServices } from "../context";
import { lastRegion } from "../hooks";
import type { ThemeChoice } from "../lib/theme";
import { useFreshness } from "../lib/useFreshness";
import { useThemeContext } from "../themeContext";
import { ExploreIcon, InfoIcon, LogoIcon, MoonIcon, NearbyIcon, SunIcon, SystemIcon } from "./Icons";

const THEMES: { id: ThemeChoice; label: string; Icon: () => React.JSX.Element }[] = [
  { id: "system", label: "System theme", Icon: SystemIcon },
  { id: "light", label: "Light theme", Icon: SunIcon },
  { id: "dark", label: "Dark theme", Icon: MoonIcon },
];

function ThemeSwitch() {
  const { choice, setChoice } = useThemeContext();
  return (
    <div className="theme-switch" role="group" aria-label="Theme">
      {THEMES.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          aria-pressed={choice === id}
          aria-label={label}
          title={label}
          onClick={() => setChoice(id)}
        >
          <Icon />
        </button>
      ))}
    </div>
  );
}

/** The three destinations, shared by the header (desktop) and the tab bar (phones). */
function useNav() {
  const params = useParams();
  const { pathname } = useLocation();
  const region = params.region ?? lastRegion();
  const nearby = region ? `/r/${region}/nearby` : "/";
  return [
    {
      to: region ? `/r/${region}` : "/",
      label: "Explore",
      Icon: ExploreIcon,
      active: pathname === "/" || (/^\/r\//.test(pathname) && !pathname.endsWith("/nearby")),
    },
    { to: nearby, label: "Nearby", Icon: NearbyIcon, active: pathname.endsWith("/nearby") },
    { to: "/about", label: "About", Icon: InfoIcon, active: pathname.startsWith("/about") },
  ];
}

export function Layout() {
  const { region } = useParams();
  const { config } = useServices();
  const { pathname } = useLocation();
  const newer = useFreshness(region);
  const nav = useNav();
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
  const links = (cls: string) =>
    nav.map(({ to, label, Icon, active }) => (
      <Link
        key={label}
        to={to}
        className={`${cls}${active ? " active" : ""}`}
        aria-current={active ? "page" : undefined}
      >
        <Icon />
        <span>{label}</span>
      </Link>
    ));
  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="header-inner">
          <Link to="/" className="brand">
            <span className="brand-mark">
              <LogoIcon />
            </span>
            Wildlife Scanner
          </Link>
          <nav aria-label="Main" className="site-nav">
            {links("nav-link")}
          </nav>
          <ThemeSwitch />
        </div>
      </header>
      {newer && (
        <div className="update-banner" role="status">
          <span>New data has been published.</span>
          <button type="button" className="button small" onClick={() => window.location.reload()}>
            Show the latest
          </button>
        </div>
      )}
      <main id="main" tabIndex={-1} ref={mainRef}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="footer-inner">
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
        </div>
      </footer>
      <nav aria-label="Main (tabs)" className="tab-bar">
        {links("tab")}
      </nav>
    </div>
  );
}
