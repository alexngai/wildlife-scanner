/**
 * The life list: species the user has seen, kept only in this browser (localStorage).
 * It is never sent anywhere.
 */
import { useCallback, useSyncExternalStore } from "react";

const KEY = "wildlife-scanner:life-list:v1";
const listeners = new Set<() => void>();
let snapshot: ReadonlySet<string> | null = null;

function read(): ReadonlySet<string> {
  try {
    const raw = localStorage.getItem(KEY);
    const ids = raw ? (JSON.parse(raw) as unknown) : [];
    return new Set(Array.isArray(ids) ? ids.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

export function getLifeList(): ReadonlySet<string> {
  if (snapshot === null) snapshot = read();
  return snapshot;
}

export function setLifeList(ids: Iterable<string>): void {
  const next = new Set(ids);
  snapshot = next;
  try {
    localStorage.setItem(KEY, JSON.stringify([...next].sort()));
  } catch {
    // Storage may be unavailable (private mode); keep the in-memory list.
  }
  listeners.forEach((l) => l());
}

export function toggleSeen(id: string): void {
  const next = new Set(getLifeList());
  if (next.has(id)) next.delete(id);
  else next.add(id);
  setLifeList(next);
}

/** For tests: drop the cached snapshot so the next read comes from storage. */
export function resetLifeListCache(): void {
  snapshot = null;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      snapshot = null;
      listener();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useLifeList(): { seen: ReadonlySet<string>; toggle: (id: string) => void } {
  const seen = useSyncExternalStore(subscribe, getLifeList, getLifeList);
  const toggle = useCallback((id: string) => toggleSeen(id), []);
  return { seen, toggle };
}
