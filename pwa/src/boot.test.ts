import { describe, expect, it } from "vitest";
import { ARRIVE_MS, LEAVE_MS, bootPhase, nextBootChange, splashEnd } from "./boot";

const at = (ms: number, settledAt: number | null) => bootPhase(1000 + ms, { start: 1000, settledAt: settledAt === null ? null : 1000 + settledAt });

describe("start-up screen", () => {
  it("shows nothing when the sync is quick", () => {
    expect(at(50, 80)).toBe("arriving");
    expect(splashEnd({ start: 0, settledAt: 120 })).toBeNull();
    expect(at(2000, 80)).toBe("done");
  });

  it("waits 150 ms before showing the logo", () => {
    expect(at(100, null)).toBe("waiting");
    expect(at(150, null)).toBe("splash");
  });

  it("keeps the logo at least 400 ms once shown, even if the sync ends right after", () => {
    // Settled at 200 ms: shown from 150, so it leaves at 550, not 200.
    expect(at(300, 200)).toBe("splash");
    expect(at(549, 200)).toBe("splash");
    expect(at(550, 200)).toBe("leaving");
    expect(at(550 + LEAVE_MS, 200)).toBe("arriving");
    expect(at(550 + LEAVE_MS + ARRIVE_MS, 200)).toBe("done");
  });

  it("leaves when the sync ends, after the minimum", () => {
    expect(at(1999, 2000)).toBe("splash");
    expect(at(2000, 2000)).toBe("leaving");
  });

  it("never blocks for more than 4 seconds", () => {
    expect(at(3999, null)).toBe("splash");
    expect(at(4000, null)).toBe("leaving");
    expect(at(4000 + LEAVE_MS + ARRIVE_MS, null)).toBe("done");
  });

  it("tells when to look again", () => {
    const times = { start: 0, settledAt: null };
    expect(nextBootChange(0, times)).toBe(150);
    expect(nextBootChange(150, times)).toBe(4000);
    expect(nextBootChange(4000 + LEAVE_MS + ARRIVE_MS, times)).toBeNull();
    expect(nextBootChange(0, { start: 0, settledAt: 100 })).toBe(150);
  });
});
