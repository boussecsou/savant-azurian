import { describe, expect, it } from "vitest";
import { WARM_TTL_MS, isDue } from "./useWarmup";

describe("isDue", () => {
  it("wakes the agent when it never was, or when the last wake-up is old", () => {
    expect(isDue(0, 1_000_000)).toBe(true);
    expect(isDue(1_000_000 - WARM_TTL_MS, 1_000_000)).toBe(true);
  });

  it("leaves a recently woken agent alone", () => {
    expect(isDue(1_000_000 - WARM_TTL_MS + 1, 1_000_000)).toBe(false);
    expect(isDue(1_000_000, 1_000_000)).toBe(false);
  });
});

describe("takeSpare", () => {
  it("hands out a warm conversation only while it is likely still warm", async () => {
    const { takeSpare, WARM_TTL_MS } = await import("./useWarmup");
    expect(takeSpare(null, 1000)).toBeUndefined();
    expect(takeSpare({ id: "caresp_1", at: 1000 }, 1000 + WARM_TTL_MS - 1)).toBe("caresp_1");
    expect(takeSpare({ id: "caresp_1", at: 1000 }, 1000 + WARM_TTL_MS)).toBeUndefined();
  });
});
