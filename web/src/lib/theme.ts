import { useEffect, useState, useSyncExternalStore } from "react";

export type ThemeChoice = "system" | "light" | "dark";
const KEY = "wildlife-scanner:theme";

export function storedTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  try {
    if (choice === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch {
    // ignore
  }
}

function systemDark(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

function subscribeSystem(cb: () => void): () => void {
  const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
  mq?.addEventListener?.("change", cb);
  return () => mq?.removeEventListener?.("change", cb);
}

/** The user's choice plus the theme actually in effect. */
export function useTheme(): { choice: ThemeChoice; effective: "light" | "dark"; setChoice: (c: ThemeChoice) => void } {
  const [choice, setChoice] = useState<ThemeChoice>(storedTheme);
  const dark = useSyncExternalStore(subscribeSystem, systemDark, () => false);
  useEffect(() => applyTheme(choice), [choice]);
  const effective = choice === "system" ? (dark ? "dark" : "light") : choice;
  return { choice, effective, setChoice };
}
