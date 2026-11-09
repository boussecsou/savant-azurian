import { describe, expect, it } from "vitest";
import { applyTheme, isTheme, loadTheme, resolveTheme, saveTheme, THEME_KEY } from "./theme";

function memoryStorage(initial: Record<string, string> = {}) {
  const values = { ...initial };
  return {
    values,
    getItem: (key: string) => (key in values ? values[key] : null),
    setItem: (key: string, value: string) => {
      values[key] = value;
    },
  };
}

function failingStorage() {
  return {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
  };
}

function fakeDocument() {
  const attributes = new Map<string, string>();
  const meta = { content: "", setAttribute: (_name: string, value: string) => (meta.content = value) };
  const doc = {
    documentElement: {
      setAttribute: (name: string, value: string) => attributes.set(name, value),
      removeAttribute: (name: string) => attributes.delete(name),
    },
    querySelector: (selector: string) => (selector === 'meta[name="theme-color"]' ? meta : null),
  };
  return { doc: doc as unknown as Document, attributes, meta };
}

describe("theme", () => {
  it("reads a stored choice and falls back to system", () => {
    expect(loadTheme(memoryStorage({ [THEME_KEY]: "dark" }))).toBe("dark");
    expect(loadTheme(memoryStorage({ [THEME_KEY]: "light" }))).toBe("light");
    expect(loadTheme(memoryStorage())).toBe("system");
    expect(loadTheme(memoryStorage({ [THEME_KEY]: "sepia" }))).toBe("system");
  });

  it("survives storage that is missing, blocked or full", () => {
    expect(loadTheme(undefined)).toBe("system");
    expect(loadTheme(failingStorage())).toBe("system");
    expect(() => saveTheme("dark", failingStorage())).not.toThrow();
    expect(() => saveTheme("dark", undefined)).not.toThrow();
  });

  it("writes the choice back", () => {
    const storage = memoryStorage();
    saveTheme("light", storage);
    expect(storage.values[THEME_KEY]).toBe("light");
  });

  it("validates the values it accepts", () => {
    expect(isTheme("system")).toBe(true);
    expect(isTheme("dark")).toBe(true);
    expect(isTheme("auto")).toBe(false);
    expect(isTheme(null)).toBe(false);
  });

  it("resolves the system preference", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("sets data-theme and the theme-color meta, and clears it for system", () => {
    const light = fakeDocument();
    applyTheme("dark", light.doc, false);
    expect(light.attributes.get("data-theme")).toBe("dark");
    expect(light.meta.content).toBe("#08080b");

    applyTheme("light", light.doc, true);
    expect(light.attributes.get("data-theme")).toBe("light");
    expect(light.meta.content).toBe("#f6f6f9");

    applyTheme("system", light.doc, false);
    expect(light.attributes.has("data-theme")).toBe(false);
    expect(light.meta.content).toBe("#f6f6f9");
  });
});
