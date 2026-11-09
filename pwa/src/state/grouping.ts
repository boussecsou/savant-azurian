const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Age of a session as the rail shows it: "now", "5 min", "3 h", "2 d". */
export function relTime(at: number, now: number = Date.now()): string {
  const age = now - at;
  if (age < MINUTE) return "now";
  if (age < HOUR) return `${Math.floor(age / MINUTE)} min`;
  if (age < DAY) return `${Math.floor(age / HOUR)} h`;
  return `${Math.floor(age / DAY)} d`;
}

export type DayGroup = "Today" | "Yesterday" | "Earlier";

/** Calendar buckets: "Today" starts at local midnight, "Yesterday" is the 24 hours before it. */
export function dayGroup(at: number, now: number = Date.now()): DayGroup {
  const midnight = new Date(now);
  midnight.setHours(0, 0, 0, 0);
  const diff = midnight.getTime() - at;
  if (diff <= 0) return "Today";
  if (diff <= DAY) return "Yesterday";
  return "Earlier";
}

export type RailItem<T> = { kind: "heading"; label: string } | { kind: "session"; session: T };

interface Groupable {
  pinned: boolean;
  updatedAt: number;
}

/** Pinned first, then Today / Yesterday / Earlier, newest first inside each group. Empty groups are skipped. */
export function groupSessions<T extends Groupable>(sessions: readonly T[], now: number = Date.now()): RailItem<T>[] {
  const sorted = sessions.slice().sort((a, b) => b.updatedAt - a.updatedAt);
  const items: RailItem<T>[] = [];
  const add = (label: string, group: T[]) => {
    if (!group.length) return;
    items.push({ kind: "heading", label });
    for (const session of group) items.push({ kind: "session", session });
  };
  add("Pinned", sorted.filter((s) => s.pinned));
  for (const label of ["Today", "Yesterday", "Earlier"] as const) {
    add(label, sorted.filter((s) => !s.pinned && dayGroup(s.updatedAt, now) === label));
  }
  return items;
}
