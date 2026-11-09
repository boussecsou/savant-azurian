import { describe, expect, it } from "vitest";
import { MAX_ENTRIES, formatDuration, pushActivity, summarize, type ActivityEntry } from "./activity";

const entry = (over: Partial<ActivityEntry> = {}): ActivityEntry => ({ id: "x", at: 0, kind: "chat", level: "ok", label: "t", ...over });

describe("pushActivity", () => {
  it("puts the newest entry first", () => {
    const list = pushActivity([entry({ id: "a" })], entry({ id: "b" }));
    expect(list.map((e) => e.id)).toEqual(["b", "a"]);
  });

  it("caps the journal", () => {
    let list: ActivityEntry[] = [];
    for (let i = 0; i < MAX_ENTRIES + 20; i++) list = pushActivity(list, entry({ id: String(i) }));
    expect(list).toHaveLength(MAX_ENTRIES);
    expect(list[0].id).toBe(String(MAX_ENTRIES + 19));
  });
});

describe("summarize", () => {
  it("is empty without a successful turn", () => {
    expect(summarize([])).toEqual({ turns: 0, firstTextMs: undefined });
    expect(summarize([entry({ level: "error", ms: 120000 })])).toEqual({ turns: 0, firstTextMs: undefined });
  });

  it("ignores tool calls, first-text delays and warm-ups in the turn statistics", () => {
    const list = [
      entry({ kind: "tool", ms: 900 }),
      entry({ kind: "first-text", ms: 1500 }),
      entry({ kind: "warmup", ms: 8000 }),
      entry({ ms: 5000 }),
    ];
    expect(summarize(list)).toEqual({ turns: 1, lastMs: 5000, averageMs: 5000, firstTextMs: 1500 });
  });

  it("averages successful turns and reports the latest first entry", () => {
    const list = [entry({ ms: 2000 }), entry({ level: "error", ms: 99999 }), entry({ ms: 4000 })];
    expect(summarize(list)).toEqual({ turns: 2, lastMs: 2000, averageMs: 3000, firstTextMs: undefined });
  });
});

describe("formatDuration", () => {
  it("formats milliseconds and seconds", () => {
    expect(formatDuration(850)).toBe("850 ms");
    expect(formatDuration(6240)).toBe("6.2 s");
    expect(formatDuration(42000)).toBe("42 s");
  });
});
