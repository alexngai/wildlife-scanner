import { lazy, Suspense, useState } from "react";
import { createBrowserRouter, Link, RouterProvider, type RouteObject } from "react-router";
import { Layout } from "./components/Layout";
import { Loading, NotAvailable } from "./components/Status";
import { ServicesProvider, type Services } from "./context";
import { AboutPage } from "./pages/AboutPage";
import { HomePage } from "./pages/HomePage";
import { NearbyPage } from "./pages/NearbyPage";
import { PlacePage } from "./pages/PlacePage";
import { RegionPage } from "./pages/RegionPage";
import { ThemeProvider } from "./themeContext";

// The species page carries h3-js and the map; load it only when needed.
const SpeciesPage = lazy(() => import("./pages/SpeciesPage").then((m) => ({ default: m.SpeciesPage })));

function NotFound() {
  return (
    <div className="page">
      <NotAvailable what="This page" detail="There's nothing at this address." />
      <p>
        <Link to="/">Go to the start page</Link>
      </p>
    </div>
  );
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "about", element: <AboutPage /> },
      { path: "r/:region", element: <RegionPage /> },
      {
        path: "r/:region/species/:taxonId",
        element: (
          <Suspense fallback={<Loading />}>
            <SpeciesPage />
          </Suspense>
        ),
      },
      { path: "r/:region/places/:placeId", element: <PlacePage /> },
      { path: "r/:region/nearby", element: <NearbyPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export function App({ services }: { services: Services }) {
  const [router] = useState(() => createBrowserRouter(routes));
  return (
    <ServicesProvider services={services}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </ServicesProvider>
  );
}
