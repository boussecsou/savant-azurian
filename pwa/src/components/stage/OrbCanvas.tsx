import { useEffect, useRef, type MutableRefObject } from "react";
import { BAR_COUNT, barNoise, barTarget, breathe, clamp, mirrorIndex, smoothLevel, sphereRadius, targetLevel } from "../../orb/orbMath";
import { PALETTES, clonePalette, easePalette, rgba, type OrbMode } from "../../orb/orbPalette";

interface Props {
  mode: OrbMode;
  /** Microphone level, 0..1. Written by the voice hook, read every frame: never React state. */
  micLevel: MutableRefObject<number>;
  /** Microphone frequency data while listening, when available. */
  spectrum?: MutableRefObject<Uint8Array | null>;
  isDark: boolean;
  reducedMotion: boolean;
}

// Five light blobs that drift inside the sphere.
const BLOBS = Array.from({ length: 5 }, (_, i) => ({ w: 0.45 + i * 0.19, ph: i * 1.9, r: 0.3 + (i % 3) * 0.13, s: 0.62 + (i % 2) * 0.2, k: 1 + i * 0.23 }));

/**
 * The orb: a sphere of drifting light with an audio halo, drawn on a canvas 190% of its box so the
 * glow ends inside the canvas. One animation loop, no React state per frame, stopped on unmount.
 */
export function OrbCanvas({ mode, micLevel, spectrum, isDark, reducedMotion }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  // Read by the loop each frame, so a change of state never restarts it.
  const live = useRef({ mode, isDark, reducedMotion });
  live.current = { mode, isDark, reducedMotion };

  useEffect(() => {
    const cv = canvas.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;

    let width = 0;
    const resize = () => {
      const box = cv.getBoundingClientRect();
      if (!box.width) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = box.width;
      cv.width = Math.round(box.width * dpr);
      cv.height = Math.round(box.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(cv);
    resize();

    const current = clonePalette(PALETTES.off);
    const amps = new Float32Array(BAR_COUNT);
    const rings: number[] = [];
    let level = 0;
    let t = 0;
    let lastRing = 0;
    let last = performance.now();
    let frameId = 0;

    const frame = (now: number) => {
      frameId = requestAnimationFrame(frame);
      if (!width) {
        resize();
        return;
      }
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const { mode: m, isDark: dark, reducedMotion: reduced } = live.current;

      easePalette(current, PALETTES[m] ?? PALETTES.off, dt);
      level = smoothLevel(level, targetLevel(m, t, micLevel.current), dt);
      t += dt * current.sp * (reduced ? 0.2 : 1);

      ctx.clearRect(0, 0, width, width);
      const cx = width / 2;
      const cy = width / 2;
      const R0 = sphereRadius(width, breathe(t, reduced), level);
      const c = current.c;

      // Light pooled on the floor under the orb: it sits on something instead of floating.
      let g: CanvasGradient;
      ctx.save();
      ctx.translate(cx, cy + R0 * 1.95);
      ctx.scale(1, 0.2);
      g = ctx.createRadialGradient(0, 0, 0, 0, 0, R0 * 1.7);
      g.addColorStop(0, rgba(c[0], (dark ? 0.34 : 0.22) + level * 0.3));
      g.addColorStop(1, rgba(c[0], 0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(0, 0, R0 * 1.7, 0, 7);
      ctx.fill();
      ctx.restore();

      // Outer glow.
      g = ctx.createRadialGradient(cx, cy, R0 * 0.6, cx, cy, R0 * 3.1);
      g.addColorStop(0, rgba(c[0], (dark ? 0.3 : 0.24) + level * 0.3));
      g.addColorStop(0.5, rgba(c[1], (dark ? 0.09 : 0.08) + level * 0.1));
      g.addColorStop(1, rgba(c[1], 0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(cx, cy, R0 * 3.1, 0, 7);
      ctx.fill();

      // Ripples while speaking.
      if (m === "speaking" && t - lastRing > 0.95) {
        rings.push(t);
        lastRing = t;
      }
      ctx.lineWidth = 1.4;
      for (let i = rings.length - 1; i >= 0; i--) {
        const age = (t - rings[i]) / 1.5;
        if (age > 1) {
          rings.splice(i, 1);
          continue;
        }
        ctx.strokeStyle = rgba(c[3], (1 - age) * 0.4);
        ctx.beginPath();
        ctx.arc(cx, cy, R0 * (1.12 + age * 0.85), 0, 7);
        ctx.stroke();
      }

      // Halo: audio bars, or orbiting arcs while thinking.
      const ring = R0 * 1.14;
      ctx.lineCap = "round";
      if (m === "thinking") {
        for (let k = 0; k < 3; k++) {
          const a0 = t * 1.5 + k * 2.094;
          ctx.strokeStyle = rgba(c[k % 3], 0.85);
          ctx.lineWidth = 3;
          ctx.beginPath();
          ctx.arc(cx, cy, ring + 4 + k * 3, a0, a0 + 0.9 + 0.35 * Math.sin(t * 2 + k));
          ctx.stroke();
        }
        ctx.strokeStyle = rgba(c[1], 0.18);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(cx, cy, ring + 4, 0, 7);
        ctx.stroke();
      } else {
        const fft = spectrum?.current ?? null;
        for (let i = 0; i < BAR_COUNT; i++) {
          const j = mirrorIndex(i);
          const fftValue = fft ? fft[Math.min(fft.length - 1, (j * 1.2) | 0)] : undefined;
          const target = barTarget({ mode: m, level, noise: barNoise(j, t), reduced, fftValue });
          amps[i] += (target - amps[i]) * (1 - Math.exp(-dt * 14));
          const a = (i / BAR_COUNT) * Math.PI * 2 - Math.PI / 2;
          const len = 3 + amps[i] * R0 * 0.78;
          ctx.strokeStyle = rgba(c[i % 2 ? 1 : 3], clamp(0.3 + amps[i] * 1.1, 0.12, 0.95));
          ctx.lineWidth = 2.2;
          ctx.beginPath();
          ctx.moveTo(cx + Math.cos(a) * ring, cy + Math.sin(a) * ring);
          ctx.lineTo(cx + Math.cos(a) * (ring + len), cy + Math.sin(a) * (ring + len));
          ctx.stroke();
        }
      }

      // The sphere itself.
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, R0, 0, 7);
      ctx.clip();
      g = ctx.createRadialGradient(cx - R0 * 0.3, cy - R0 * 0.38, R0 * 0.05, cx, cy, R0 * 1.05);
      g.addColorStop(0, rgba(current.base.map((v) => v * 2.2), 1));
      g.addColorStop(1, rgba(current.base.map((v) => v * 0.45), 1));
      ctx.fillStyle = g;
      ctx.fillRect(cx - R0, cy - R0, R0 * 2, R0 * 2);
      ctx.globalCompositeOperation = "lighter";
      BLOBS.forEach((b, i) => {
        const ang = t * b.w + b.ph;
        const bx = cx + Math.cos(ang) * R0 * b.r * (1 + level * 0.5);
        const by = cy + Math.sin(ang * b.k * 0.8 + b.ph) * R0 * b.r * (1 + level * 0.5);
        const rad = R0 * b.s * (0.95 + level * 0.5);
        const color = c[i % 4];
        const bg = ctx.createRadialGradient(bx, by, 0, bx, by, rad);
        bg.addColorStop(0, rgba(color, 0.78));
        bg.addColorStop(0.55, rgba(color, 0.26));
        bg.addColorStop(1, rgba(color, 0));
        ctx.fillStyle = bg;
        ctx.fillRect(cx - R0, cy - R0, R0 * 2, R0 * 2);
      });
      ctx.globalCompositeOperation = "source-over";
      // Fresnel rim, highlight and a shade at the bottom.
      g = ctx.createRadialGradient(cx, cy, R0 * 0.62, cx, cy, R0);
      g.addColorStop(0, "rgba(0,0,0,0)");
      g.addColorStop(0.75, rgba(c[3], 0.1));
      g.addColorStop(1, rgba(c[3], 0.5));
      ctx.fillStyle = g;
      ctx.fillRect(cx - R0, cy - R0, R0 * 2, R0 * 2);
      g = ctx.createRadialGradient(cx - R0 * 0.36, cy - R0 * 0.46, 0, cx - R0 * 0.36, cy - R0 * 0.46, R0 * 0.62);
      g.addColorStop(0, "rgba(255,255,255,0.62)");
      g.addColorStop(0.45, "rgba(255,255,255,0.12)");
      g.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g;
      ctx.fillRect(cx - R0, cy - R0, R0 * 2, R0 * 2);
      g = ctx.createLinearGradient(cx, cy, cx, cy + R0);
      g.addColorStop(0, "rgba(0,0,0,0)");
      g.addColorStop(1, "rgba(5,5,25,0.38)");
      ctx.fillStyle = g;
      ctx.fillRect(cx - R0, cy, R0 * 2, R0);
      ctx.restore();
      ctx.strokeStyle = rgba(c[3], 0.28 + level * 0.3);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(cx, cy, R0 - 0.5, 0, 7);
      ctx.stroke();
    };

    frameId = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(frameId);
      observer?.disconnect();
    };
  }, [micLevel, spectrum]);

  return <canvas ref={canvas} aria-hidden="true" />;
}
