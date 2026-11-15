import { migrateOldKeys } from "./storage";

describe("settings saved under the old project name", () => {
  beforeEach(() => localStorage.clear());

  it("move to the new keys once, keeping the life list", () => {
    localStorage.setItem("wildlife-radar:life-list:v1", '["a","b"]');
    localStorage.setItem("wildlife-radar:theme", "dark");
    localStorage.setItem("unrelated", "x");
    migrateOldKeys();
    expect(localStorage.getItem("wildlife-scanner:life-list:v1")).toBe('["a","b"]');
    expect(localStorage.getItem("wildlife-scanner:theme")).toBe("dark");
    expect(localStorage.getItem("wildlife-radar:life-list:v1")).toBeNull();
    expect(localStorage.getItem("unrelated")).toBe("x");
  });

  it("never overwrite a value already saved under the new name", () => {
    localStorage.setItem("wildlife-scanner:theme", "light");
    localStorage.setItem("wildlife-radar:theme", "dark");
    migrateOldKeys();
    expect(localStorage.getItem("wildlife-scanner:theme")).toBe("light");
    expect(localStorage.getItem("wildlife-radar:theme")).toBeNull();
  });

  it("do nothing when storage is unavailable", () => {
    const broken = {
      get length(): number {
        throw new Error("blocked");
      },
    } as unknown as Storage;
    expect(() => migrateOldKeys(broken)).not.toThrow();
  });
});
