/**
 * This browser's saved settings (life list, theme, map layers, last region) live under
 * "wildlife-scanner:" keys. Values saved under the project's old name, "wildlife-radar:", are
 * moved over once, so nobody loses their life list. Every access is guarded: storage can be
 * unavailable (private mode, blocked site data).
 */
export const STORAGE_PREFIX = "wildlife-scanner:";
const OLD_PREFIX = "wildlife-radar:";

export function migrateOldKeys(storage: Storage | undefined = globalThis.localStorage): void {
  try {
    if (!storage) return;
    const old: string[] = [];
    for (let i = 0; i < storage.length; i++) {
      const k = storage.key(i);
      if (k?.startsWith(OLD_PREFIX)) old.push(k);
    }
    for (const k of old) {
      const next = STORAGE_PREFIX + k.slice(OLD_PREFIX.length);
      const value = storage.getItem(k);
      if (value !== null && storage.getItem(next) === null) storage.setItem(next, value);
      storage.removeItem(k);
    }
  } catch {
    // Storage unavailable: nothing to move.
  }
}
