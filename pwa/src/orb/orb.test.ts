import { describe, expect, it } from "vitest";
import { BAR_COUNT, barNoise, barTarget, breathe, micLevelFrom, mirrorIndex, smoothLevel, sphereRadius, targetLevel } from "./orbMath";
import { PALETTES, clonePalette, easePalette, orbMode, rgba } from "./orbPalette";

describe("orbMode", () => {
  it("shows muted only while listening", () => {
    expect(orbMode("listening", true)).toBe("muted");
    expect(orbMode("listening", false)).toBe("listening");
    expect(orbMode("thinking", true)).toBe("thinking");
    expect(orbMode("off", true)).toBe("off");
  });
});

describe("palettes", () => {
  it("has the seven states with four lights each", () => {
    expect(Object.keys(PALETTES).sort()).toEqual(["error", "listening", "muted", "off", "speaking", "starting", "thinking"]);
    for (const palette of Object.values(PALETTES)) expect(palette.c).toHaveLength(4);
  });

  it("eases toward the target without overshooting, at any frame rate", () => {
    const current = clonePalette(PALETTES.off);
    easePalette(current, PALETTES.error, 0.016);
    expect(current.c[0][0]).toBeGreaterThan(PALETTES.off.c[0][0]);
    expect(current.c[0][0]).toBeLessThan(PALETTES.error.c[0][0]);
    for (let i = 0; i < 400; i++) easePalette(current, PALETTES.error, 0.05);
    expect(current.c[0][0]).toBeCloseTo(PALETTES.error.c[0][0], 1);
    expect(current.sp).toBeCloseTo(PALETTES.error.sp, 2);
  });

  it("does not modify the shared palette when cloned", () => {
    const copy = clonePalette(PALETTES.off);
    copy.c[0][0] = 0;
    expect(PALETTES.off.c[0][0]).toBe(108);
  });

  it("formats colours for the canvas", () => {
    expect(rgba([10.9, 20, 30], 0.5)).toBe("rgba(10,20,30,0.5)");
  });
});

describe("orbMath", () => {
  it("sizes the sphere from the canvas width", () => {
    expect(sphereRadius(1000, 1, 0)).toBeCloseTo(134.2);
    expect(sphereRadius(1000, 1, 1)).toBeCloseTo(134.2 * 1.07);
    expect(breathe(1, true)).toBe(1);
    expect(breathe(1, false)).not.toBe(1);
  });

  it("mirrors the halo bars", () => {
    expect(mirrorIndex(0)).toBe(0);
    expect(mirrorIndex(BAR_COUNT - 1)).toBe(0);
    expect(mirrorIndex(BAR_COUNT / 2)).toBe(BAR_COUNT / 2 - 1);
  });

  it("keeps the noise between 0 and 1", () => {
    for (let j = 0; j < BAR_COUNT; j++) for (const t of [0, 1.3, 7.7]) {
      const n = barNoise(j, t);
      expect(n).toBeGreaterThanOrEqual(0);
      expect(n).toBeLessThanOrEqual(1);
    }
  });

  it("gives each state its level source", () => {
    expect(targetLevel("listening", 0, 0.5)).toBe(0.5);
    expect(targetLevel("listening", 0, 0)).toBe(0.04);
    expect(targetLevel("listening", 0, 9)).toBe(1);
    expect(targetLevel("off", 1, 1)).toBe(0.02);
    expect(targetLevel("muted", 1, 1)).toBe(0.03);
    expect(targetLevel("starting", 1, 1)).toBe(0.18);
    const speaking = targetLevel("speaking", 2.3, 0);
    expect(speaking).toBeGreaterThanOrEqual(0.28);
    expect(speaking).toBeLessThanOrEqual(0.68);
  });

  it("attacks fast and releases slowly", () => {
    const up = smoothLevel(0, 1, 0.016) - 0;
    const down = 1 - smoothLevel(1, 0, 0.016);
    expect(up).toBeGreaterThan(down);
  });

  it("aims halo bars by state, and follows the spectrum while listening", () => {
    const base = { level: 0.5, noise: 0.5, reduced: false };
    expect(barTarget({ ...base, mode: "off" })).toBeCloseTo(0.035);
    expect(barTarget({ ...base, mode: "listening" })).toBeCloseTo(0.5 * 0.6);
    expect(barTarget({ ...base, mode: "listening", reduced: true })).toBeCloseTo(0.25);
    expect(barTarget({ ...base, mode: "thinking" })).toBeCloseTo(0.25);
    expect(barTarget({ ...base, mode: "listening", fftValue: 255 })).toBeCloseTo(1.1);
    expect(barTarget({ ...base, mode: "speaking", fftValue: 255 })).toBeCloseTo(0.5 * 0.6);
  });

  it("derives a bounded microphone level from frequency bytes", () => {
    expect(micLevelFrom([])).toBe(0.04);
    expect(micLevelFrom(new Uint8Array(16))).toBe(0.04);
    expect(micLevelFrom(new Uint8Array(16).fill(255))).toBe(1);
    expect(micLevelFrom(new Uint8Array(16).fill(50))).toBeCloseTo((50 / 255) * 2.4);
  });
});
