import { createContext, useContext, type ReactNode } from "react";
import { useTheme, type ThemeChoice } from "./lib/theme";

interface ThemeCtx {
  choice: ThemeChoice;
  effective: "light" | "dark";
  setChoice: (c: ThemeChoice) => void;
}

const Ctx = createContext<ThemeCtx>({ choice: "system", effective: "light", setChoice: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useTheme();
  return <Ctx.Provider value={theme}>{children}</Ctx.Provider>;
}

export function useThemeContext(): ThemeCtx {
  return useContext(Ctx);
}
