/**
 * The start-up screen: Savant shows its logo while the workspace is read back from the server.
 * A pure timeline, so the thresholds are tested without a browser.
 *
 * - Nothing is shown for the first 150 ms: a fast start never flashes a splash.
 * - Once shown, it stays at least 400 ms (it would otherwise blink), and at most 4 s: after that the
 *   local copy is used and the sync goes on in the background (the owner is never blocked).
 * - It then leaves in 280 ms, and the interface arrives over the next 700 ms.
 */
export const SHOW_AFTER_MS = 150;
export const MIN_VISIBLE_MS = 400;
export const MAX_WAIT_MS = 4000;
export const LEAVE_MS = 280;
export const ARRIVE_MS = 700;

export type BootPhase = "waiting" | "splash" | "leaving" | "arriving" | "done";

export interface BootTimes {
  /** When the app started, in ms (any clock, as long as `now` uses the same one). */
  start: number;
  /** When the workspace sync finished (well or not), or null while it runs. */
  settledAt: number | null;
}

/** When the splash goes away, or null if it never shows. */
export function splashEnd({ start, settledAt }: BootTimes): number | null {
  const shownAt = start + SHOW_AFTER_MS;
  const ready = Math.min(settledAt ?? Infinity, start + MAX_WAIT_MS);
  if (ready <= shownAt) return null;
  return Math.max(ready, shownAt + MIN_VISIBLE_MS);
}

export function bootPhase(now: number, times: BootTimes): BootPhase {
  const { start, settledAt } = times;
  const end = splashEnd(times);
  if (end === null) {
    // The sync finished before the logo was due: no splash, only the arrival.
    return now - (settledAt as number) < ARRIVE_MS ? "arriving" : "done";
  }
  if (now < start + SHOW_AFTER_MS) return "waiting";
  if (now < end) return "splash";
  if (now < end + LEAVE_MS) return "leaving";
  if (now < end + LEAVE_MS + ARRIVE_MS) return "arriving";
  return "done";
}

/** The next instant at which the phase can change, or null when it is settled. */
export function nextBootChange(now: number, times: BootTimes): number | null {
  const { start, settledAt } = times;
  const end = splashEnd(times);
  const marks = [start + SHOW_AFTER_MS, start + MAX_WAIT_MS];
  if (end !== null) marks.push(end, end + LEAVE_MS, end + LEAVE_MS + ARRIVE_MS);
  else if (settledAt !== null) marks.push(settledAt + ARRIVE_MS);
  const later = marks.filter((mark) => mark > now);
  return later.length ? Math.min(...later) : null;
}
