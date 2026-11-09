import { formatDuration, summarize, type ActivityEntry } from "../activity";
import type { NotionState } from "../useNotion";
import type { WarmState } from "../useWarmup";
import { Icon } from "./Icon";

type Tone = "ok" | "warn" | "error" | "idle";

interface Props {
  entries: readonly ActivityEntry[];
  notion: NotionState;
  warm: WarmState;
  onClear: () => void;
}

const NOTION: Record<NotionState, [string, Tone]> = {
  unknown: ["Checking…", "idle"],
  disconnected: ["Not connected", "warn"],
  waiting: ["Waiting for consent", "warn"],
  connected: ["Connected", "ok"],
  unavailable: ["Unavailable", "error"],
};

function bffStatus(notion: NotionState): [string, Tone] {
  if (notion === "unknown") return ["Checking…", "idle"];
  if (notion === "unavailable") return ["Unreachable", "error"];
  return ["Reachable", "ok"];
}

function agentStatus(entries: readonly ActivityEntry[], warm: WarmState): [string, Tone] {
  const last = entries.find((e) => e.kind === "chat");
  if (last) return last.level === "ok" ? ["Answered", "ok"] : ["Last exchange failed", "error"];
  if (warm.status === "warming") return ["Warming up…", "warn"];
  if (warm.status === "ready") return [`Ready (${formatDuration(warm.ms ?? 0)})`, "ok"];
  if (warm.status === "failed") return ["Warm-up failed", "error"];
  if (warm.status === "unsupported") return ["Warm-up unavailable", "idle"];
  return ["No exchange yet", "idle"];
}

const time = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** What this browser observes: response times, tool calls and errors. Message content is never recorded. */
export function Diagnostics({ entries, notion, warm, onClear }: Props) {
  const stats = summarize(entries);
  const services: [string, [string, Tone]][] = [
    ["Notion", NOTION[notion]],
    ["BFF gateway", bffStatus(notion)],
    ["Agent", agentStatus(entries, warm)],
  ];
  return (
    <>
      <div className="diag-head">
        <p className="s-lead">What this browser observes. Message content is never recorded, and this list disappears when the tab is closed.</p>
        <button type="button" className="btn sm press" onClick={onClear} disabled={entries.length === 0}>
          Clear
        </button>
      </div>

      <ul className="services">
        {services.map(([name, [label, tone]]) => (
          <li key={name} className="service">
            <span>{name}</span>
            <span className="service-state" data-tone={tone}>
              <i aria-hidden="true" />
              {label}
            </span>
          </li>
        ))}
      </ul>

      <dl className="stats">
        <div>
          <dt>First text</dt>
          <dd>{stats.firstTextMs !== undefined ? formatDuration(stats.firstTextMs) : "—"}</dd>
        </div>
        <div>
          <dt>Last answer</dt>
          <dd>{stats.lastMs !== undefined ? formatDuration(stats.lastMs) : "—"}</dd>
        </div>
        <div>
          <dt>Average</dt>
          <dd>{stats.averageMs !== undefined ? formatDuration(stats.averageMs) : "—"}</dd>
        </div>
        <div>
          <dt>Answers received</dt>
          <dd>{stats.turns}</dd>
        </div>
      </dl>

      {entries.length === 0 ? (
        <p className="empty-note">No events yet. Send a message to measure the response time.</p>
      ) : (
        <ol className="events" aria-label="Events">
          {entries.map((entry) => (
            <li key={entry.id} className="event" data-level={entry.level}>
              <i aria-hidden="true" />
              <span>{entry.label}</span>
              {entry.ms !== undefined ? (
                <span className="event-ms">
                  <Icon name="refresh" />
                  {formatDuration(entry.ms)}
                </span>
              ) : (
                <span />
              )}
              <time className="event-time">{time.format(entry.at)}</time>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
