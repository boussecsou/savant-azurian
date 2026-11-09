import { describe, expect, it } from "vitest";
import { VIEW_MODE_KEY, loadViewMode, saveViewMode } from "./viewMode";

const memory = (initial: Record<string, string> = {}) => {
  const data = { ...initial };
  return { data, getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v) };
};

describe("view mode", () => {
  it("starts with the voice stage", () => {
    expect(loadViewMode(memory())).toBe("voice");
  });

  it("remembers the chat-only view", () => {
    const storage = memory();
    saveViewMode("chat", storage);
    expect(storage.data[VIEW_MODE_KEY]).toBe("chat");
    expect(loadViewMode(storage)).toBe("chat");
  });

  it("ignores anything that is not a view", () => {
    expect(loadViewMode(memory({ [VIEW_MODE_KEY]: "wide" }))).toBe("voice");
  });

  it("works when storage is blocked", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(loadViewMode(blocked)).toBe("voice");
    expect(() => saveViewMode("chat", blocked)).not.toThrow();
  });
});
