/**
 * The owner's workspace: projects, the sessions (chats) filed in them, and the UI choices that
 * persist. Pure: no DOM, no clock, no random ids. The caller passes both in, so every rule here
 * can be tested. Messages live apart (see workspaceStorage.ts): this holds metadata only.
 */

export const MAIN_ID = "main";
export const COLORS = ["#6c80f2", "#e0699b", "#3cb98a", "#e0a23c", "#4aa3d8", "#a077e8"] as const;
export const NEW_SESSION_TITLE = "New session";
export const TITLE_MAX = 42;
export const PROJECT_NAME_MAX = 40;

export interface Project {
  id: string;
  /** Unique, case-insensitive, at most PROJECT_NAME_MAX characters. */
  name: string;
  color: string;
  /** Main: cannot be deleted. */
  system?: true;
  createdAt: number;
}

export interface Session {
  id: string;
  projectId: string;
  title: string;
  /** Once the owner renames a session, the first message no longer sets its title. */
  titleEdited?: boolean;
  pinned: boolean;
  updatedAt: number;
  /** Finished messages in this session (the rail shows it; storage keeps the last 100 only). */
  messageCount: number;
  /** Foundry id of the agent's last answer, which continues the thread. */
  conversationId?: string;
  /** Unsent text in the composer. */
  draft?: string;
}

/** What is kept of a message: its text, never what the tools did. */
export interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** Said by voice. */
  voice?: boolean;
  at: number;
}

export interface UiState {
  railTab: "sessions" | "projects";
  /** Expanded projects. Undefined means "only the active project". */
  open: Record<string, boolean>;
  /** Technical composer. */
  tech: boolean;
  /** Read answers aloud. */
  speak: boolean;
}

export interface Workspace {
  v: 1;
  projects: Project[];
  sessions: Session[];
  activeProjectId: string;
  activeSessionId: string;
  ui: UiState;
}

/** Clock and ids come from outside so the rules stay deterministic. */
export interface Env {
  now: number;
  id: () => string;
}

export const DEFAULT_UI: UiState = { railTab: "sessions", open: {}, tech: false, speak: true };

// ---------------------------------------------------------------- titles

/** Titles come from the first message, so Markdown markers must not leak into the rail. */
export function plainTitle(text: string): string {
  return text
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_~`#>]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** The automatic title of a session, or undefined when the text has nothing to title it with. */
export function autoTitle(text: string): string | undefined {
  const plain = plainTitle(text);
  if (!plain) return undefined;
  return plain.length > TITLE_MAX ? `${plain.slice(0, TITLE_MAX - 1)}…` : plain;
}

// ---------------------------------------------------------------- queries

export function sessionsOf(workspace: Workspace, projectId: string): Session[] {
  return workspace.sessions.filter((s) => s.projectId === projectId).sort((a, b) => b.updatedAt - a.updatedAt);
}

export function findSession(workspace: Workspace, id: string): Session | undefined {
  return workspace.sessions.find((s) => s.id === id);
}

export function findProject(workspace: Workspace, id: string): Project | undefined {
  return workspace.projects.find((p) => p.id === id);
}

/** Whether a project's node is expanded: the owner's choice, else only the active project. */
export function isOpen(workspace: Workspace, projectId: string): boolean {
  return workspace.ui.open[projectId] ?? projectId === workspace.activeProjectId;
}

export type NameCheck = { ok: true; name: string } | { ok: false; error: string };

/** A project name as it would be stored, or why it cannot be. `exceptId` is the project being renamed. */
export function checkProjectName(workspace: Workspace, raw: string, exceptId?: string): NameCheck {
  const name = raw.replace(/\s+/g, " ").trim();
  if (!name) return { ok: false, error: "Give the project a name" };
  if (name.length > PROJECT_NAME_MAX) return { ok: false, error: `A project name has at most ${PROJECT_NAME_MAX} characters` };
  const clash = workspace.projects.some((p) => p.id !== exceptId && p.name.toLowerCase() === name.toLowerCase());
  if (clash) return { ok: false, error: `A project named “${name}” already exists` };
  return { ok: true, name };
}

// ---------------------------------------------------------------- construction

function emptySession(projectId: string, env: Env): Session {
  return { id: env.id(), projectId, title: NEW_SESSION_TITLE, pinned: false, updatedAt: env.now, messageCount: 0 };
}

export function createWorkspace(env: Env): Workspace {
  const main: Project = { id: MAIN_ID, name: "Main", color: COLORS[0], system: true, createdAt: env.now };
  const session = emptySession(MAIN_ID, env);
  return { v: 1, projects: [main], sessions: [session], activeProjectId: MAIN_ID, activeSessionId: session.id, ui: { ...DEFAULT_UI, open: {} } };
}

/**
 * Makes any workspace valid: Main exists, every session sits in a real project, the active project
 * and session exist and agree. Used after loading, and after every change that could break them.
 */
export function normalize(input: Workspace, env: Env): Workspace {
  let projects = input.projects;
  if (!projects.some((p) => p.id === MAIN_ID)) {
    projects = [{ id: MAIN_ID, name: "Main", color: COLORS[0], system: true, createdAt: env.now }, ...projects];
  }
  const known = new Set(projects.map((p) => p.id));
  let sessions = input.sessions.map((s) => (known.has(s.projectId) ? s : { ...s, projectId: MAIN_ID }));
  const draft: Workspace = { ...input, projects, sessions };

  const active = findSession(draft, draft.activeSessionId);
  if (active) return { ...draft, activeProjectId: active.projectId };

  const projectId = known.has(draft.activeProjectId) ? draft.activeProjectId : MAIN_ID;
  const newest = sessionsOf(draft, projectId)[0];
  if (newest) return { ...draft, activeProjectId: projectId, activeSessionId: newest.id };
  const created = emptySession(projectId, env);
  sessions = [created, ...sessions];
  return { ...draft, sessions, activeProjectId: projectId, activeSessionId: created.id };
}

// ---------------------------------------------------------------- actions

export type Action =
  | { type: "newSession"; projectId?: string }
  | { type: "openSession"; id: string }
  | { type: "selectProject"; id: string }
  | { type: "renameSession"; id: string; title: string }
  | { type: "pinSession"; id: string; pinned: boolean }
  | { type: "moveSession"; id: string; projectId: string }
  | { type: "deleteSession"; id: string }
  | { type: "restoreSession"; session: Session; active: boolean }
  | { type: "turn"; sessionId: string; role: "user" | "assistant"; text: string }
  | { type: "setConversation"; sessionId: string; conversationId: string | undefined }
  | { type: "setDraft"; sessionId: string; draft: string }
  | { type: "createProject"; name: string; color: string }
  | { type: "renameProject"; id: string; name: string }
  | { type: "deleteProject"; id: string }
  | { type: "restoreProject"; project: Project; sessions: Session[]; activeSessionId?: string }
  | { type: "setUi"; change: Partial<Omit<UiState, "open">> }
  | { type: "setOpen"; projectId: string; open: boolean }
  | { type: "hydrate"; projects: Project[]; sessions: Session[] };

function patchSession(workspace: Workspace, id: string, change: (s: Session) => Session): Workspace {
  const index = workspace.sessions.findIndex((s) => s.id === id);
  if (index === -1) return workspace;
  const sessions = workspace.sessions.slice();
  sessions[index] = change(sessions[index]);
  return { ...workspace, sessions };
}

/** Make a project the active one, opening its newest session (or starting one if it has none). */
function activate(workspace: Workspace, projectId: string, env: Env): Workspace {
  const current = findSession(workspace, workspace.activeSessionId);
  if (current?.projectId === projectId) return { ...workspace, activeProjectId: projectId };
  const newest = sessionsOf(workspace, projectId)[0];
  if (newest) return { ...workspace, activeProjectId: projectId, activeSessionId: newest.id };
  const created = emptySession(projectId, env);
  return { ...workspace, sessions: [created, ...workspace.sessions], activeProjectId: projectId, activeSessionId: created.id };
}

export function reduce(workspace: Workspace, action: Action, env: Env): Workspace {
  switch (action.type) {
    case "newSession": {
      const projectId = findProject(workspace, action.projectId ?? workspace.activeProjectId) ? (action.projectId ?? workspace.activeProjectId) : MAIN_ID;
      // An untouched "New session" is reused instead of piling up empty ones.
      const empty = workspace.sessions.find((s) => s.projectId === projectId && s.messageCount === 0);
      if (empty) return { ...workspace, activeProjectId: projectId, activeSessionId: empty.id };
      const created = emptySession(projectId, env);
      return { ...workspace, sessions: [created, ...workspace.sessions], activeProjectId: projectId, activeSessionId: created.id };
    }
    case "openSession": {
      const session = findSession(workspace, action.id);
      if (!session) return workspace;
      return { ...workspace, activeSessionId: session.id, activeProjectId: session.projectId };
    }
    case "selectProject":
      return findProject(workspace, action.id) ? activate(workspace, action.id, env) : workspace;
    case "renameSession": {
      const title = plainTitle(action.title).slice(0, TITLE_MAX * 2);
      if (!title) return workspace;
      return patchSession(workspace, action.id, (s) => ({ ...s, title, titleEdited: true }));
    }
    case "pinSession":
      return patchSession(workspace, action.id, (s) => ({ ...s, pinned: action.pinned }));
    case "moveSession": {
      if (!findProject(workspace, action.projectId)) return workspace;
      const moved = patchSession(workspace, action.id, (s) => ({ ...s, projectId: action.projectId }));
      return action.id === workspace.activeSessionId ? { ...moved, activeProjectId: action.projectId } : moved;
    }
    case "deleteSession": {
      const session = findSession(workspace, action.id);
      if (!session) return workspace;
      const rest: Workspace = { ...workspace, sessions: workspace.sessions.filter((s) => s.id !== action.id) };
      if (action.id !== workspace.activeSessionId) return rest;
      const newest = sessionsOf(rest, session.projectId)[0];
      if (newest) return { ...rest, activeProjectId: session.projectId, activeSessionId: newest.id };
      const created = emptySession(session.projectId, env);
      return { ...rest, sessions: [created, ...rest.sessions], activeProjectId: session.projectId, activeSessionId: created.id };
    }
    case "restoreSession": {
      if (findSession(workspace, action.session.id) || !findProject(workspace, action.session.projectId)) return workspace;
      const restored = { ...workspace, sessions: [action.session, ...workspace.sessions] };
      return action.active ? { ...restored, activeSessionId: action.session.id, activeProjectId: action.session.projectId } : restored;
    }
    case "turn":
      return patchSession(workspace, action.sessionId, (s) => {
        const first = s.messageCount === 0 && action.role === "user";
        const title = first && !s.titleEdited ? (autoTitle(action.text) ?? s.title) : s.title;
        return { ...s, title, messageCount: s.messageCount + 1, updatedAt: env.now };
      });
    case "setConversation":
      if (findSession(workspace, action.sessionId)?.conversationId === action.conversationId) return workspace;
      return patchSession(workspace, action.sessionId, (s) => {
        if (action.conversationId) return { ...s, conversationId: action.conversationId };
        const { conversationId: _forgotten, ...rest } = s;
        return rest;
      });
    case "setDraft":
      if ((findSession(workspace, action.sessionId)?.draft ?? "") === action.draft) return workspace;
      return patchSession(workspace, action.sessionId, (s) => {
        if (action.draft) return { ...s, draft: action.draft };
        const { draft: _draft, ...rest } = s;
        return rest;
      });
    case "createProject": {
      const checked = checkProjectName(workspace, action.name);
      if (!checked.ok) return workspace;
      const color = (COLORS as readonly string[]).includes(action.color) ? action.color : COLORS[workspace.projects.length % COLORS.length];
      const project: Project = { id: env.id(), name: checked.name, color, createdAt: env.now };
      const session = emptySession(project.id, env);
      return {
        ...workspace,
        projects: [...workspace.projects, project],
        sessions: [session, ...workspace.sessions],
        activeProjectId: project.id,
        activeSessionId: session.id,
      };
    }
    case "renameProject": {
      const checked = checkProjectName(workspace, action.name, action.id);
      if (!checked.ok || !findProject(workspace, action.id)) return workspace;
      const name = checked.name;
      return { ...workspace, projects: workspace.projects.map((p) => (p.id === action.id ? { ...p, name } : p)) };
    }
    case "deleteProject": {
      const project = findProject(workspace, action.id);
      if (!project || project.system) return workspace;
      const rest: Workspace = {
        ...workspace,
        projects: workspace.projects.filter((p) => p.id !== action.id),
        sessions: workspace.sessions.filter((s) => s.projectId !== action.id),
        ui: { ...workspace.ui, open: Object.fromEntries(Object.entries(workspace.ui.open).filter(([id]) => id !== action.id)) },
      };
      const stillActive = findSession(rest, workspace.activeSessionId);
      return stillActive ? { ...rest, activeProjectId: stillActive.projectId } : activate({ ...rest, activeSessionId: "" }, MAIN_ID, env);
    }
    case "restoreProject": {
      if (findProject(workspace, action.project.id)) return workspace;
      const restored: Workspace = {
        ...workspace,
        projects: [...workspace.projects, action.project],
        sessions: [...action.sessions, ...workspace.sessions],
      };
      const wanted = action.activeSessionId && action.sessions.some((s) => s.id === action.activeSessionId);
      return wanted ? { ...restored, activeSessionId: action.activeSessionId as string, activeProjectId: action.project.id } : restored;
    }
    case "hydrate": {
      // The server is authoritative for projects and sessions, but the owner's UI choices
      // and caches stay local. Without migration, old local-only sessions simply disappear
      // from the rail and remain untouched in localStorage.
      const draft: Workspace = { ...workspace, projects: action.projects, sessions: action.sessions };
      const active = findSession(draft, workspace.activeSessionId);
      if (active) return normalize({ ...draft, activeProjectId: active.projectId }, env);
      const newest = sessionsOf(draft, MAIN_ID)[0];
      if (newest) return normalize({ ...draft, activeProjectId: MAIN_ID, activeSessionId: newest.id }, env);
      const created = emptySession(MAIN_ID, env);
      return normalize(
        { ...draft, sessions: [created, ...draft.sessions], activeProjectId: MAIN_ID, activeSessionId: created.id },
        env,
      );
    }
    case "setUi":
      return { ...workspace, ui: { ...workspace.ui, ...action.change } };
    case "setOpen":
      return { ...workspace, ui: { ...workspace.ui, open: { ...workspace.ui.open, [action.projectId]: action.open } } };
  }
}
