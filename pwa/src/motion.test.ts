import { describe, expect, it } from "vitest";
import { MOTION_KEY, loadMotion, resolveMotion, saveMotion } from "./motion";

describe("motion preference", () => {
  it("reduces when the owner or the system asks", () => {
    expect(resolveMotion("system", false)).toBe("full");
    expect(resolveMotion("system", true)).toBe("reduce");
    expect(resolveMotion("reduce", false)).toBe("reduce");
  });

  it("reads and writes storage without ever throwing", () => {
    const data = new Map<string, string>();
    const storage = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
    expect(loadMotion(storage)).toBe("system");
    saveMotion("reduce", storage);
    expect(data.get(MOTION_KEY)).toBe("reduce");
    expect(loadMotion(storage)).toBe("reduce");
    data.set(MOTION_KEY, "weird");
    expect(loadMotion(storage)).toBe("system");
    const hostile = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(loadMotion(hostile)).toBe("system");
    expect(() => saveMotion("reduce", hostile)).not.toThrow();
  });
});
