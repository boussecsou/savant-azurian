import { describe, expect, it } from "vitest";
import { applySlash, enterAction, matchSlash, slashQuery } from "./composerKeys";

const key = (over: Partial<{ shift: boolean; mod: boolean; composing: boolean }> = {}) => ({ shift: false, mod: false, composing: false, ...over });

describe("enterAction", () => {
  it("sends on Enter and adds a line on Shift+Enter in normal mode", () => {
    expect(enterAction(key(), false)).toBe("send");
    expect(enterAction(key({ shift: true }), false)).toBe("newline");
  });

  it("adds a line on Enter in technical mode", () => {
    expect(enterAction(key(), true)).toBe("newline");
    expect(enterAction(key({ shift: true }), true)).toBe("newline");
  });

  it("sends on Ctrl/⌘+Enter in both modes", () => {
    expect(enterAction(key({ mod: true }), false)).toBe("send");
    expect(enterAction(key({ mod: true }), true)).toBe("send");
  });

  it("does nothing while an input method is composing", () => {
    expect(enterAction(key({ composing: true }), false)).toBe("none");
    expect(enterAction(key({ composing: true, mod: true }), true)).toBe("none");
  });
});

describe("slash menu", () => {
  it("opens only when the content is exactly /word", () => {
    expect(slashQuery("/")).toBe("");
    expect(slashQuery("/co")).toBe("co");
    expect(slashQuery("hello /co")).toBeNull();
    expect(slashQuery("/co de")).toBeNull();
    expect(slashQuery("")).toBeNull();
  });

  it("filters commands by prefix", () => {
    expect(matchSlash("/").map((c) => c.name)).toEqual(["/id", "/code"]);
    expect(matchSlash("/c").map((c) => c.name)).toEqual(["/code"]);
    expect(matchSlash("/ID").map((c) => c.name)).toEqual(["/id"]);
    expect(matchSlash("/zzz")).toEqual([]);
    expect(matchSlash("plain")).toEqual([]);
  });

  it("puts the cursor inside a code block", () => {
    const [id, code] = matchSlash("/");
    expect(applySlash(id)).toEqual({ value: "Look up an ID: ", cursor: 15 });
    expect(applySlash(code)).toEqual({ value: "```\n\n```", cursor: 4 });
  });
});
