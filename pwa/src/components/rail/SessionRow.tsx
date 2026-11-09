import { memo, useEffect, useRef, useState } from "react";
import { relTime } from "../../state/grouping";
import type { Project, Session } from "../../state/workspace";
import { Icon } from "../Icon";

interface Props {
  session: Session;
  project?: Project;
  /** Show the project's dot and name: in the "All" scope and nowhere else. */
  showProject: boolean;
  active: boolean;
  renaming: boolean;
  now: number;
  onOpen: (id: string) => void;
  onMenu: (trigger: HTMLElement, session: Session) => void;
  onContextMenu: (x: number, y: number, session: Session) => void;
  onRename: (id: string, title: string) => void;
  onRenameEnd: () => void;
  onStartRename: (id: string) => void;
}

/** One session in the rail. F2, a double click or the menu rename it; Enter saves, Escape cancels. */
export const SessionRow = memo(function SessionRow({ session, project, showProject, active, renaming, now, onOpen, onMenu, onContextMenu, onRename, onRenameEnd, onStartRename }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(session.title);

  useEffect(() => {
    if (!renaming) return;
    setValue(session.title);
    input.current?.focus();
    input.current?.select();
  }, [renaming, session.title]);

  const count = `${session.messageCount} msg`;

  return (
    <li className="row">
      <div className="row-in">
        {renaming ? (
          <input
            ref={input}
            className="rename"
            value={value}
            aria-label="Session name"
            maxLength={84}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                if (value.trim()) onRename(session.id, value);
                onRenameEnd();
              } else if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                onRenameEnd();
              }
            }}
            onBlur={() => {
              if (value.trim() && value !== session.title) onRename(session.id, value);
              onRenameEnd();
            }}
          />
        ) : (
          <div
            className="sess"
            onContextMenu={(event) => {
              event.preventDefault();
              onContextMenu(event.clientX, event.clientY, session);
            }}
          >
            <button
              type="button"
              className="sess-btn press"
              aria-current={active ? "true" : undefined}
              onClick={() => onOpen(session.id)}
              onDoubleClick={() => onStartRename(session.id)}
            >
              <span className="sess-top">
                <span className="sess-title">{session.title}</span>
                {session.pinned && (
                  <span className="pin-mark" role="img" aria-label="Pinned">
                    <Icon name="pin" />
                  </span>
                )}
              </span>
              <span className="sess-sub">
                {showProject && project && (
                  <>
                    <span className="dot" style={{ ["--c" as string]: project.color }} />
                    <span>{project.name} ·</span>
                  </>
                )}
                <span>
                  {relTime(session.updatedAt, now)} · {count}
                </span>
              </span>
            </button>
            <button type="button" className="icon-btn sm more press" aria-label={`Options for ${session.title}`} aria-haspopup="menu" onClick={(event) => onMenu(event.currentTarget, session)}>
              <Icon name="more" />
            </button>
          </div>
        )}
      </div>
    </li>
  );
});
