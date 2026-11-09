import { useEffect, useRef, useState } from "react";
import type { Project } from "../../state/workspace";
import { Icon } from "../Icon";

interface Props {
  title: string;
  project: Project;
  /** The rail is folded away (or is a drawer): offer to bring it back. */
  showRailButton: boolean;
  onShowRail: () => void;
  focus: boolean;
  onFocus: () => void;
  chatOnly: boolean;
  onChatOnly: () => void;
  attention: boolean;
  settingsOpen: boolean;
  onSettings: () => void;
  onRename: (title: string) => void;
  renaming: boolean;
  onRenameEnd: () => void;
  onStartRename: () => void;
}

/** Session title (a double click renames it), its project, Chat only, Focus and Settings. Connections live in Settings only. */
export function TopBar(props: Props) {
  const { title, project, attention } = props;
  const [value, setValue] = useState(title);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!props.renaming) return;
    setValue(title);
    input.current?.focus();
    input.current?.select();
  }, [props.renaming, title]);

  return (
    <header className="topbar">
      {props.showRailButton && (
        <button type="button" className="icon-btn press" aria-label="Show sessions" onClick={props.onShowRail}>
          <Icon name="rail" size="md" />
        </button>
      )}
      <div className="top-title">
        {props.renaming ? (
          <input
            ref={input}
            className="rename-title"
            value={value}
            maxLength={84}
            aria-label="Session name"
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                if (value.trim()) props.onRename(value);
                props.onRenameEnd();
              } else if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                props.onRenameEnd();
              }
            }}
            onBlur={() => {
              if (value.trim() && value !== title) props.onRename(value);
              props.onRenameEnd();
            }}
          />
        ) : (
          <h1 title="Double-click to rename" onDoubleClick={props.onStartRename}>
            {title}
          </h1>
        )}
        <span className="chip-proj">
          <span className="dot" style={{ ["--c" as string]: project.color }} />
          <span>{project.name}</span>
        </span>
      </div>
      <div className="top-actions">
        <button
          type="button"
          className="icon-btn press"
          aria-pressed={props.chatOnly}
          aria-label="Chat only"
          title={props.chatOnly ? "Back to voice and chat" : "Chat only"}
          onClick={props.onChatOnly}
        >
          <Icon name={props.chatOnly ? "orb" : "thread"} size="md" />
        </button>
        <button type="button" className="icon-btn press" aria-pressed={props.focus} aria-label="Focus mode" title="Focus mode" onClick={props.onFocus}>
          <Icon name="focus" size="md" />
        </button>
        <button
          type="button"
          className="icon-btn press"
          aria-haspopup="dialog"
          aria-expanded={props.settingsOpen}
          aria-label={attention ? "Open settings — a connection needs attention" : "Open settings"}
          title={attention ? "Settings — a connection needs attention" : "Settings"}
          onClick={props.onSettings}
        >
          <Icon name="sliders" size="md" />
          {attention && <span className="attn" aria-hidden="true" />}
        </button>
      </div>
    </header>
  );
}
