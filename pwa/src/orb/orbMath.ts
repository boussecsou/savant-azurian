import type { OrbMode } from "./orbPalette";

/** Number of bars in the halo. */
export const BAR_COUNT = 96;

export const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/** A slow swell of the sphere (none when motion is reduced). */
export function breathe(t: number, reduced: boolean): number {
  return reduced ? 1 : 1 + 0.014 * Math.sin(t * 1.3);
}

/** Radius of the sphere from the canvas width: the canvas is 190% of the orb, the sphere 25.5% of it. */
export function sphereRadius(canvasWidth: number, swell: number, level: number): number {
  return canvasWidth * 0.1342 * swell * (1 + level * 0.07);
}

/** The halo is mirrored left to right: bar i and its mirror share one index. */
export function mirrorIndex(i: number, count: number = BAR_COUNT): number {
  return i < count / 2 ? i : count - 1 - i;
}

/** A moving value in [0, 1] for a bar: three sines that never quite line up. */
export function barNoise(j: number, t: number): number {
  return (Math.sin(j * 0.9 + t * 3.1) + Math.sin(j * 0.37 - t * 2.3) + Math.sin(j * 1.7 + t * 5.3)) / 6 + 0.5;
}

/** Where the level wants to be. Listening follows the real microphone; the rest are drawn, not measured. */
export function targetLevel(mode: OrbMode, t: number, micLevel: number): number {
  switch (mode) {
    case "listening":
      return clamp(micLevel, 0.04, 1);
    case "thinking":
      return 0.14 + 0.06 * Math.sin(3 * t);
    case "speaking":
      return 0.28 + 0.4 * Math.abs(Math.sin(8.2 * t) * Math.sin(2.7 * t + 1));
    case "starting":
      return 0.18;
    case "muted":
      return 0.03;
    default:
      return 0.02;
  }
}

/** Fast attack, slow release, independent of the frame rate. */
export function smoothLevel(level: number, target: number, dt: number): number {
  return level + (target - level) * (1 - Math.exp(-dt * (target > level ? 16 : 5)));
}

/** Where one halo bar wants to be. `spectrum` is the microphone's frequency data, when there is some. */
export function barTarget(opts: {
  mode: OrbMode;
  level: number;
  noise: number;
  reduced: boolean;
  fftValue?: number;
}): number {
  const { mode, level, noise, reduced, fftValue } = opts;
  let target: number;
  if (mode === "listening" || mode === "speaking") target = level * (reduced ? 0.5 : 0.2 + 0.8 * noise);
  else if (mode === "off" || mode === "muted") target = 0.025 + 0.02 * noise;
  else target = level * 0.5;
  if (fftValue !== undefined && mode === "listening") target = Math.max(target * 0.3, (fftValue / 255) * 1.1);
  return target;
}

/** Microphone level from frequency bytes (an AnalyserNode with a small fft): the mean, boosted and bounded. */
export function micLevelFrom(bytes: ArrayLike<number>): number {
  if (bytes.length === 0) return 0.04;
  let sum = 0;
  for (let i = 0; i < bytes.length; i++) sum += bytes[i];
  return clamp((sum / bytes.length / 255) * 2.4, 0.04, 1);
}
