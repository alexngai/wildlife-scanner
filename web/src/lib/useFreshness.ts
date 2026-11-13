import { useEffect, useState } from "react";
import { useServices } from "../context";

export const FRESHNESS_INTERVAL_MS = 10 * 60 * 1000;

/**
 * Watch a region's CURRENT pointer while the page is open. Returns the newer version once one
 * is published (checked every 10 minutes and whenever the tab becomes visible again).
 */
export function useFreshness(region: string | undefined, intervalMs = FRESHNESS_INTERVAL_MS): string | null {
  const { products } = useServices();
  const [newer, setNewer] = useState<{ region: string; version: string } | null>(null);
  useEffect(() => {
    if (!region) return;
    let live = true;
    const check = async () => {
      try {
        const [loaded, latest] = await Promise.all([products.current(region), products.latestVersion(region)]);
        if (live && latest && latest !== loaded) setNewer({ region, version: latest });
      } catch {
        // Offline or unavailable: try again next time.
      }
    };
    const timer = window.setInterval(check, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") void check();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      live = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [products, region, intervalMs]);
  return newer && newer.region === region ? newer.version : null;
}
