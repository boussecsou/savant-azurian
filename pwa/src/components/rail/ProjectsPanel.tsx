import { useEffect, useRef, useState } from "react";
import { COLORS, PROJECT_NAME_MAX, type Project } from "../../state/workspace";
import { Icon } from "../Icon";

interface Props {
  projects: readonly Project[];
  activeProjectId: string;
  sessionCount: (projectId: string) => number;
  renamingId: string | null;
  /** Returns an error message, or null when the project was created. */
  onCreate: (name: string, color: string) => string | null;
  onSelect: (id: string) => void;
  onMenu: (trigger: HTMLElement, project: Project) => void;
  onRename: (id: string, name: string) => string | null;
  onRenameEnd: () => void;
  /** Changes each time something asks for the "new project" form (the palette, for instance). */
  createSignal: number;
}

function ProjectName({ project, onRename, onRenameEnd }: { project: Project; onRename: Props["onRename"]; onRenameEnd: () => void }) {
  const [value, setValue] = useState(project.name);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);
  const commit = () => {
    if (!value.trim() || value.trim() === project.name) return onRenameEnd();
    const failure = onRename(project.id, value);
    if (failure) setError(failure);
    else onRenameEnd();
  };
  return (
    <div style={{ padding: "6px 8px" }}>
      <input
        ref={input}
        className="rename"
        value={value}
        maxLength={PROJECT_NAME_MAX}
        aria-label="Project name"
        aria-invalid={error ? "true" : undefined}
        onChange={(event) => {
          setValue(event.target.value);
          setError(null);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          } else if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            onRenameEnd();
          }
        }}
        onBlur={() => (error ? onRenameEnd() : commit())}
      />
      {error && (
        <p className="note" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** The projects, in the switcher's popover: pick one, create one, rename or delete from its menu. */
export function ProjectsPanel(props: Props) {
  const { projects, activeProjectId, sessionCount } = props;
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [color, setColor] = useState<string>(COLORS[3]);
  const [error, setError] = useState<string | null>(null);
  const field = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (creating) field.current?.focus();
  }, [creating]);

  const signal = useRef(props.createSignal);
  useEffect(() => {
    if (props.createSignal !== signal.current) {
      signal.current = props.createSignal;
      setCreating(true);
    }
  }, [props.createSignal]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const failure = props.onCreate(name, color);
    if (failure) {
      setError(failure);
      return;
    }
    setName("");
    setError(null);
    setCreating(false);
  };

  return (
    <div className="pswitch-list">
      <div className="block-head">
        <h2>Projects</h2>
        <button type="button" className="icon-btn sm press" aria-label="New project" aria-expanded={creating} onClick={() => setCreating((open) => !open)}>
          <Icon name="plus" />
        </button>
      </div>
      {creating && (
        <>
          <form className="inline-form" onSubmit={submit} autoComplete="off">
            <input
              ref={field}
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setError(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.stopPropagation();
                  setCreating(false);
                }
              }}
              placeholder="Project name"
              maxLength={PROJECT_NAME_MAX}
              aria-label="Project name"
              aria-invalid={error ? "true" : undefined}
            />
            <button type="submit" className="btn sm primary press">
              Create
            </button>
          </form>
          <div className="swatches" role="group" aria-label="Project colour">
            {COLORS.map((c) => (
              <button key={c} type="button" className="swatch press" style={{ ["--c" as string]: c }} aria-pressed={c === color} aria-label={`Colour ${c}`} onClick={() => setColor(c)} />
            ))}
          </div>
          {error && (
            <p className="note" role="alert" style={{ padding: "0 12px 8px" }}>
              {error}
            </p>
          )}
        </>
      )}
      <ul className="pcards">
        {projects.map((project) => {
          const count = sessionCount(project.id);
          return (
            <li key={project.id} className="pcard" data-active={project.id === activeProjectId ? "" : undefined}>
              {props.renamingId === project.id ? (
                <ProjectName project={project} onRename={props.onRename} onRenameEnd={props.onRenameEnd} />
              ) : (
                <>
                  <button type="button" className="pcard-main press" aria-current={project.id === activeProjectId ? "true" : undefined} onClick={() => props.onSelect(project.id)}>
                    <span className="dot" style={{ ["--c" as string]: project.color }} />
                    <span className="pcard-name">
                      <span>{project.name}</span>
                      {project.system && <span className="tag">default</span>}
                    </span>
                    <span className="pcard-sub">
                      {count} session{count === 1 ? "" : "s"}
                    </span>
                  </button>
                  <button type="button" className="icon-btn sm more press" aria-label={`Options for ${project.name}`} aria-haspopup="menu" onClick={(event) => props.onMenu(event.currentTarget, project)}>
                    <Icon name="more" />
                  </button>
                </>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
