import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";
import { DEFAULT_CONFIG } from "../config";
import { makeServices, ServicesProvider } from "../context";
import { useFreshness } from "./useFreshness";

describe("useFreshness", () => {
  it("reports a newer CURRENT once published", async () => {
    vi.useFakeTimers();
    let version = "v1";
    const fetcher = (async () => new Response(version)) as unknown as typeof fetch;
    const services = makeServices({ ...DEFAULT_CONFIG, staticBase: "/data" }, fetcher);
    await services.products.current("r"); // the version the page loaded
    const wrapper = ({ children }: { children: ReactNode }) => <ServicesProvider services={services}>{children}</ServicesProvider>;
    const { result } = renderHook(() => useFreshness("r", 1000), { wrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current).toBeNull();
    version = "v2";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current).toBe("v2");
    vi.useRealTimers();
  });
});
