import { describe, expect, it } from "vitest";
import { dayGroup, groupSessions, relTime } from "./grouping";

const HOUR = 3_600_000;
// Local noon, so "today" and "yesterday" do not depend on the hour the tests run.
const NOW = new Date(2026, 10, 5, 12, 0, 0).getTime();

describe("relTime", () => {
  it("shows now, minutes, hours, then days", () => {
    expect(relTime(NOW - 30_000, NOW)).toBe("now");
    expect(relTime(NOW - 5 * 60_000, NOW)).toBe("5 min");
    expect(relTime(NOW - 3 * HOUR, NOW)).toBe("3 h");
    expect(relTime(NOW - 50 * HOUR, NOW)).toBe("2 d");
  });
});

describe("dayGroup", () => {
  it("cuts at local midnight", () => {
    expect(dayGroup(NOW - HOUR, NOW)).toBe("Today");
    expect(dayGroup(new Date(2026, 10, 5, 0, 0, 0).getTime(), NOW)).toBe("Today");
    expect(dayGroup(new Date(2026, 10, 4, 23, 0, 0).getTime(), NOW)).toBe("Yesterday");
    expect(dayGroup(new Date(2026, 10, 3, 9, 0, 0).getTime(), NOW)).toBe("Earlier");
  });
});

describe("groupSessions", () => {
  const session = (id: string, updatedAt: number, pinned = false) => ({ id, updatedAt, pinned });

  it("puts pinned first, then the day groups newest first, and skips empty groups", () => {
    const items = groupSessions(
      [session("old", NOW - 5 * 24 * HOUR), session("a", NOW - 2 * HOUR), session("b", NOW - HOUR), session("pin", NOW - 9 * 24 * HOUR, true)],
      NOW,
    );
    expect(items.map((i) => (i.kind === "heading" ? `# ${i.label}` : i.session.id))).toEqual(["# Pinned", "pin", "# Today", "b", "a", "# Earlier", "old"]);
  });

  it("is empty for no sessions", () => {
    expect(groupSessions([], NOW)).toEqual([]);
  });
});
