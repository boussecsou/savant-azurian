/**
 * A project's documents (SDD-005 phase 4): the files Savant searches when the owner asks about them.
 * The states come from the BFF, which reads them from Azure (index and indexer): never simulated here,
 * except "uploading" while the browser is still sending the file.
 */
import { ApiError, kindForStatus, type ApiErrorKind } from "./api";

export { mergeSources, parseSources, type Source } from "./sources";

export type DocumentState = "uploading" | "indexing" | "ready" | "failed";

export interface ProjectDocument {
  id: string;
  projectId: string;
  name: string;
  size: number;
  uploadedAt: number;
  state: DocumentState;
}

/** What the indexer reads (scripts/search_setup.py) and the Basic tier's file size limit. */
export const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".pptx", ".txt", ".md"] as const;
export const MAX_DOCUMENT_BYTES = 16 * 1024 * 1024;
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.join(",");

/** While any document is indexing, its state is read again this often. */
export const POLL_MS = 5000;

function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

/** Why this file cannot be added, in plain words, or null when it can. */
export function checkFile(file: { name: string; size: number }): string | null {
  if (!ACCEPTED_EXTENSIONS.includes(extension(file.name) as (typeof ACCEPTED_EXTENSIONS)[number])) {
    return `“${file.name}” is not supported. Add a PDF, Word, PowerPoint, text or Markdown file.`;
  }
  if (file.size === 0) return `“${file.name}” is empty.`;
  if (file.size > MAX_DOCUMENT_BYTES) return `“${file.name}” is larger than 16 MB.`;
  return null;
}

export type DocumentKind = "pdf" | "word" | "slides" | "markdown" | "text";

/** The short badge shown on a document or a source chip. */
export function documentKind(name: string): DocumentKind {
  switch (extension(name)) {
    case ".pdf":
      return "pdf";
    case ".docx":
      return "word";
    case ".pptx":
      return "slides";
    case ".md":
      return "markdown";
    default:
      return "text";
  }
}

export const KIND_LABEL: Record<DocumentKind, string> = { pdf: "PDF", word: "DOC", slides: "PPT", markdown: "MD", text: "TXT" };

export interface SettledUpload {
  id: string;
  name: string;
  outcome: "ready" | "failed" | "gone";
}

/**
 * Of the files added in this page (id → name), those whose story is over: indexed, failed, or no longer
 * listed (removed meanwhile). A file still being sent or indexed is not reported: keep watching it.
 */
export function settledUploads(watched: ReadonlyMap<string, string>, documents: readonly ProjectDocument[]): SettledUpload[] {
  const settled: SettledUpload[] = [];
  for (const [id, name] of watched) {
    const found = documents.find((d) => d.id === id);
    if (!found) settled.push({ id, name, outcome: "gone" });
    else if (found.state === "ready" || found.state === "failed") settled.push({ id, name, outcome: found.state });
  }
  return settled;
}

export const STATE_LABEL: Record<DocumentState, string> = {
  uploading: "Uploading…",
  indexing: "Indexing…",
  ready: "Ready",
  failed: "Failed",
};

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Opens in a new tab through the same /api proxy, which adds the owner's token. */
export function documentFileUrl(projectId: string, documentId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/file`;
}

function isDocument(value: unknown): value is ProjectDocument {
  if (!value || typeof value !== "object") return false;
  const d = value as Record<string, unknown>;
  return typeof d.id === "string" && typeof d.name === "string" && typeof d.projectId === "string"
    && (d.state === "indexing" || d.state === "ready" || d.state === "failed");
}

/** A document error the owner can act on: the BFF's own reason for 413/415/422, else the generic kind. */
export class DocumentApiError extends ApiError {
  constructor(kind: ApiErrorKind, status: number | undefined, public readonly reason?: string) {
    super(kind, status);
  }
}

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, { cache: "no-store", ...init });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new DocumentApiError("network", undefined);
  }
  if (!response.ok) {
    let reason: string | undefined;
    if (response.status === 413 || response.status === 415 || response.status === 422) {
      try {
        const body = (await response.json()) as { detail?: unknown };
        reason = typeof body.detail === "string" ? body.detail : undefined;
      } catch {
        reason = undefined;
      }
    }
    throw new DocumentApiError(kindForStatus(response.status), response.status, reason);
  }
  return response;
}

function base(projectId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/documents`;
}

export async function listDocuments(projectId: string, signal?: AbortSignal): Promise<ProjectDocument[]> {
  const body = (await (await call(base(projectId), { signal })).json()) as unknown;
  return Array.isArray(body) ? body.filter(isDocument) : [];
}

/** Sends the file as the request body; its name travels in the query string. */
export async function uploadDocument(projectId: string, file: Blob & { name: string }): Promise<ProjectDocument> {
  const response = await call(`${base(projectId)}?name=${encodeURIComponent(file.name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: file,
  });
  const body = (await response.json()) as unknown;
  if (!isDocument(body)) throw new DocumentApiError("upstream", response.status);
  return body;
}

export async function deleteDocument(projectId: string, documentId: string): Promise<void> {
  await call(`${base(projectId)}/${encodeURIComponent(documentId)}`, { method: "DELETE" });
}

/** The stored file, as a File with its name: kept in memory while its removal can be undone. */
export async function downloadDocument(document: ProjectDocument): Promise<File> {
  const response = await call(documentFileUrl(document.projectId, document.id), {});
  const blob = await response.blob();
  return new File([blob], document.name, { type: blob.type });
}

/** A short sentence for a failed document request. */
export function documentErrorMessage(error: unknown): string {
  if (error instanceof DocumentApiError && error.reason) return error.reason;
  if (error instanceof ApiError) {
    if (error.status === 404) return "This project or document no longer exists.";
    if (error.kind === "auth") return "Access denied. Sign in again with “az login”, then restart the development server.";
    if (error.kind === "network") return "Cannot connect. Check your network and try again.";
  }
  return "The documents service is not answering right now. Try again in a moment.";
}
