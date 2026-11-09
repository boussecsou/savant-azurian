import { useMemo, useState } from "react";
import { groupSessions } from "../../state/grouping";
import type { Project, Session } from "../../state/workspace";
import { Icon } from "../Icon";
import { SessionRow } from "./SessionRow";

export type Scope = "project" | "all";

interface Props {
  projects: readonly Project[];
  sessions: readonly Session[];
  activeProject: Project;
  activeSessionId: string;
  renamingId: string | null;
  /** The text of a session's messages, lower-cased, for the search. Read only while searching. */
  messageText: (sessionId: string) => string;
  onOpen: (id: string) => void;
  onNew: () => void;
  onMenu: (trigger: HTMLElement, session: Session) => void;
  onContextMenu: (x: number, y: number, session: Session) => void;
  onRename: (id: string, title: string) => void;
  onRenameEnd: () => void;
  onStartRename: (id: string) => void;
}

/** The sessions of the active project (or of all projects), grouped by day, with a search. */
export function SessionsPanel(props: Props) {
  const { projects, sessions, activeProject, activeSessionId, messageText } = props;
  const [scope, setScope] = useState<Scope>("project");
  const [query, setQuery] = useState("");
  const now = Date.now();
  const byId = useMemo(() => new Map(projects.map((p) => [p.id, p])), [projects]);

  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = sessions.filter((s) => scope === "all" || s.projectId === activeProject.id);
    if (q) list = list.filter((s) => s.title.toLowerCase().includes(q) || messageText(s.id).includes(q));
    return groupSessions(list, now);
    // `now` is read once per render on purpose: relative times refresh when the list changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions, scope, activeProject.id, query, messageText]);

  return (
    <>
      <div className="rail-scroll">
        <div className="block-head">
          <h2>Sessions</h2>
          <div className="seg" role="group" aria-label="Session scope">
            <button type="button" className="press" aria-pressed={scope === "project"} onClick={() => setScope("project")}>
              Project
            </button>
            <button type="button" className="press" aria-pressed={scope === "all"} onClick={() => setScope("all")}>
              All
            </button>
          </div>
        </div>
        <button type="button" className="new-session press" onClick={props.onNew}>
          <Icon name="plus" />
          New session
        </button>
        <label className="search">
          <Icon name="search" />
          <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search sessions" aria-label="Search sessions" autoComplete="off" />
        </label>
        {items.length === 0 ? (
          <p className="empty-note">
            {query ? `No session matches “${query}”.` : `No sessions in this project yet. Start one — it will be filed under ${activeProject.name}.`}
          </p>
        ) : (
          <ul>
            {items.map((item) =>
              item.kind === "heading" ? (
                <li key={`h-${item.label}`} className="group-label">
                  {item.label}
                </li>
              ) : (
                <SessionRow
                  key={item.session.id}
                  session={item.session}
                  project={byId.get(item.session.projectId)}
                  showProject={scope === "all"}
                  active={item.session.id === activeSessionId}
                  renaming={props.renamingId === item.session.id}
                  now={now}
                  onOpen={props.onOpen}
                  onMenu={props.onMenu}
                  onContextMenu={props.onContextMenu}
                  onRename={props.onRename}
                  onRenameEnd={props.onRenameEnd}
                  onStartRename={props.onStartRename}
                />
              ),
            )}
          </ul>
        )}
      </div>
    </>
  );
}
