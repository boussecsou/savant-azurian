import { parseSources, type Source } from "./sources";

/** Calls to the BFF. The local dev proxy forwards /api/* with the owner's Entra token; the browser holds no token. */

export type ApiErrorKind = "auth" | "timeout" | "upstream" | "invalid" | "network" | "unknown";

export class ApiError extends Error {
  constructor(
    public readonly kind: ApiErrorKind,
    /** HTTP status when the error comes from a response. */
    public readonly status?: number,
  ) {
    super(kind);
  }
}

export interface ChatReply {
  conversationId: string;
  reply: string;
}

export const NOTION_START_URL = "/api/oauth/notion/start";

export function kindForStatus(status: number): ApiErrorKind {
  if (status === 401 || status === 403) return "auth";
  if (status === 504) return "timeout";
  if (status === 502 || status === 503) return "upstream";
  if (status === 422) return "invalid";
  return "unknown";
}

async function request(path: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, { cache: "no-store", ...init });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("network");
  }
  if (!response.ok) throw new ApiError(kindForStatus(response.status), response.status);
  return response;
}

export async function getNotionStatus(signal?: AbortSignal): Promise<boolean> {
  const response = await request("/api/oauth/notion/status", { signal });
  const body = (await response.json()) as { connected?: unknown };
  return body.connected === true;
}

/** "voice" asks the agent for an answer meant to be heard: short, no Markdown. */
export type ChatMode = "text" | "voice";

export async function sendChat(
  message: string,
  conversationId: string | undefined,
  signal?: AbortSignal,
  mode: ChatMode = "text",
  /** Server-side session recorded by the BFF. Only passed once the session is known to exist. */
  sessionId?: string,
): Promise<ChatReply> {
  const response = await request("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId, mode, ...(sessionId ? { session_id: sessionId } : {}) }),
    signal,
  });
  const body = (await response.json()) as { conversation_id?: unknown; reply?: unknown };
  if (typeof body.conversation_id !== "string" || typeof body.reply !== "string") {
    throw new ApiError("upstream");
  }
  return { conversationId: body.conversation_id, reply: body.reply };
}

const MESSAGES: Record<ApiErrorKind, string> = {
  auth: "Access denied. Sign in again with “az login”, then restart the development server.",
  timeout: "The answer took too long. Try again in a moment.",
  upstream: "The assistant is not answering right now. Try again in a moment.",
  invalid: "This message could not be sent. Shorten it and try again.",
  network: "Cannot connect. Check your network and try again.",
  unknown: "Something went wrong. Try again in a moment.",
};

export function errorMessage(kind: ApiErrorKind): string {
  return MESSAGES[kind];
}

/** What the BFF's /api/chat/stream sends: text, tool calls, and a final `done` or `error`. */
export type StreamEvent =
  | { type: "delta"; text: string }
  | { type: "tool"; id: string; name?: string; status: "running" | "done"; consent?: boolean }
  | { type: "sources"; id: string; sources: Source[] }
  | { type: "done"; conversationId: string }
  | { type: "error"; kind: ApiErrorKind };

/** Thrown when the BFF does not know the streaming route yet (an older image): use /api/chat. */
export class StreamUnsupported extends Error {}

const ERROR_KINDS: readonly ApiErrorKind[] = ["auth", "timeout", "upstream", "invalid", "network", "unknown"];

function toEvent(value: unknown): StreamEvent | null {
  if (!value || typeof value !== "object") return null;
  const e = value as Record<string, unknown>;
  switch (e.type) {
    case "delta":
      return typeof e.text === "string" && e.text ? { type: "delta", text: e.text } : null;
    case "tool":
      if (typeof e.id !== "string" || (e.status !== "running" && e.status !== "done")) return null;
      return {
        type: "tool",
        id: e.id,
        name: typeof e.name === "string" ? e.name : undefined,
        status: e.status,
        ...(e.consent === true ? { consent: true } : {}),
      };
    case "sources": {
      const sources = parseSources(e.sources);
      return typeof e.id === "string" && sources.length > 0 ? { type: "sources", id: e.id, sources } : null;
    }
    case "done":
      return typeof e.conversation_id === "string" ? { type: "done", conversationId: e.conversation_id } : null;
    case "error":
      return { type: "error", kind: ERROR_KINDS.find((k) => k === e.kind) ?? "upstream" };
    default:
      return null;
  }
}

/** Split a growing text buffer into complete events and the unfinished remainder. */
export function parseSse(buffer: string): { events: StreamEvent[]; rest: string } {
  const blocks = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: StreamEvent[] = [];
  for (const block of blocks) {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .join("");
    if (!data) continue;
    try {
      const event = toEvent(JSON.parse(data));
      if (event) events.push(event);
    } catch {
      // A malformed block is skipped: the stream keeps going.
    }
  }
  return { events, rest };
}

/**
 * Send a message and report the answer as it is written. Resolves after a `done` event;
 * rejects with ApiError, or StreamUnsupported when the BFF has no streaming route.
 */
export async function streamChat(
  message: string,
  conversationId: string | undefined,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
  mode: ChatMode = "text",
  /** Server-side session recorded by the BFF. Only passed once the session is known to exist. */
  sessionId?: string,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/chat/stream", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, conversation_id: conversationId, mode, ...(sessionId ? { session_id: sessionId } : {}) }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("network");
  }
  if (response.status === 404) throw new StreamUnsupported();
  if (!response.ok) throw new ApiError(kindForStatus(response.status));
  if (!response.body) throw new ApiError("upstream");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const parsed = parseSse(done ? `${buffer}\n\n` : buffer);
      buffer = parsed.rest;
      for (const event of parsed.events) {
        if (event.type === "error") throw new ApiError(event.kind);
        onEvent(event);
        if (event.type === "done") return;
      }
      if (done) throw new ApiError("network");
    }
  } catch (error) {
    if (error instanceof ApiError || (error instanceof DOMException && error.name === "AbortError")) throw error;
    throw new ApiError("network");
  } finally {
    void reader.cancel().catch(() => undefined);
  }
}

/** Thrown when the BFF has no warm-up route yet (an older image). */
export class WarmupUnsupported extends Error {}

/** Ask the BFF to wake the agent. Resolves true once the agent answered its probe. */
export interface WarmUp {
  ready: boolean;
  /** A conversation whose Foundry session is already started: continue it to skip the cold start. */
  conversationId?: string;
}

export async function warmUp(signal?: AbortSignal): Promise<WarmUp> {
  let response: Response;
  try {
    response = await request("/api/warmup", { method: "POST", signal });
  } catch (error) {
    if (error instanceof ApiError && error.kind === "unknown" && error.status === 404) throw new WarmupUnsupported();
    throw error;
  }
  const body = (await response.json()) as { ready?: unknown; conversation_id?: unknown };
  const ready = body.ready === true;
  const id = body.conversation_id;
  return ready && typeof id === "string" && /^[A-Za-z0-9_.:-]{1,256}$/.test(id) ? { ready, conversationId: id } : { ready };
}

export interface SpeechToken {
  token: string;
  region: string;
  /** Seconds the token stays valid. */
  expiresIn: number;
}

/** A short-lived Azure Speech token, minted by the BFF with its managed identity. */
export async function getSpeechToken(signal?: AbortSignal): Promise<SpeechToken> {
  const response = await request("/api/speech/token", { method: "POST", signal });
  const body = (await response.json()) as { token?: unknown; region?: unknown; expires_in?: unknown };
  if (typeof body.token !== "string" || !body.token || typeof body.region !== "string" || !/^[a-z0-9]{2,40}$/.test(body.region)) {
    throw new ApiError("invalid");
  }
  const expiresIn = typeof body.expires_in === "number" && body.expires_in > 0 ? body.expires_in : 300;
  return { token: body.token, region: body.region, expiresIn };
}

// ---------------------------------------------------------------- workspace sync
//
// Wire shapes of the owner-only workspace routes. The PWA keeps its own copy in
// localStorage and mirrors it here when the BFF supports it; localStorage stays the
// instant, offline cache. These helpers only move bytes: the decisions live in
// state/remoteSync.ts so they can be tested without a server.

export interface RemoteProject {
  id: string;
  name: string;
  color: string;
  system?: boolean;
  createdAt: number;
}

export interface RemoteSession {
  id: string;
  projectId: string;
  title: string;
  titleEdited?: boolean;
  pinned: boolean;
  updatedAt: number;
  messageCount: number;
  conversationId?: string;
}

export interface RemoteMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  voice?: boolean;
  at: number;
}

const record = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : undefined;
const isText = (value: unknown): value is string => typeof value === "string";
const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function readRemoteProject(raw: unknown): RemoteProject | undefined {
  const p = record(raw);
  if (!p || !isText(p.id) || !p.id || !isText(p.name) || !p.name.trim()) return undefined;
  if (!isNumber(p.createdAt)) return undefined;
  return {
    id: p.id,
    name: p.name,
    color: isText(p.color) ? p.color : "#6c80f2",
    ...(p.system === true ? { system: true } : {}),
    createdAt: p.createdAt,
  };
}

function readRemoteSession(raw: unknown): RemoteSession | undefined {
  const s = record(raw);
  if (!s || !isText(s.id) || !s.id || !isText(s.projectId) || !s.projectId) return undefined;
  if (!isNumber(s.updatedAt)) return undefined;
  return {
    id: s.id,
    projectId: s.projectId,
    title: isText(s.title) && s.title.trim() ? s.title : "New session",
    ...(s.titleEdited === true ? { titleEdited: true } : {}),
    pinned: s.pinned === true,
    updatedAt: s.updatedAt,
    messageCount: isNumber(s.messageCount) && s.messageCount >= 0 ? Math.floor(s.messageCount) : 0,
    ...(isText(s.conversationId) && s.conversationId ? { conversationId: s.conversationId } : {}),
  };
}

function readRemoteMessage(raw: unknown): RemoteMessage | undefined {
  const m = record(raw);
  if (!m || !isText(m.id) || !isText(m.text) || (m.role !== "user" && m.role !== "assistant")) return undefined;
  return {
    id: m.id,
    role: m.role,
    text: m.text,
    ...(m.voice === true ? { voice: true } : {}),
    at: isNumber(m.at) ? m.at : 0,
  };
}

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/**
 * Projects from the BFF, or undefined when the workspace routes are not deployed
 * (404) or unreachable at startup: the PWA then behaves exactly as before.
 */
export async function getRemoteProjects(signal?: AbortSignal): Promise<RemoteProject[] | undefined> {
  try {
    const response = await request("/api/projects", { signal });
    const body: unknown = await response.json();
    if (!Array.isArray(body)) throw new ApiError("upstream");
    return body.flatMap((raw) => {
      const project = readRemoteProject(raw);
      return project ? [project] : [];
    });
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.kind === "network")) return undefined;
    throw error;
  }
}

export async function getRemoteSessions(projectId?: string, signal?: AbortSignal): Promise<RemoteSession[]> {
  const path = projectId ? `/api/sessions?project=${encodeURIComponent(projectId)}` : "/api/sessions";
  const response = await request(path, { signal });
  const body: unknown = await response.json();
  if (!Array.isArray(body)) throw new ApiError("upstream");
  return body.flatMap((raw) => {
    const session = readRemoteSession(raw);
    return session ? [session] : [];
  });
}

export async function getRemoteMessages(sessionId: string, signal?: AbortSignal): Promise<RemoteMessage[]> {
  const response = await request(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, { signal });
  const body: unknown = await response.json();
  if (!Array.isArray(body)) throw new ApiError("upstream");
  return body.flatMap((raw) => {
    const message = readRemoteMessage(raw);
    return message ? [message] : [];
  });
}

export async function createRemoteProject(project: { id: string; name: string; color: string }): Promise<void> {
  await request("/api/projects", jsonInit("POST", project));
}

export async function updateRemoteProject(id: string, change: { name?: string; color?: string }): Promise<void> {
  await request(`/api/projects/${encodeURIComponent(id)}`, jsonInit("PATCH", change));
}

export async function deleteRemoteProject(id: string): Promise<void> {
  await request(`/api/projects/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function createRemoteSession(session: {
  id: string;
  projectId: string;
  title: string;
  pinned?: boolean;
}): Promise<void> {
  await request("/api/sessions", jsonInit("POST", session));
}

export async function updateRemoteSession(
  id: string,
  change: { title?: string; titleEdited?: boolean; pinned?: boolean; projectId?: string },
): Promise<void> {
  await request(`/api/sessions/${encodeURIComponent(id)}`, jsonInit("PATCH", change));
}

export async function deleteRemoteSession(id: string): Promise<void> {
  await request(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** Test hook: how one parsed SSE payload is read. */
export const streamEventFromForTest = toEvent;
