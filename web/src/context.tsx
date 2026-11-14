import { createContext, useContext, type ReactNode } from "react";
import { ApiClient } from "./api/client";
import type { AppConfig } from "./config";
import { StaticClient } from "./products/client";

export interface Services {
  config: AppConfig;
  products: StaticClient;
  api: ApiClient;
}

const Ctx = createContext<Services | null>(null);

export function makeServices(config: AppConfig, fetcher?: typeof fetch): Services {
  return {
    config,
    products: new StaticClient(config.staticBase, fetcher),
    api: new ApiClient(config.apiBase, fetcher),
  };
}

export function ServicesProvider({ services, children }: { services: Services; children: ReactNode }) {
  return <Ctx.Provider value={services}>{children}</Ctx.Provider>;
}

export function useServices(): Services {
  const s = useContext(Ctx);
  if (!s) throw new Error("ServicesProvider missing");
  return s;
}
