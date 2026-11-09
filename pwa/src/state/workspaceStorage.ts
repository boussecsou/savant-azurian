import { loadChat } from "../chat";
import {
  COLORS,
  DEFAULT_UI,
  MAIN_ID,
  autoTitle,
  createWorkspace,
  normalize,
  type Env,
  type Project,
  type Session,
  type StoredMessage,
  type UiState,
  type Workspace,
} from "./workspace";

/**
 * Where the workspace lives. The UI only knows this interface, so the browser store below can be
 * replaced by the BFF (Cosmos DB, task 39) without touching a component. Nothing here ever throws:
 * storage can be missing, blocked or full, and the app must keep working without it.
 */
export interface SessionStore {
  loadWorkspace(env?: Env): Workspace;
  saveWorkspace(workspace: Workspace): void;
  loadMessages(sessionId: string): StoredMessage[];
  saveMessages(sessionId: string, messages: readonly StoredMessage[]): void;
  deleteSession(sessionId: string): void;
}

export const WORKSPACE_KEY = "sa2-workspace-v1";
export const MESSAGES_PREFIX = "sa2-msgs-";
/** The single conversation of the first version of the app. */
export const LEGACY_CHAT_KEY = "sa2-chat-v1";
export const MAX_STORED_MESSAGES = 100;

type Backing = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function browserStorage(): Backing | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

const string = (value: unknown): value is string => typeof value === "string";
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function readProject(raw: unknown, now: number): Project | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const p = raw as Record<string, unknown>;
  if (!string(p.id) || !string(p.name) || !p.id || !p.name.trim()) return undefined;
  const system = p.id === MAIN_ID;
  return {
    id: p.id,
    name: p.name,
    color: string(p.color) && (COLORS as readonly string[]).includes(p.color) ? p.color : COLORS[0],
    ...(system ? { system: true as const } : {}),
    createdAt: finite(p.createdAt) ? p.createdAt : now,
  };
}

function readSession(raw: unknown, now: number): Session | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const s = raw as Record<string, unknown>;
  if (!string(s.id) || !s.id || !string(s.projectId)) return undefined;
  return {
    id: s.id,
    projectId: s.projectId,
    title: string(s.title) && s.title.trim() ? s.title : "New session",
    ...(s.titleEdited === true ? { titleEdited: true } : {}),
    pinned: s.pinned === true,
    updatedAt: finite(s.updatedAt) ? s.updatedAt : now,
    messageCount: finite(s.messageCount) && s.messageCount >= 0 ? Math.floor(s.messageCount) : 0,
    ...(string(s.conversationId) && s.conversationId ? { conversationId: s.conversationId } : {}),
    ...(string(s.draft) && s.draft ? { draft: s.draft } : {}),
  };
}

function readUi(raw: unknown): UiState {
  const u = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const open: Record<string, boolean> = {};
  if (u.open && typeof u.open === "object") {
    for (const [id, value] of Object.entries(u.open as Record<string, unknown>)) if (typeof value === "boolean") open[id] = value;
  }
  return {
    railTab: u.railTab === "projects" ? "projects" : DEFAULT_UI.railTab,
    open,
    tech: u.tech === true,
    speak: typeof u.speak === "boolean" ? u.speak : DEFAULT_UI.speak,
  };
}

/** Rebuild a workspace from stored JSON, dropping what is malformed and repairing what is inconsistent. */
export function parseWorkspace(json: string, env: Env): Workspace | undefined {
  let data: unknown;
  try {
    data = JSON.parse(json);
  } catch {
    return undefined;
  }
  if (!data || typeof data !== "object") return undefined;
  const w = data as Record<string, unknown>;
  if (w.v !== 1 || !Array.isArray(w.projects) || !Array.isArray(w.sessions)) return undefined;
  const seen = new Set<string>();
  const projects = w.projects.flatMap((p) => {
    const project = readProject(p, env.now);
    if (!project || seen.has(project.id)) return [];
    seen.add(project.id);
    return [project];
  });
  const ids = new Set<string>();
  const sessions = w.sessions.flatMap((s) => {
    const session = readSession(s, env.now);
    if (!session || ids.has(session.id)) return [];
    ids.add(session.id);
    return [session];
  });
  return normalize(
    {
      v: 1,
      projects,
      sessions,
      activeProjectId: string(w.activeProjectId) ? w.activeProjectId : MAIN_ID,
      activeSessionId: string(w.activeSessionId) ? w.activeSessionId : "",
      ui: readUi(w.ui),
    },
    env,
  );
}

function parseMessages(json: string): StoredMessage[] {
  try {
    const data: unknown = JSON.parse(json);
    if (!Array.isArray(data)) return [];
    return data
      .flatMap((m): StoredMessage[] => {
        if (!m || typeof m !== "object") return [];
        const r = m as Record<string, unknown>;
        if (!string(r.id) || !string(r.text) || (r.role !== "user" && r.role !== "assistant")) return [];
        return [{ id: r.id, role: r.role, text: r.text, ...(r.voice === true ? { voice: true } : {}), at: finite(r.at) ? r.at : 0 }];
      })
      .slice(-MAX_STORED_MESSAGES);
  } catch {
    return [];
  }
}

export function createBrowserStore(storage: Backing | undefined = browserStorage(), defaultEnv?: () => Env): SessionStore {
  const envNow = (): Env => defaultEnv?.() ?? { now: Date.now(), id: () => crypto.randomUUID() };

  const write = (key: string, value: string): boolean => {
    try {
      storage?.setItem(key, value);
      return storage !== undefined;
    } catch {
      // Quota exceeded or blocked: this part is simply not remembered.
      return false;
    }
  };
  const read = (key: string): string | null => {
    try {
      return storage?.getItem(key) ?? null;
    } catch {
      return null;
    }
  };
  const remove = (key: string) => {
    try {
      storage?.removeItem(key);
    } catch {
      // Nothing to do: the key stays and is overwritten next time.
    }
  };

  /** The one-conversation app becomes a session of Main. The old key goes only once the new data is safely written. */
  const migrateLegacy = (env: Env): Workspace | undefined => {
    const legacy = loadChat(storage);
    if (!legacy.messages.length && !legacy.conversationId) return undefined;
    const workspace = createWorkspace(env);
    const first = legacy.messages.find((m) => m.role === "user");
    const base = workspace.sessions[0];
    const session: Session = {
      ...base,
      title: (first && autoTitle(first.text)) || "Imported conversation",
      messageCount: legacy.messages.length,
      ...(legacy.conversationId ? { conversationId: legacy.conversationId } : {}),
    };
    const migrated: Workspace = { ...workspace, sessions: [session] };
    const stored: StoredMessage[] = legacy.messages.map((m, index) => ({ id: m.id, role: m.role, text: m.text, at: env.now - (legacy.messages.length - index) }));
    if (write(MESSAGES_PREFIX + session.id, JSON.stringify(stored)) && write(WORKSPACE_KEY, JSON.stringify(migrated))) remove(LEGACY_CHAT_KEY);
    return migrated;
  };

  return {
    loadWorkspace(env = envNow()) {
      const json = read(WORKSPACE_KEY);
      const stored = json ? parseWorkspace(json, env) : undefined;
      return stored ?? (json ? undefined : migrateLegacy(env)) ?? createWorkspace(env);
    },
    saveWorkspace(workspace) {
      write(WORKSPACE_KEY, JSON.stringify(workspace));
    },
    loadMessages(sessionId) {
      const json = read(MESSAGES_PREFIX + sessionId);
      return json ? parseMessages(json) : [];
    },
    saveMessages(sessionId, messages) {
      // Text only: tool steps and animation flags describe a live turn, not stored history.
      const clean = messages.slice(-MAX_STORED_MESSAGES).map((m) => ({ id: m.id, role: m.role, text: m.text, ...(m.voice ? { voice: true } : {}), at: m.at }));
      write(MESSAGES_PREFIX + sessionId, JSON.stringify(clean));
    },
    deleteSession(sessionId) {
      remove(MESSAGES_PREFIX + sessionId);
    },
  };
}
