import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { routes } from "../src/App";
import { DEFAULT_CONFIG, type AppConfig } from "../src/config";
import { makeServices, ServicesProvider } from "../src/context";
import { ThemeProvider } from "../src/themeContext";
import { makeFixtureFetch } from "./fixtureFetch";

export function renderApp(
  path: string,
  { api = {}, config = {} }: { api?: Parameters<typeof makeFixtureFetch>[0]; config?: Partial<AppConfig> } = {},
) {
  const { fetcher, requested } = makeFixtureFetch(api);
  const services = makeServices(
    { ...DEFAULT_CONFIG, staticBase: "/data", apiBase: "/api", regions: ["testland"], ...config },
    fetcher,
  );
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const utils = render(
    <ServicesProvider services={services}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </ServicesProvider>,
  );
  return { ...utils, requested, router };
}
