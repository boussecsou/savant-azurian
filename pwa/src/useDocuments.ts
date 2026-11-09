import { useCallback, useEffect, useRef, useState } from "react";
import {
  POLL_MS,
  checkFile,
  deleteDocument,
  documentErrorMessage,
  downloadDocument,
  listDocuments,
  uploadDocument,
  type ProjectDocument,
} from "./documents";

export type UploadResult = { document: ProjectDocument; temporaryId: string } | { error: string };

export interface DocumentsApi {
  documents: ProjectDocument[];
  /** Ids hidden while their removal is being sent. */
  hidden: ReadonlySet<string>;
  loaded: boolean;
  error: string | null;
  /**
   * Sends the files to the project. `onQueued` gets at once the temporary ids of the accepted files (their
   * "Uploading…" entries); the result gives, per file, the stored document (and its temporary id) or why
   * it was refused.
   */
  upload: (files: readonly File[], onQueued?: (temporaryIds: string[]) => void) => Promise<UploadResult[]>;
  /**
   * Removes at once, everywhere (index, then file): from the next question on, Savant no longer finds it.
   * Resolves with a copy of the file, for Undo (sent again as a new document), or null if none could be
   * kept. Rejects (and shows the document again) if the removal failed.
   */
  remove: (document: ProjectDocument) => Promise<File | null>;
  refresh: () => Promise<void>;
}

/**
 * The active project's documents. The list comes from the BFF; while one is indexing it is read again
 * every few seconds, so "Indexing…" turns into "Ready" (or "Failed") without a reload.
 */
export function useDocuments(projectId: string, enabled: boolean): DocumentsApi {
  const [documents, setDocuments] = useState<ProjectDocument[]>([]);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = useRef(projectId);
  current.current = projectId;

  const refresh = useCallback(async () => {
    if (!enabled) return;
    const asked = projectId;
    try {
      const listed = await listDocuments(asked);
      if (current.current !== asked) return;
      // Keep files still being sent: the server does not know them yet.
      setDocuments((previous) => [...previous.filter((d) => d.state === "uploading" && d.projectId === asked), ...listed]);
      setError(null);
    } catch (caught) {
      if (current.current === asked) setError(documentErrorMessage(caught));
    } finally {
      if (current.current === asked) setLoaded(true);
    }
  }, [enabled, projectId]);

  useEffect(() => {
    setDocuments([]);
    setLoaded(false);
    setError(null);
    void refresh();
  }, [refresh]);

  const indexing = documents.some((d) => d.state === "indexing");
  useEffect(() => {
    if (!enabled || !indexing) return;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, indexing, refresh]);

  const upload = useCallback(
    async (files: readonly File[], onQueued?: (temporaryIds: string[]) => void): Promise<UploadResult[]> => {
      const project = projectId;
      const queued = files.map((file) => {
        const refused = checkFile(file);
        if (refused) return { file, refused };
        const temporary: ProjectDocument = {
          id: `uploading-${crypto.randomUUID()}`, projectId: project, name: file.name, size: file.size,
          uploadedAt: Date.now(), state: "uploading",
        };
        return { file, temporary };
      });
      const temporaries = queued.flatMap((entry) => ("temporary" in entry && entry.temporary ? [entry.temporary] : []));
      setDocuments((previous) => [...temporaries, ...previous]);
      onQueued?.(temporaries.map((t) => t.id));
      return Promise.all(
        queued.map(async (entry): Promise<UploadResult> => {
          if (!("temporary" in entry) || !entry.temporary) return { error: entry.refused ?? "Not supported." };
          const temporary = entry.temporary;
          try {
            const added = await uploadDocument(project, entry.file);
            setDocuments((previous) => previous.map((d) => (d.id === temporary.id ? added : d)));
            return { document: added, temporaryId: temporary.id };
          } catch (caught) {
            setDocuments((previous) => previous.filter((d) => d.id !== temporary.id));
            return { error: documentErrorMessage(caught) };
          }
        }),
      );
    },
    [projectId],
  );

  const remove = useCallback(
    async (document: ProjectDocument): Promise<File | null> => {
      const show = () =>
        setHidden((previous) => {
          const next = new Set(previous);
          next.delete(document.id);
          return next;
        });
      setHidden((previous) => new Set(previous).add(document.id));
      // A copy first, so Undo can bring it back; a failed copy only means no Undo.
      const copy = await downloadDocument(document).catch(() => null);
      try {
        await deleteDocument(document.projectId, document.id);
        setDocuments((previous) => previous.filter((d) => d.id !== document.id));
        return copy;
      } finally {
        show();
      }
    },
    [],
  );

  return { documents, hidden, loaded, error, upload, remove, refresh };
}
