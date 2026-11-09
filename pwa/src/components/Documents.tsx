import { useRef, useState, type DragEvent } from "react";
import {
  ACCEPT_ATTRIBUTE,
  KIND_LABEL,
  STATE_LABEL,
  documentFileUrl,
  documentKind,
  formatSize,
  type ProjectDocument,
  type Source,
} from "../documents";
import { Icon } from "./Icon";

/** The file-type badge: PDF, DOC, PPT or TXT. */
function KindBadge({ name }: { name: string }) {
  const kind = documentKind(name);
  return (
    <span className="dkind" data-kind={kind} aria-hidden="true">
      {KIND_LABEL[kind]}
    </span>
  );
}

function StateTag({ document }: { document: ProjectDocument }) {
  return (
    <span className="dstate" data-state={document.state} role="status">
      {(document.state === "uploading" || document.state === "indexing") && <span className="spin" aria-hidden="true" />}
      {STATE_LABEL[document.state]}
    </span>
  );
}

function open_(projectId: string, documentId: string) {
  window.open(documentFileUrl(projectId, documentId), "_blank", "noopener");
}

/** Files dropped or picked: the same path for the project card and the composer. */
export function useFilePicker(onFiles: (files: File[]) => void) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const pick = () => input.current?.click();
  const element = (
    <input
      ref={input}
      type="file"
      multiple
      accept={ACCEPT_ATTRIBUTE}
      hidden
      onChange={(event) => {
        const files = Array.from(event.target.files ?? []);
        event.target.value = "";
        if (files.length) onFiles(files);
      }}
    />
  );
  const drop = {
    onDragOver: (event: DragEvent) => {
      if (!event.dataTransfer.types.includes("Files")) return;
      event.preventDefault();
      setOver(true);
    },
    onDragLeave: (event: DragEvent) => {
      // Moving between two children of the target also fires dragleave: only leaving the target counts.
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false);
    },
    onDrop: (event: DragEvent) => {
      if (!event.dataTransfer.files.length) return;
      event.preventDefault();
      setOver(false);
      onFiles(Array.from(event.dataTransfer.files));
    },
  };
  return { input: element, pick, drop, over };
}

interface SectionProps {
  projectName: string;
  documents: readonly ProjectDocument[];
  hidden: ReadonlySet<string>;
  loaded: boolean;
  error: string | null;
  onAdd: (files: File[]) => void;
  onRemove: (document: ProjectDocument) => void;
}

/**
 * The active project's sources, in the rail under its sessions: the project's name is in the header so the
 * destination of a file is never in doubt. Add (button or drop), real states, open, remove (with Undo).
 */
export function SourcesSection({ projectName, documents, hidden, loaded, error, onAdd, onRemove }: SectionProps) {
  const { input, pick, drop, over } = useFilePicker(onAdd);
  const [open, setOpen] = useState(true);
  const visible = documents.filter((d) => !hidden.has(d.id));
  return (
    <section className="sources-section" aria-label={`Sources of ${projectName}`} data-over={over ? "" : undefined} {...drop}>
      <div className="sources-head">
        <button type="button" className="sources-toggle press" aria-expanded={open} aria-controls="sources-body" onClick={() => setOpen((value) => !value)}>
          <Icon name="chevron" />
          <b>Sources</b>
          <span className="sources-proj">· {projectName}</span>
          {visible.length > 0 && <span className="sources-count">{visible.length}</span>}
        </button>
        <button type="button" className="icon-btn sm press" aria-label={`Add to ${projectName}'s sources`} title={`Add to ${projectName}'s sources`} onClick={pick}>
          <Icon name="plus" />
        </button>
        {input}
      </div>
      <div className="sources-body" id="sources-body" data-open={open ? "" : undefined} inert={!open}>
        <div className="sources-body-in">
          {error && (
            <p className="note" role="alert">
              {error}
            </p>
          )}
          {loaded && visible.length === 0 && !error ? (
            <button type="button" className="docs-empty press" onClick={pick}>
              <Icon name="file" />
              <span>Drop a PDF, Word, PowerPoint, text or Markdown file here, or click to add it to {projectName}. Savant searches the sources when you ask.</span>
            </button>
          ) : (
            <ul className="docs-list">
              {visible.map((document) => (
                <li key={document.id} className="doc" data-state={document.state}>
                  <KindBadge name={document.name} />
                  <button
                    type="button"
                    className="doc-name press"
                    disabled={document.state === "uploading"}
                    title={document.name}
                    aria-label={`Open ${document.name}`}
                    onClick={() => open_(document.projectId, document.id)}
                  >
                    <span className="truncate">{document.name}</span>
                    <span className="doc-sub">
                      {formatSize(document.size)} · <StateTag document={document} />
                    </span>
                  </button>
                  {document.state !== "uploading" && (
                    <button type="button" className="icon-btn sm press" aria-label={`Remove ${document.name}`} title="Remove" onClick={() => onRemove(document)}>
                      <Icon name="trash" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

/** Over the thread while files are dragged in: says where they will go. */
export function DropVeil({ projectName }: { projectName: string }) {
  return (
    <div className="drop-veil" aria-hidden="true">
      <Icon name="file" size="md" />
      <b>Add to {projectName}'s sources</b>
      <span>PDF, Word, PowerPoint, text or Markdown</span>
    </div>
  );
}

/** Under an answer: the documents it used. A known document opens; an unknown one is just named. */
export function SourceChips({ sources, projectId, known }: { sources: readonly Source[]; projectId: string; known: ReadonlySet<string> }) {
  if (sources.length === 0) return null;
  return (
    <div className="sources" aria-label="Sources used">
      <span className="sources-label">
        <Icon name="doc" /> Sources · {sources.length}
      </span>
      {sources.map((source) =>
        known.has(source.documentId) ? (
          <button
            type="button"
            key={source.documentId}
            className="dchip press"
            title={`Open ${source.title}`}
            onClick={() => open_(projectId, source.documentId)}
          >
            <KindBadge name={source.title} />
            <span className="dchip-name">{source.title}</span>
          </button>
        ) : (
          <span key={source.documentId} className="dchip" title={source.title}>
            <KindBadge name={source.title} />
            <span className="dchip-name">{source.title}</span>
          </span>
        ),
      )}
    </div>
  );
}
