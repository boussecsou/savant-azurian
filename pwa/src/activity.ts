/**
 * In-memory activity journal for the Journal view.
 *
 * It records what the browser itself observes (turn durations, failure kinds, Notion
 * state changes) and never message content, identifiers or tokens. Nothing is
 * persisted: closing the tab clears it.
 */

export type ActivityLevel = "info" | "ok" | "warn" | "error";

/** chat: a whole turn · first-text: delay before the first words · tool: one tool call · warmup: agent wake-up. */
export type ActivityKind = "chat" | "first-text" | "tool" | "warmup" | "system";

export interface ActivityEntry {
  id: string;
  at: number;
  kind: ActivityKind;
  level: ActivityLevel;
  label: string;
  /** Duration in milliseconds, when the event measures one. */
  ms?: number;
  /** Raw tool name for tool events, so the settings drawer can list what was used. */
  tool?: string;
}

export const MAX_ENTRIES = 80;

/** Newest first, capped so a long session cannot grow without bound. */
export function pushActivity(
  list: readonly ActivityEntry[],
  entry: ActivityEntry,
  max: number = MAX_ENTRIES,
): ActivityEntry[] {
  return [entry, ...list].slice(0, max);
}

export interface ActivitySummary {
  turns: number;
  lastMs?: number;
  averageMs?: number;
  /** Delay before the first words of the latest answer: what the reader actually waits for. */
  firstTextMs?: number;
}

/** Statistics over successful chat turns only: a failure's duration is not a response time. */
export function summarize(list: readonly ActivityEntry[]): ActivitySummary {
  const durations = list
    .filter((e) => e.kind === "chat" && e.level === "ok" && typeof e.ms === "number")
    .map((e) => e.ms as number);
  const firstTextMs = list.find((e) => e.kind === "first-text")?.ms;
  if (durations.length === 0) return { turns: 0, firstTextMs };
  const total = durations.reduce((sum, ms) => sum + ms, 0);
  return { turns: durations.length, lastMs: durations[0], averageMs: Math.round(total / durations.length), firstTextMs };
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
}
