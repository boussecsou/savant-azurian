import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createRemoteProject,
  createRemoteSession,
  deleteRemoteProject,
  deleteRemoteSession,
  getRemoteMessages,
  getRemoteProjects,
  getRemoteSessions,
  updateRemoteProject,
  updateRemoteSession,
} from "../api";
import { fromStored, newId, toStored, type ChatMessage } from "../chat";
import {
  applyProjectChanges,
  applySessionChanges,
  emptySnapshot,
  forgetProject,
  forgetSession,
  isEmptyPlan,
  markProjectSynced,
  markSessionSynced,
  planSync,
  snapshotFromServer,
  toProjects,
  toSessions,
  toStoredMessages,
  wasProjectSynced,
  wasSessionSynced,
  type SyncSnapshot,
} from "./remoteSync";
import { createBrowserStore, type SessionStore } from "./workspaceStorage";
import { findProject, findSession, reduce, type Action, type Env, type Workspace } from "./workspace";

const SAVE_DELAY_MS = 250;
/** The UI never waits for the network: changes reach the server after a short pause. */
const SYNC_DELAY_MS = 400;

type Updater = ChatMessage[] | ((previous: ChatMessage[]) => ChatMessage[]);

const env = (): Env => ({ now: Date.now(), id: newId });

/**
 * The workspace and the messages of the sessions the owner has opened. The reducer holds every rule;
 * this hook only keeps the latest state readable from callbacks (`workspaceRef`), loads messages
 * when a session is first shown, and writes both back after a short pause. Storage goes through a
 * SessionStore so the browser copy can later be replaced by the BFF.
 *
 * On top of that, when the BFF exposes the workspace routes, the same state is mirrored to it
 * write-behind: localStorage stays the instant, offline copy while projects and session metadata
 * catch up in the background. A sync failure never blocks the UI; the next change retries it.
 */
export function useWorkspace(store: SessionStore) {
  const [workspace, setWorkspace] = useState<Workspace>(() => store.loadWorkspace());
  const workspaceRef = useRef(workspace);
  const [chats, setChats] = useState<Record<string, ChatMessage[]>>(() => ({
    [workspace.activeSessionId]: store.loadMessages(workspace.activeSessionId).map(fromStored),
  }));
  const chatsRef = useRef(chats);

  // Server mirror. `snapshot` is what the server is believed to hold; a failed call simply
  // stays absent from it and is therefore sent again on the next flush.
  const syncEnabled = useRef(false);
  const syncStarted = useRef(false);
  // False until the first read of the server's copy has finished, well or not (see boot.ts).
  const [synced, setSynced] = useState(false);
  const snapshot = useRef<SyncSnapshot>(emptySnapshot());
  const pending = useRef({ projects: new Set<string>(), sessions: new Set<string>() });
  const messagesLoaded = useRef(new Set<string>());
  // One network write at a time keeps `snapshot` coherent when a chat and a flush overlap.
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  const serial = useCallback(<T>(task: () => Promise<T>): Promise<T> => {
    const run = queue.current.then(task, task);
    queue.current = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  }, []);

  // The reference to the latest state is updated first, so two actions in one tick see each other.
  const dispatch = useCallback((action: Action) => {
    const next = reduce(workspaceRef.current, action, env());
    workspaceRef.current = next;
    setWorkspace(next);
  }, []);

  const setMessages = useCallback((sessionId: string, update: Updater) => {
    const previous = chatsRef.current[sessionId] ?? [];
    const next = typeof update === "function" ? update(previous) : update;
    chatsRef.current = { ...chatsRef.current, [sessionId]: next };
    setChats(chatsRef.current);
  }, []);

  const messagesOf = useCallback(
    (sessionId: string): ChatMessage[] => chatsRef.current[sessionId] ?? store.loadMessages(sessionId).map(fromStored),
    [store],
  );

  /** The server's history wins when it holds more messages than the local cache. */
  const reconcileMessages = useCallback(
    async (sessionId: string) => {
      if (!syncEnabled.current || messagesLoaded.current.has(sessionId)) return;
      const session = findSession(workspaceRef.current, sessionId);
      if (!session) return;
      const cached = chatsRef.current[sessionId] ?? store.loadMessages(sessionId).map(fromStored);
      const cachedCount = cached.filter((message) => !message.error).length;
      messagesLoaded.current.add(sessionId);
      if (session.messageCount <= cachedCount) return;
      try {
        const remote = await getRemoteMessages(sessionId);
        setMessages(sessionId, toStoredMessages(remote).map(fromStored));
      } catch {
        // Keep the cache and try again the next time this session is opened.
        messagesLoaded.current.delete(sessionId);
      }
    },
    [setMessages, store],
  );

  /** Forget a session's messages for good (after its Undo window), then drop it server-side. */
  const discard = useCallback(
    (sessionId: string) => {
      store.deleteSession(sessionId);
      const { [sessionId]: _gone, ...rest } = chatsRef.current;
      chatsRef.current = rest;
      setChats(rest);
      messagesLoaded.current.delete(sessionId);

      if (!syncEnabled.current || !wasSessionSynced(snapshot.current, sessionId)) return;
      void serial(async () => {
        try {
          await deleteRemoteSession(sessionId);
          pending.current.sessions.delete(sessionId);
          snapshot.current = forgetSession(snapshot.current, sessionId);
        } catch {
          pending.current.sessions.add(sessionId);
        }
      });
    },
    [serial, store],
  );

  /** Same Undo window for a project: the server cascades its sessions, so they are not deleted one by one. */
  const discardProject = useCallback(
    (projectId: string, sessionIds: readonly string[]) => {
      for (const id of sessionIds) {
        store.deleteSession(id);
        messagesLoaded.current.delete(id);
      }
      const remaining = { ...chatsRef.current };
      for (const id of sessionIds) delete remaining[id];
      chatsRef.current = remaining;
      setChats(remaining);

      if (!syncEnabled.current) return;
      if (!wasProjectSynced(snapshot.current, projectId)) {
        for (const id of sessionIds) {
          if (!wasSessionSynced(snapshot.current, id)) continue;
          void serial(async () => {
            try {
              await deleteRemoteSession(id);
              snapshot.current = forgetSession(snapshot.current, id);
            } catch {
              pending.current.sessions.add(id);
            }
          });
        }
        return;
      }
      void serial(async () => {
        try {
          await deleteRemoteProject(projectId);
          pending.current.projects.delete(projectId);
          for (const id of sessionIds) pending.current.sessions.delete(id);
          snapshot.current = forgetProject(snapshot.current, projectId);
        } catch {
          pending.current.projects.add(projectId);
        }
      });
    },
    [serial, store],
  );

  /** Send what the server is missing, oldest debts first (failed deletes, then creates, then updates). */
  const flush = useCallback(
    () =>
      serial(async () => {
        if (!syncEnabled.current) return;
        while (pending.current.sessions.size > 0) {
          const [id] = pending.current.sessions;
          try {
            await deleteRemoteSession(id);
          } catch {
            return;
          }
          pending.current.sessions.delete(id);
          snapshot.current = forgetSession(snapshot.current, id);
        }
        while (pending.current.projects.size > 0) {
          const [id] = pending.current.projects;
          try {
            await deleteRemoteProject(id);
          } catch {
            return;
          }
          pending.current.projects.delete(id);
          snapshot.current = forgetProject(snapshot.current, id);
        }

        const plan = planSync(workspaceRef.current, snapshot.current);
        if (isEmptyPlan(plan)) return;

        for (const project of plan.createProjects) {
          try {
            await createRemoteProject({ id: project.id, name: project.name, color: project.color });
          } catch {
            return;
          }
          snapshot.current = markProjectSynced(snapshot.current, project);
        }
        for (const update of plan.updateProjects) {
          try {
            await updateRemoteProject(update.id, { name: update.name, color: update.color });
          } catch {
            return;
          }
          snapshot.current = applyProjectChanges(snapshot.current, update.id, update);
        }
        for (const session of plan.createSessions) {
          try {
            await createRemoteSession({
              id: session.id,
              projectId: session.projectId,
              title: session.title,
              pinned: session.pinned,
            });
          } catch {
            return;
          }
          snapshot.current = markSessionSynced(snapshot.current, session);
        }
        for (const update of plan.updateSessions) {
          try {
            await updateRemoteSession(update.id, {
              title: update.title,
              titleEdited: update.titleEdited,
              pinned: update.pinned,
              projectId: update.projectId,
            });
          } catch {
            return;
          }
          snapshot.current = applySessionChanges(snapshot.current, update.id, update);
        }
      }),
    [serial],
  );

  /**
   * Make sure a session exists on the server before a chat refers to it, creating its project
   * first when needed. Returns whether the session can safely be passed as `session_id`.
   */
  const ensureSession = useCallback(
    (sessionId: string): Promise<boolean> =>
      serial(async () => {
        if (!syncEnabled.current) return false;
        const session = findSession(workspaceRef.current, sessionId);
        if (!session) return false;
        const project = findProject(workspaceRef.current, session.projectId);
        if (!project) return false;
        try {
          if (!snapshot.current.projects[project.id]) {
            await createRemoteProject({ id: project.id, name: project.name, color: project.color });
            snapshot.current = markProjectSynced(snapshot.current, project);
          }
          if (!snapshot.current.sessions[session.id]) {
            await createRemoteSession({
              id: session.id,
              projectId: session.projectId,
              title: session.title,
              pinned: session.pinned,
            });
            snapshot.current = markSessionSynced(snapshot.current, session);
          }
          return true;
        } catch {
          return false;
        }
      }),
    [serial],
  );

  // Detection and one-shot hydration. The local workspace has already rendered from
  // localStorage; when the routes are missing (404) or unreachable, sync stays disabled and
  // nothing changes. Sessions left in localStorage from before the server existed are NOT
  // migrated: the server wins, and the old copy stays untouched in storage.
  useEffect(() => {
    if (syncStarted.current) return;
    syncStarted.current = true;
    const hydrate = async () => {
      let remoteProjects;
      try {
        remoteProjects = await getRemoteProjects();
      } catch {
        return;
      }
      if (!remoteProjects) return;
      let remoteSessions;
      try {
        // The documented route filters by project; asking per project also keeps us away
        // from whatever "no filter" would mean on an older image.
        const lists = await Promise.all(remoteProjects.map((project) => getRemoteSessions(project.id)));
        remoteSessions = lists.flat();
      } catch {
        return;
      }
      const projects = toProjects(remoteProjects);
      const sessions = toSessions(remoteSessions);
      snapshot.current = snapshotFromServer(projects, sessions);
      syncEnabled.current = true;
      dispatch({ type: "hydrate", projects, sessions });
      await reconcileMessages(workspaceRef.current.activeSessionId);
    };
    // Settled whatever the outcome (server unreachable, routes missing): the start-up screen then lets go.
    void hydrate().finally(() => setSynced(true));
  }, [dispatch, reconcileMessages]);

  // A session opened later may have a history the server kept but this browser never saw.
  const activeId = workspace.activeSessionId;
  useEffect(() => {
    void reconcileMessages(activeId);
  }, [activeId, reconcileMessages]);

  // A session's messages are read from storage the first time it is shown.
  useEffect(() => {
    if (chatsRef.current[activeId]) return;
    chatsRef.current = { ...chatsRef.current, [activeId]: store.loadMessages(activeId).map(fromStored) };
    setChats(chatsRef.current);
  }, [activeId, store]);

  // Write-behind: the pause keeps a burst of edits (typing a rename, pinning) to one request.
  useEffect(() => {
    if (!syncEnabled.current) return;
    const timer = window.setTimeout(() => void flush(), SYNC_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [workspace, flush]);

  // Write the workspace after a pause. Messages of a session wait until nothing is being written in it.
  const saved = useRef(new Map<string, ChatMessage[]>());
  useEffect(() => {
    const timer = window.setTimeout(() => {
      store.saveWorkspace(workspace);
      const now = Date.now();
      for (const [sessionId, messages] of Object.entries(chats)) {
        if (saved.current.get(sessionId) === messages) continue;
        if (messages.some((m) => m.streaming)) continue;
        saved.current.set(sessionId, messages);
        store.saveMessages(sessionId, messages.filter((m) => !m.error).map((m) => toStored(m, now)));
      }
    }, SAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [workspace, chats, store]);

  // Closing the tab inside the pause must not lose the last words.
  useEffect(() => {
    const flushLocal = () => {
      store.saveWorkspace(workspaceRef.current);
      const now = Date.now();
      for (const [sessionId, messages] of Object.entries(chatsRef.current)) {
        if (messages.some((m) => m.streaming)) continue;
        store.saveMessages(sessionId, messages.filter((m) => !m.error).map((m) => toStored(m, now)));
      }
    };
    window.addEventListener("pagehide", flushLocal);
    return () => window.removeEventListener("pagehide", flushLocal);
  }, [store]);

  return { workspace, workspaceRef, dispatch, chats, setMessages, messagesOf, discard, discardProject, ensureSession, synced };
}

/** One browser store for the page. */
export function useBrowserStore(): SessionStore {
  return useMemo(() => createBrowserStore(), []);
}
