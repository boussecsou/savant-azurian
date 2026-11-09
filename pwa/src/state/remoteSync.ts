import type { RemoteMessage, RemoteProject, RemoteSession } from "../api";
import {
  COLORS,
  MAIN_ID,
  NEW_SESSION_TITLE,
  type Project,
  type Session,
  type StoredMessage,
  type Workspace,
} from "./workspace";

/**
 * Mapping and diff rules for the write-behind copy of the workspace kept by the BFF.
 *
 * Everything here is pure: localStorage stays the instant, offline source of truth and
 * this module only says what the server is missing. That keeps the network out of the
 * reducer and makes the tricky cases (empty sessions, deletes during Undo) testable.
 */

// ---------------------------------------------------------------- wire -> workspace

function colorOf(value: string): string {
  return (COLORS as readonly string[]).includes(value) ? value : COLORS[0];
}

/** Server projects as workspace projects, dropping duplicates and repairing unknown colours. */
export function toProjects(remote: readonly RemoteProject[]): Project[] {
  const seen = new Set<string>();
  return remote.flatMap((project) => {
    if (seen.has(project.id)) return [];
    seen.add(project.id);
    return [
      {
        id: project.id,
        name: project.name.trim() || "Untitled",
        color: colorOf(project.color),
        ...(project.id === MAIN_ID ? { system: true as const } : {}),
        createdAt: project.createdAt,
      },
    ];
  });
}

/** Server sessions as workspace sessions. The server is authoritative for metadata. */
export function toSessions(remote: readonly RemoteSession[]): Session[] {
  const seen = new Set<string>();
  return remote.flatMap((session) => {
    if (seen.has(session.id)) return [];
    seen.add(session.id);
    return [
      {
        id: session.id,
        projectId: session.projectId,
        title: session.title.trim() || NEW_SESSION_TITLE,
        ...(session.titleEdited === true ? { titleEdited: true } : {}),
        pinned: session.pinned === true,
        updatedAt: session.updatedAt,
        messageCount: Math.max(0, Math.floor(session.messageCount)),
        ...(session.conversationId ? { conversationId: session.conversationId } : {}),
      },
    ];
  });
}

/** Loaded history is cached locally like any other message: text, channel and date only. */
export function toStoredMessages(remote: readonly RemoteMessage[]): StoredMessage[] {
  return remote.map((message) => ({
    id: message.id,
    role: message.role,
    text: message.text,
    ...(message.voice === true ? { voice: true } : {}),
    at: message.at,
  }));
}

// ---------------------------------------------------------------- snapshot

/** Fields the server knows about a project. Anything else (createdAt, system) never changes. */
export interface ProjectState {
  name: string;
  color: string;
}

/** Fields the server knows about a session. Messages are written by the BFF, not by us. */
export interface SessionState {
  projectId: string;
  title: string;
  titleEdited: boolean;
  pinned: boolean;
}

/** What the server is believed to hold. Failed calls are simply still missing from it. */
export interface SyncSnapshot {
  projects: Record<string, ProjectState>;
  sessions: Record<string, SessionState>;
}

export function emptySnapshot(): SyncSnapshot {
  return { projects: {}, sessions: {} };
}

export function snapshotFromServer(projects: readonly Project[], sessions: readonly Session[]): SyncSnapshot {
  const snapshot = emptySnapshot();
  for (const project of projects) snapshot.projects[project.id] = { name: project.name, color: project.color };
  for (const session of sessions) snapshot.sessions[session.id] = sessionState(session);
  return snapshot;
}

function sessionState(session: Session): SessionState {
  return {
    projectId: session.projectId,
    title: session.title,
    titleEdited: session.titleEdited === true,
    pinned: session.pinned,
  };
}

// ---------------------------------------------------------------- diff

export interface ProjectUpdate {
  id: string;
  name?: string;
  color?: string;
}

export interface SessionUpdate {
  id: string;
  title?: string;
  titleEdited?: boolean;
  pinned?: boolean;
  projectId?: string;
}

/** Ordered work for one flush: parents before children, so sessions always find their project. */
export interface SyncPlan {
  createProjects: Project[];
  updateProjects: ProjectUpdate[];
  createSessions: Session[];
  updateSessions: SessionUpdate[];
}

export function isEmptyPlan(plan: SyncPlan): boolean {
  return (
    plan.createProjects.length === 0 &&
    plan.updateProjects.length === 0 &&
    plan.createSessions.length === 0 &&
    plan.updateSessions.length === 0
  );
}

/**
 * Compare the local workspace with what the server already holds.
 *
 * An untouched session (messageCount 0) is never created here: it only reaches the
 * server through ensureSession, once a chat needs a session_id. Deletions are not
 * part of the plan either; they happen at discard, after the Undo window.
 */
export function planSync(workspace: Workspace, snapshot: SyncSnapshot): SyncPlan {
  const plan: SyncPlan = { createProjects: [], updateProjects: [], createSessions: [], updateSessions: [] };

  for (const project of workspace.projects) {
    const known = snapshot.projects[project.id];
    if (!known) {
      plan.createProjects.push(project);
      continue;
    }
    const update: ProjectUpdate = { id: project.id };
    if (known.name !== project.name) update.name = project.name;
    if (known.color !== project.color) update.color = project.color;
    if (update.name !== undefined || update.color !== undefined) plan.updateProjects.push(update);
  }

  for (const session of workspace.sessions) {
    const known = snapshot.sessions[session.id];
    if (!known) {
      // An empty session stays local until the owner sends something in it.
      if (session.messageCount === 0) continue;
      plan.createSessions.push(session);
      continue;
    }
    const update: SessionUpdate = { id: session.id };
    if (known.title !== session.title) update.title = session.title;
    if (known.titleEdited !== (session.titleEdited === true)) update.titleEdited = session.titleEdited === true;
    if (known.pinned !== session.pinned) update.pinned = session.pinned;
    if (known.projectId !== session.projectId) update.projectId = session.projectId;
    if (
      update.title !== undefined ||
      update.titleEdited !== undefined ||
      update.pinned !== undefined ||
      update.projectId !== undefined
    ) {
      plan.updateSessions.push(update);
    }
  }

  return plan;
}

// ---------------------------------------------------------------- accepted writes

export function markProjectSynced(
  snapshot: SyncSnapshot,
  project: Pick<Project, "id" | "name" | "color">,
): SyncSnapshot {
  return {
    ...snapshot,
    projects: { ...snapshot.projects, [project.id]: { name: project.name, color: project.color } },
  };
}

export function markSessionSynced(snapshot: SyncSnapshot, session: Session): SyncSnapshot {
  return {
    ...snapshot,
    sessions: { ...snapshot.sessions, [session.id]: sessionState(session) },
  };
}

export function applyProjectChanges(snapshot: SyncSnapshot, id: string, change: ProjectUpdate): SyncSnapshot {
  const known = snapshot.projects[id];
  if (!known) return snapshot;
  return {
    ...snapshot,
    projects: {
      ...snapshot.projects,
      [id]: {
        name: change.name ?? known.name,
        color: change.color ?? known.color,
      },
    },
  };
}

export function applySessionChanges(snapshot: SyncSnapshot, id: string, change: SessionUpdate): SyncSnapshot {
  const known = snapshot.sessions[id];
  if (!known) return snapshot;
  return {
    ...snapshot,
    sessions: {
      ...snapshot.sessions,
      [id]: {
        projectId: change.projectId ?? known.projectId,
        title: change.title ?? known.title,
        titleEdited: change.titleEdited ?? known.titleEdited,
        pinned: change.pinned ?? known.pinned,
      },
    },
  };
}

// ---------------------------------------------------------------- discards

/** Called once the Undo window is over: the server may now forget this session. */
export function wasSessionSynced(snapshot: SyncSnapshot, id: string): boolean {
  return snapshot.sessions[id] !== undefined;
}

/** Called once the Undo window is over: the server may now forget this project and its sessions. */
export function wasProjectSynced(snapshot: SyncSnapshot, id: string): boolean {
  return snapshot.projects[id] !== undefined;
}

export function forgetSession(snapshot: SyncSnapshot, id: string): SyncSnapshot {
  if (!snapshot.sessions[id]) return snapshot;
  const { [id]: _gone, ...sessions } = snapshot.sessions;
  return { ...snapshot, sessions };
}

export function forgetProject(snapshot: SyncSnapshot, id: string): SyncSnapshot {
  if (!snapshot.projects[id] && !Object.values(snapshot.sessions).some((s) => s.projectId === id)) return snapshot;
  const { [id]: _project, ...projects } = snapshot.projects;
  const sessions = Object.fromEntries(Object.entries(snapshot.sessions).filter(([, session]) => session.projectId !== id));
  return { projects, sessions };
}
