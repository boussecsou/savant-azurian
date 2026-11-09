import type { VoiceState } from "../voice";

/** What the orb is doing. "muted" is the microphone switched off while voice is still on. */
export type OrbMode = "off" | "starting" | "listening" | "thinking" | "speaking" | "muted" | "error";

export type RGB = [number, number, number];

export interface Palette {
  /** Four lights that drift inside the sphere and tint its halo. */
  c: [RGB, RGB, RGB, RGB];
  /** The sphere's body colour. */
  base: RGB;
  /** Speed of the drift. */
  sp: number;
}

export const PALETTES: Record<OrbMode, Palette> = {
  off: { c: [[108, 128, 242], [148, 121, 234], [86, 160, 236], [196, 170, 250]], base: [18, 18, 52], sp: 0.5 },
  starting: { c: [[130, 150, 255], [170, 140, 250], [110, 190, 250], [220, 200, 255]], base: [22, 22, 62], sp: 1.1 },
  listening: { c: [[60, 150, 255], [70, 215, 240], [120, 110, 255], [150, 245, 255]], base: [10, 24, 66], sp: 0.9 },
  thinking: { c: [[150, 100, 240], [214, 120, 230], [100, 110, 240], [244, 170, 240]], base: [28, 16, 66], sp: 1.7 },
  speaking: { c: [[255, 115, 168], [255, 172, 118], [170, 108, 250], [255, 214, 170]], base: [44, 16, 52], sp: 1.1 },
  muted: { c: [[120, 130, 160], [140, 140, 170], [100, 120, 150], [170, 175, 200]], base: [20, 22, 38], sp: 0.35 },
  error: { c: [[232, 98, 98], [206, 78, 122], [150, 66, 108], [255, 150, 140]], base: [46, 14, 22], sp: 0.4 },
};

export function clonePalette(palette: Palette): Palette {
  return { c: palette.c.map((c) => [...c]) as Palette["c"], base: [...palette.base], sp: palette.sp };
}

/** The mode the orb shows for a voice state; a live microphone that is muted reads as "muted". */
export function orbMode(state: VoiceState, muted: boolean): OrbMode {
  if (state === "listening" && muted) return "muted";
  return state;
}

/** Move `current` toward `target` for a frame of `dt` seconds, whatever the frame rate. Mutates `current`. */
export function easePalette(current: Palette, target: Palette, dt: number, rate = 5): void {
  const k = 1 - Math.exp(-dt * rate);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 3; j++) current.c[i][j] += (target.c[i][j] - current.c[i][j]) * k;
  for (let j = 0; j < 3; j++) current.base[j] += (target.base[j] - current.base[j]) * k;
  current.sp += (target.sp - current.sp) * k;
}

export function rgba(color: readonly number[], alpha: number): string {
  return `rgba(${color[0] | 0},${color[1] | 0},${color[2] | 0},${alpha})`;
}
