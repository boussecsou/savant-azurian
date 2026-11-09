import type { ApiErrorKind } from "./api";
import type { Source } from "./sources";
import type { StoredMessage } from "./state/workspace";

/** One tool call of the agent, as the stream reported it. Never persisted. */
export interface ToolStep {
  id: string;
  name: string;
  status: "running" | "done";
  /** Time between the call and its result, measured in the browser. */
  ms?: number;
}

/** Durations of a voice turn, measured in the browser. A missing part was not measured. */
export interface Trace {
  stt?: number;
  agent?: number;
  tts?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** Said or answered by voice. */
  voice?: boolean;
  /** When it was written (ms since the epoch). */
  at?: number;
  /** Set on a local, non-persisted notice shown when a request failed. */
  error?: ApiErrorKind;
  /** Tool calls of this turn, shown above the answer while and after it is written. */
  tools?: ToolStep[];
  /** Still being written by the agent. */
  streaming?: boolean;
  /** Received during this session: its text is revealed with an animation. Reloaded ones are not. */
  live?: boolean;
  /** Speech-to-text, agent and text-to-speech times of a voice turn (this page only). */
  trace?: Trace;
  /** Documents of the project this answer used (search_documents), this page only. */
  sources?: Source[];
}

/** What a session keeps of a message: text, channel and date, never what the tools did. */
export function toStored(message: ChatMessage, fallbackAt: number): StoredMessage {
  return { id: message.id, role: message.role, text: message.text, ...(message.voice ? { voice: true } : {}), at: message.at ?? fallbackAt };
}

export function fromStored(message: StoredMessage): ChatMessage {
  return { id: message.id, role: message.role, text: message.text, ...(message.voice ? { voice: true } : {}), at: message.at };
}

/** The single conversation of the first version of the app, before sessions existed. */
export interface LegacyChat {
  messages: { id: string; role: "user" | "assistant"; text: string }[];
  conversationId?: string;
}

const LEGACY_KEY = "sa2-chat-v1";
const MAX_MESSAGES = 100;

/**
 * Reads the old one-conversation storage so it can be migrated into a session.
 * Storage can be missing or blocked (private windows, cleared site data): never rely on it.
 */
export function loadChat(storage: Pick<Storage, "getItem"> | undefined = safeStorage()): LegacyChat {
  try {
    const raw = storage?.getItem(LEGACY_KEY);
    if (!raw) return { messages: [] };
    const data = JSON.parse(raw) as { messages?: unknown; conversationId?: unknown };
    const messages = Array.isArray(data.messages)
      ? data.messages
          .filter(
            (m): m is ChatMessage =>
              !!m && (m.role === "user" || m.role === "assistant") && typeof m.text === "string" && typeof m.id === "string" && !m.error,
          )
          .map(({ id, role, text }) => ({ id, role, text }))
      : [];
    return {
      messages: messages.slice(-MAX_MESSAGES),
      conversationId: typeof data.conversationId === "string" ? data.conversationId : undefined,
    };
  } catch {
    return { messages: [] };
  }
}

function safeStorage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function newId(): string {
  return crypto.randomUUID();
}
