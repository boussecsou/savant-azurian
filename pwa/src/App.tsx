import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { pushActivity, type ActivityEntry, type ActivityKind, type ActivityLevel } from "./activity";
import { ApiError, StreamUnsupported, errorMessage, sendChat, streamChat, type ApiErrorKind, type ChatMode, type StreamEvent } from "./api";
import { newId, type ChatMessage, type ToolStep } from "./chat";
import { copyText } from "./clipboard";
import { Composer, type ComposerApi } from "./components/Composer";
import { DropVeil, SourcesSection, useFilePicker } from "./components/Documents";
import { Dock } from "./components/dock/Dock";
import { Messages } from "./components/Messages";
import { CommandPalette } from "./components/overlays/CommandPalette";
import { PopoverMenu, useMenu, type MenuEntry } from "./components/overlays/PopoverMenu";
import { Toaster } from "./components/overlays/Toaster";
import { ProjectsPanel } from "./components/rail/ProjectsPanel";
import { ProjectSwitcher } from "./components/rail/ProjectSwitcher";
import { Rail } from "./components/rail/Rail";
import { SessionsPanel } from "./components/rail/SessionsPanel";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { AppShell } from "./components/shell/AppShell";
import { Banner, type BannerContent } from "./components/shell/Banner";
import { Splash } from "./components/shell/Splash";
import { MobileNav } from "./components/shell/MobileNav";
import { TopBar } from "./components/shell/TopBar";
import { VoiceStage } from "./components/stage/VoiceStage";
import { bannerKind, needsAttention } from "./connections";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { useMotion } from "./hooks/useMotion";
import { useOnline } from "./hooks/useOnline";
import { useToasts } from "./hooks/useToasts";
import type { Command } from "./palette";
import { recentIds } from "./state/ids";
import { sessionToMarkdown } from "./state/transcript";
import { useBrowserStore, useWorkspace } from "./state/useWorkspace";
import { checkProjectName, findProject, findSession, type Project, type Session } from "./state/workspace";
import { resolveTheme } from "./theme";
import { toolLabel } from "./tools";
import { useNotion, type NotionState } from "./useNotion";
import { OUTLOOK_ENABLED, useOutlook } from "./useOutlook";
import { useBoot } from "./useBoot";
import { useTheme } from "./useTheme";
import { useVoice } from "./useVoice";
import { useDocuments } from "./useDocuments";
import { DOCUMENTS_ENABLED } from "./flags";
import { mergeSources } from "./sources";
import { settledUploads, type ProjectDocument } from "./documents";
import { useWarmup } from "./useWarmup";
import { loadViewMode, saveViewMode, type ViewMode } from "./viewMode";
import { loadVoiceLanguage, saveVoiceLanguage, type VoiceLanguage } from "./voice";

/** Sent when the owner presses "Connect Outlook": the agent gives the sign-in link, or confirms it already works. */
const CONNECT_OUTLOOK = "Connect my Outlook account. If it is already connected, read my latest email subject to confirm.";

const SUGGESTIONS = ["List my SA2 tasks", "What is the load on the VM?", "Search the web for today's tech news", "What can you do for me?"];

const FAILURE: Record<ApiErrorKind, string> = {
  auth: "Access denied (Entra token)",
  timeout: "Gateway timeout",
  upstream: "Agent unreachable or failing",
  invalid: "Message rejected",
  network: "Network unavailable",
  unknown: "Unknown error",
};

const NOTION_EVENT: Partial<Record<NotionState, [ActivityLevel, string]>> = {
  connected: ["ok", "Notion connected"],
  disconnected: ["warn", "Notion not connected"],
  waiting: ["info", "Waiting for Notion consent"],
  unavailable: ["error", "Notion or gateway unavailable"],
};

const NARROW = "(max-width: 1179px)";

type Renaming = { kind: "session"; id: string; where: "rail" | "top" } | { kind: "project"; id: string } | null;

export default function App() {
  const store = useBrowserStore();
  const { workspace, workspaceRef, dispatch, chats, setMessages, messagesOf, discard, discardProject, ensureSession, synced } = useWorkspace(store);
  const boot = useBoot(synced);
  const activeId = workspace.activeSessionId;
  const activeSession = findSession(workspace, activeId) as Session;
  const activeProject = (findProject(workspace, activeSession.projectId) ?? workspace.projects[0]) as Project;
  // A session opened from the rail is read from storage in the same render, so it never flashes empty.
  const messages = chats[activeId] ?? messagesOf(activeId);

  const [busyIds, setBusyIds] = useState<readonly string[]>([]);
  const [resume, setResume] = useState(false);
  const [settings, setSettings] = useState(false);
  const [palette, setPalette] = useState(false);
  const [railOpen, setRailOpen] = useState(true);
  const [drawer, setDrawer] = useState(false);
  const [focus, setFocus] = useState(false);
  const [mobile, setMobile] = useState<"stage" | "thread">("stage");
  const [view, setView] = useState<ViewMode>(() => loadViewMode());
  const [renaming, setRenaming] = useState<Renaming>(null);
  const [newProjectSignal, setNewProjectSignal] = useState(0);
  const [authDenied, setAuthDenied] = useState(false);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [language, setLanguageState] = useState<VoiceLanguage>(() => loadVoiceLanguage());
  const { state: notionState, justConnected, connect, acknowledge } = useNotion();
  const { state: outlookState, observeTool } = useOutlook();
  const { theme, setTheme } = useTheme();
  const motion = useMotion();
  const online = useOnline();
  const narrow = useMediaQuery(NARROW);
  const prefersDark = useMediaQuery("(prefers-color-scheme: dark)");
  const { toasts, push, act, pause, resume: resumeToast } = useToasts();
  // ------------------------------------------------------------------ documents
  const docs = useDocuments(activeProject.id, DOCUMENTS_ENABLED);
  const uploadDocuments = docs.upload;
  const removeNow = docs.remove;
  // Files added in this page (id → name): when one is indexed (or fails) a toast says so, wherever the rail is.
  const watchedUploads = useRef(new Map<string, string>());
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const { menu, openFrom, openAt, close: closeMenu } = useMenu();
  const composer = useRef<ComposerApi>(null);
  const lastText = useRef(new Map<string, string>());
  const controllers = useRef(new Map<string, AbortController>());
  const lastNotion = useRef<NotionState>("unknown");
  // The voice turn being written, so its timings land on the right message.
  const voiceTurn = useRef<{ sessionId: string; answerId: string } | null>(null);
  // An older BFF image has no streaming route: remember it and use /api/chat for the session.
  const streaming = useRef(true);

  const chatOnly = view === "chat";
  const busy = busyIds.includes(activeId);
  const speakAloud = workspace.ui.speak;

  const log = useCallback((kind: ActivityKind, level: ActivityLevel, label: string, ms?: number, tool?: string) => {
    setActivity((previous) => pushActivity(previous, { id: newId(), at: Date.now(), kind, level, label, ms, tool }));
  }, []);

  const closeSettings = useCallback(() => setSettings(false), []);

  const warm = useWarmup(notionState !== "unknown" && notionState !== "unavailable", (result) =>
    result.ok
      ? log("warmup", "ok", "Agent warmed up", result.ms)
      : result.unsupported
        ? log("warmup", "info", "Warm-up unavailable: the BFF does not have this route yet")
        : log("warmup", "warn", `Warm-up failed: ${FAILURE[result.kind ?? "unknown"]}`, result.ms),
  );
  const takeWarm = warm.take;

  useEffect(
    () => () => {
      for (const controller of controllers.current.values()) controller.abort();
    },
    [],
  );

  // Journal: record Notion state changes, skipping the first check.
  useEffect(() => {
    if (lastNotion.current === notionState) return;
    lastNotion.current = notionState;
    const event = NOTION_EVENT[notionState];
    if (event) log("system", event[0], event[1]);
  }, [notionState, log]);

  // Back from the Notion consent tab: offer to resume the request that needed it.
  useEffect(() => {
    if (justConnected) {
      setResume(messages.length > 0);
      acknowledge();
    }
  }, [justConnected, acknowledge, messages.length]);

  useEffect(() => {
    document.title = `${activeSession.title} · Savant`;
  }, [activeSession.title]);

  // Set once voice exists (below): reads a short fixed phrase when a tool starts or ends in a voice turn.
  const announceTool = useRef<((tool: string | undefined, moment: "start" | "done") => void) | null>(null);

  const setBusy = useCallback((sessionId: string, value: boolean) => {
    setBusyIds((ids) => (value ? (ids.includes(sessionId) ? ids : [...ids, sessionId]) : ids.filter((id) => id !== sessionId)));
  }, []);

  /**
   * One turn, bound to the session it started in: the answer is written there even if the owner opens
   * another session meanwhile. The thread is continued with that session's own Foundry conversation id.
   * `typed`: a voice turn whose message was typed in the composer (shown as typed, answered aloud).
   */
  const send = useCallback(
    async (text: string, mode: ChatMode = "text", sessionId: string = workspaceRef.current.activeSessionId, typed = false): Promise<string | null> => {
      lastText.current.set(sessionId, text);
      setResume(false);
      setMessages(sessionId, (previous) => [...previous.filter((m) => !m.error), { id: newId(), role: "user", text, at: Date.now(), ...(mode === "voice" && !typed ? { voice: true } : {}) }]);
      dispatch({ type: "turn", sessionId, role: "user", text });
      setBusy(sessionId, true);
      // A new session continues the warm-up conversation: its Foundry session is already started.
      const previous = findSession(workspaceRef.current, sessionId)?.conversationId ?? (await takeWarm());
      // The server records the turn itself, so it must know this session before the request.
      const assured = await ensureSession(sessionId);
      const recordedSession = assured ? sessionId : undefined;
      const controller = new AbortController();
      controllers.current.set(sessionId, controller);
      const started = performance.now();
      const elapsed = () => Math.round(performance.now() - started);

      // The agent's message is created by its first event, then patched as the stream goes.
      const answerId = newId();
      if (mode === "voice") voiceTurn.current = { sessionId, answerId };
      const patch = (change: (message: ChatMessage) => ChatMessage) =>
        setMessages(sessionId, (list) => {
          const index = list.findIndex((m) => m.id === answerId);
          if (index === -1) {
            return [...list, change({ id: answerId, role: "assistant", text: "", streaming: true, live: true, at: Date.now(), ...(mode === "voice" ? { voice: true } : {}) })];
          }
          const next = list.slice();
          next[index] = change(list[index]);
          return next;
        });
      const toolStarts = new Map<string, number>();
      const toolNames = new Map<string, string>();
      const announcedTools = new Set<string>();
      const finishedTools = new Set<string>();
      let firstText = false;
      let answer = "";

      const onEvent = (event: StreamEvent) => {
        if (event.type === "delta") {
          if (!firstText) {
            firstText = true;
            log("first-text", "info", "First text received", elapsed());
          }
          answer += event.text;
          patch((m) => ({ ...m, text: m.text + event.text }));
        } else if (event.type === "tool") {
          if (event.status === "running") {
            if (!toolStarts.has(event.id)) toolStarts.set(event.id, performance.now());
            // A toolbox dispatch arrives twice (as call_tool, then with the real name): announce the real one.
            const announced = announcedTools.has(event.id);
            if (mode === "voice" && !announced && event.name !== "call_tool") {
              announcedTools.add(event.id);
              announceTool.current?.(event.name, "start");
            }
            toolNames.set(event.id, event.name ?? "");
            const step: ToolStep = { id: event.id, name: event.name ?? "", status: "running" };
            patch((m) => ({ ...m, tools: [...(m.tools ?? []).filter((t) => t.id !== step.id), step] }));
          } else {
            // The agent reports a tool's output twice (added, then done): count it once.
            if (finishedTools.has(event.id)) return;
            finishedTools.add(event.id);
            if (mode === "voice") announceTool.current?.(toolNames.get(event.id), "done");
            const began = toolStarts.get(event.id);
            const ms = began === undefined ? undefined : Math.round(performance.now() - began);
            patch((m) => ({
              ...m,
              tools: (m.tools ?? []).map((t) => (t.id === event.id ? { ...t, status: "done", ms } : t)),
            }));
            observeTool(toolNames.get(event.id), event.consent === true);
            log("tool", "ok", `Tool · ${toolLabel(toolNames.get(event.id))}`, ms, toolNames.get(event.id));
          }
        } else if (event.type === "sources") {
          patch((m) => ({ ...m, sources: mergeSources(m.sources, event.sources) }));
        } else if (event.type === "done") {
          dispatch({ type: "setConversation", sessionId, conversationId: event.conversationId });
        }
      };

      try {
        if (streaming.current) {
          try {
            await streamChat(text, previous, onEvent, controller.signal, mode, recordedSession);
          } catch (error) {
            if (!(error instanceof StreamUnsupported)) throw error;
            streaming.current = false;
          }
        }
        if (!streaming.current) {
          const reply = await sendChat(text, previous, controller.signal, mode, recordedSession);
          dispatch({ type: "setConversation", sessionId, conversationId: reply.conversationId });
          answer = reply.reply;
          patch((m) => ({ ...m, text: reply.reply }));
        }
        log("chat", "ok", "Answer received", elapsed());
        setAuthDenied(false);
        patch((m) => ({ ...m, streaming: false }));
        if (answer) dispatch({ type: "turn", sessionId, role: "assistant", text: answer });
        return answer;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return null;
        const kind = error instanceof ApiError ? error.kind : "unknown";
        log("chat", "error", FAILURE[kind], elapsed());
        if (kind === "auth") setAuthDenied(true);
        setMessages(sessionId, (list) => [
          // Keep what was written before the failure; drop an answer that never started.
          ...list.filter((m) => m.id !== answerId || m.text !== "" || (m.tools?.length ?? 0) > 0).map((m) => (m.id === answerId ? { ...m, streaming: false } : m)),
          { id: newId(), role: "assistant", text: "", error: kind },
        ]);
        return null;
      } finally {
        controllers.current.delete(sessionId);
        setBusy(sessionId, false);
      }
    },
    [dispatch, ensureSession, log, observeTool, setBusy, setMessages, takeWarm, workspaceRef],
  );

  const setLanguage = useCallback((next: VoiceLanguage) => {
    saveVoiceLanguage(next);
    setLanguageState(next);
  }, []);

  // Voice: each final transcript is sent like a typed message, marked as spoken; the answer is read aloud.
  // A message typed while voice mode is on goes through the same loop (see sendText).
  const voice = useVoice(
    useCallback((text: string, heard: { typed?: boolean }) => send(text, "voice", undefined, heard.typed === true), [send]),
    {
      language,
      speakAloud,
      onTurn: (trace) => {
        const turn = voiceTurn.current;
        if (turn) setMessages(turn.sessionId, (list) => list.map((m) => (m.id === turn.answerId ? { ...m, trace } : m)));
      },
      onSoftError: () => push({ message: "The answer could not be read aloud; it is in the thread.", kind: "info" }),
    },
  );
  announceTool.current = voice.announce;
  const voiceOn = voice.state !== "off" && voice.state !== "error";
  const stopVoice = voice.stop;

  // Get the Speech SDK and a token ready shortly after load: the first tap then listens at once.
  const prepareVoice = voice.prepare;
  useEffect(() => {
    const timer = setTimeout(() => void prepareVoice(), 1500);
    return () => clearTimeout(timer);
  }, [prepareVoice]);

  const toggleVoice = useCallback(() => (voiceOn ? stopVoice() : void voice.start()), [voiceOn, stopVoice, voice]);

  // Chat only hides the voice stage; the thread stays, and the microphone moves to the composer.
  const chooseView = useCallback((next: ViewMode) => {
    saveViewMode(next);
    setView(next);
    if (next === "chat") {
      setFocus(false);
      setMobile("thread");
    }
  }, []);
  const toggleChatOnly = useCallback(() => chooseView(chatOnly ? "voice" : "chat"), [chatOnly, chooseView]);

  // ------------------------------------------------------------------ navigation

  /** Whatever changes the open session ends voice mode: its turn would no longer land where the owner is looking. */
  const leaveSession = useCallback(() => {
    if (voiceOn) stopVoice();
    setDrawer(false);
    setRenaming(null);
  }, [voiceOn, stopVoice]);

  const openSession = useCallback(
    (id: string) => {
      if (id !== workspaceRef.current.activeSessionId) leaveSession();
      else setDrawer(false);
      dispatch({ type: "openSession", id });
    },
    [dispatch, leaveSession, workspaceRef],
  );

  const newSession = useCallback(
    (projectId?: string) => {
      leaveSession();
      dispatch({ type: "newSession", projectId });
      setSwitcherOpen(false);
      window.setTimeout(() => composer.current?.focus(), 0);
    },
    [dispatch, leaveSession],
  );

  const selectProject = useCallback(
    (id: string) => {
      leaveSession();
      dispatch({ type: "selectProject", id });
      setSwitcherOpen(false);
    },
    [dispatch, leaveSession],
  );

  const showRail = useCallback(() => (narrow ? setDrawer(true) : setRailOpen(true)), [narrow]);
  const hideRail = useCallback(() => (narrow ? setDrawer(false) : setRailOpen(false)), [narrow]);

  // ------------------------------------------------------------------ sessions

  const copySession = useCallback(
    async (session: Session) => {
      const ok = await copyText(sessionToMarkdown(session.title, messagesOf(session.id)));
      push(ok ? { message: "Session copied as Markdown", kind: "ok" } : { message: "The clipboard refused the copy", kind: "err" });
    },
    [messagesOf, push],
  );

  const deleteSession = useCallback(
    (session: Session) => {
      const wasActive = workspaceRef.current.activeSessionId === session.id;
      if (wasActive) leaveSession();
      controllers.current.get(session.id)?.abort();
      dispatch({ type: "deleteSession", id: session.id });
      push({
        message: `Deleted “${session.title}”`,
        kind: "info",
        ms: 6500,
        action: { label: "Undo", run: () => dispatch({ type: "restoreSession", session, active: wasActive }) },
        onExpire: () => discard(session.id),
      });
    },
    [discard, dispatch, leaveSession, push, workspaceRef],
  );

  const sessionMenu = useCallback(
    (session: Session): MenuEntry[] => {
      const others = workspaceRef.current.projects.filter((p) => p.id !== session.projectId);
      const entries: MenuEntry[] = [
        { kind: "item", id: "rename", label: "Rename", icon: "pencil", onSelect: () => setRenaming({ kind: "session", id: session.id, where: "rail" }) },
        { kind: "item", id: "pin", label: session.pinned ? "Unpin" : "Pin to top", icon: "pin", onSelect: () => dispatch({ type: "pinSession", id: session.id, pinned: !session.pinned }) },
        { kind: "item", id: "copy", label: "Copy as Markdown", icon: "copy", onSelect: () => void copySession(session) },
      ];
      if (others.length > 0) {
        entries.push({ kind: "separator" }, { kind: "label", label: "Move to project" });
        for (const project of others) {
          entries.push({ kind: "item", id: `move-${project.id}`, label: project.name, icon: "folder", onSelect: () => dispatch({ type: "moveSession", id: session.id, projectId: project.id }) });
        }
      }
      entries.push({ kind: "separator" }, { kind: "item", id: "delete", label: "Delete", icon: "trash", danger: true, onSelect: () => deleteSession(session) });
      return entries;
    },
    [copySession, deleteSession, dispatch, workspaceRef],
  );

  const renameSession = useCallback((id: string, title: string) => dispatch({ type: "renameSession", id, title }), [dispatch]);
  const endRename = useCallback(() => setRenaming(null), []);
  const startRename = useCallback((id: string) => setRenaming({ kind: "session", id, where: "rail" }), []);
  const onSessionMenu = useCallback((trigger: HTMLElement, session: Session) => openFrom(trigger, sessionMenu(session)), [openFrom, sessionMenu]);
  const onSessionContext = useCallback((x: number, y: number, session: Session) => openAt(x, y, sessionMenu(session)), [openAt, sessionMenu]);

  // ------------------------------------------------------------------ projects

  const createProject = useCallback(
    (name: string, color: string): string | null => {
      const checked = checkProjectName(workspaceRef.current, name);
      if (!checked.ok) return checked.error;
      leaveSession();
      dispatch({ type: "createProject", name: checked.name, color });
      setSwitcherOpen(false);
      push({ message: `Project “${checked.name}” created`, kind: "ok" });
      return null;
    },
    [dispatch, leaveSession, push, workspaceRef],
  );

  const renameProject = useCallback(
    (id: string, name: string): string | null => {
      const checked = checkProjectName(workspaceRef.current, name, id);
      if (!checked.ok) return checked.error;
      dispatch({ type: "renameProject", id, name: checked.name });
      return null;
    },
    [dispatch, workspaceRef],
  );

  const deleteProject = useCallback(
    (project: Project) => {
      const current = workspaceRef.current;
      const sessions = current.sessions.filter((s) => s.projectId === project.id);
      const activeInside = sessions.some((s) => s.id === current.activeSessionId);
      if (activeInside) leaveSession();
      for (const s of sessions) controllers.current.get(s.id)?.abort();
      const activeSessionId = activeInside ? current.activeSessionId : undefined;
      dispatch({ type: "deleteProject", id: project.id });
      const count = sessions.length;
      push({
        message: `Deleted project “${project.name}”${count ? ` and ${count} session${count === 1 ? "" : "s"}` : ""}`,
        kind: "info",
        ms: 7000,
        action: { label: "Undo", run: () => dispatch({ type: "restoreProject", project, sessions, activeSessionId }) },
        onExpire: () => discardProject(project.id, sessions.map((s) => s.id)),
      });
    },
    [discardProject, dispatch, leaveSession, push, workspaceRef],
  );

  const onProjectMenu = useCallback(
    (trigger: HTMLElement, project: Project) => {
      const entries: MenuEntry[] = [
        { kind: "item", id: "rename", label: "Rename", icon: "pencil", onSelect: () => { setSwitcherOpen(true); setRenaming({ kind: "project", id: project.id }); } },
        { kind: "item", id: "new", label: "New session here", icon: "plus", onSelect: () => newSession(project.id) },
      ];
      if (!project.system) entries.push({ kind: "separator" }, { kind: "item", id: "delete", label: "Delete project", icon: "trash", danger: true, onSelect: () => deleteProject(project) });
      openFrom(trigger, entries);
    },
    [deleteProject, newSession, openFrom],
  );

  const sessionCount = useCallback((projectId: string) => workspace.sessions.filter((s) => s.projectId === projectId).length, [workspace.sessions]);
  const messageText = useCallback((sessionId: string) => messagesOf(sessionId).map((m) => m.text).join(" ").toLowerCase(), [messagesOf]);

  // ------------------------------------------------------------------ thread actions

  const retry = useCallback(() => {
    const sessionId = workspaceRef.current.activeSessionId;
    // Drop the notice and everything the failed turn wrote after the reader's message, then ask again.
    setMessages(sessionId, (previous) => {
      const base = previous.filter((m) => !m.error);
      let end = base.length;
      while (end > 0 && base[end - 1].role === "assistant") end--;
      return base.slice(0, end > 0 && base[end - 1].role === "user" ? end - 1 : end);
    });
    void send(lastText.current.get(sessionId) ?? "", "text", sessionId);
  }, [send, setMessages, workspaceRef]);

  // The agent would not continue an old thread: forget it, keep the text on screen, ask again here.
  const startFresh = useCallback(() => {
    dispatch({ type: "setConversation", sessionId: workspaceRef.current.activeSessionId, conversationId: undefined });
    retry();
  }, [dispatch, retry, workspaceRef]);

  const copyAnswer = useCallback(
    async (text: string) => {
      const ok = await copyText(text);
      push(ok ? { message: "Copied", kind: "ok", ms: 2200 } : { message: "The clipboard refused the copy", kind: "err" });
    },
    [push],
  );

  /** Adds files to the active project's sources; a toast follows each one from "indexing" to "ready". */
  const addDocuments = useCallback(
    async (files: File[]) => {
      const project = activeProject.name;
      const results = await uploadDocuments(files);
      for (const result of results) {
        if ("error" in result) push({ message: result.error, kind: "err" });
        else {
          watchedUploads.current.set(result.document.id, result.document.name);
          push({ message: `Added “${result.document.name}” to ${project}'s sources · indexing…`, kind: "info", ms: 3500 });
          log("system", "ok", `Document added · ${result.document.name}`);
        }
      }
    },
    [activeProject.name, log, push, uploadDocuments],
  );

  // The thread is a drop target too: a file dropped anywhere on it goes to the active project's sources.
  const dropTarget = useFilePicker((files) => void addDocuments(files));

  // Removed at once everywhere (the index first, then the file): the next question can no longer find it.
  // Undo sends the kept copy again, as a new document of the same project.
  const removeDocument = useCallback(
    async (document: ProjectDocument) => {
      try {
        const copy = await removeNow(document);
        push({
          message: `Removed “${document.name}” from the project's sources`,
          kind: "info",
          ms: 6500,
          action: copy ? { label: "Undo", run: () => void addDocuments([copy]) } : undefined,
        });
      } catch {
        push({ message: `“${document.name}” could not be removed. Try again.`, kind: "err" });
      }
    },
    [addDocuments, push, removeNow],
  );

  const knownDocuments = useMemo(() => new Set(docs.documents.filter((d) => d.state !== "uploading").map((d) => d.id)), [docs.documents]);

  useEffect(() => {
    if (watchedUploads.current.size === 0) return;
    const visible = docs.documents.filter((d) => !docs.hidden.has(d.id));
    for (const { id, name, outcome } of settledUploads(watchedUploads.current, visible)) {
      watchedUploads.current.delete(id);
      if (outcome === "ready") push({ message: `“${name}” is ready: Savant can search it`, kind: "ok", ms: 4000 });
      else if (outcome === "failed") push({ message: `“${name}” could not be indexed. Remove it and try another file.`, kind: "err" });
    }
  }, [docs.documents, docs.hidden, push]);

  // Chat and voice are two inputs of one conversation: while voice mode is on, a typed message joins
  // the voice loop and its answer is read aloud; otherwise it is an ordinary text turn.
  const submitTyped = voice.submit;
  const sendText = useCallback(
    (text: string) => {
      if (!voiceOn) return void send(text);
      // Never a second turn beside the voice one: while Savant answers, the message waits for the owner.
      if (!submitTyped(text)) push({ message: "Savant is answering; send it once the answer starts.", kind: "info" });
    },
    [push, send, submitTyped, voiceOn],
  );

  // ------------------------------------------------------------------ keyboard

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((open) => !open);
        return;
      }
      if (event.key === "F2" && !renaming) {
        event.preventDefault();
        setRenaming({ kind: "session", id: workspaceRef.current.activeSessionId, where: "top" });
        return;
      }
      if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        const target = event.target as HTMLElement | null;
        const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
        if (!typing) {
          event.preventDefault();
          composer.current?.focus();
        }
        return;
      }
      // Overlays handle (and stop) their own Escape: what reaches here belongs to voice mode.
      if (event.key === "Escape" && voiceOn) stopVoice();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [renaming, stopVoice, voiceOn, workspaceRef]);

  // ------------------------------------------------------------------ palette

  const commands = useMemo<Command[]>(() => {
    const list: Command[] = [
      { id: "new-session", title: "New session", kind: "Action", run: () => newSession() },
      { id: "new-project", title: "New project", kind: "Action", run: () => { showRail(); setSwitcherOpen(true); setNewProjectSignal((n) => n + 1); } },
      { id: "voice", title: voiceOn ? "Stop voice mode" : "Start voice mode", kind: "Action", run: toggleVoice },
      { id: "settings", title: "Open settings", kind: "Action", run: () => setSettings(true) },
      { id: "projects", title: "Switch project", kind: "Action", run: () => { showRail(); setSwitcherOpen(true); } },
      { id: "sessions", title: "Show sessions", kind: "Action", run: () => { showRail(); setSwitcherOpen(false); } },
      { id: "chat-only", title: chatOnly ? "Show voice and chat" : "Chat only", kind: "Action", run: toggleChatOnly },
      { id: "focus", title: focus ? "Leave focus mode" : "Enter focus mode", kind: "Action", run: () => { chooseView("voice"); setFocus((f) => !f); } },
      { id: "theme", title: "Switch theme", kind: "Action", run: () => setTheme(resolveTheme(theme, prefersDark) === "dark" ? "light" : "dark") },
    ];
    for (const project of workspace.projects) list.push({ id: `p-${project.id}`, title: project.name, kind: "Project", run: () => selectProject(project.id) });
    const names = new Map(workspace.projects.map((p) => [p.id, p.name]));
    for (const session of [...workspace.sessions].sort((a, b) => b.updatedAt - a.updatedAt)) {
      list.push({ id: `s-${session.id}`, title: session.title, kind: `Session · ${names.get(session.projectId) ?? ""}`, run: () => openSession(session.id) });
    }
    return list;
  }, [chatOnly, chooseView, focus, newSession, openSession, prefersDark, selectProject, setTheme, showRail, theme, toggleChatOnly, toggleVoice, voiceOn, workspace.projects, workspace.sessions]);

  // ------------------------------------------------------------------ banner

  const banner = useMemo<BannerContent | null>(() => {
    const kind = bannerKind({ authDenied, online, notion: notionState });
    if (kind === "auth") {
      return { tone: "err", icon: "lock", title: "Access denied.", text: errorMessage("auth").replace(/^Access denied\.\s*/, ""), action: { label: "Reload", run: () => window.location.reload() } };
    }
    if (kind === "offline") {
      return { tone: "warn", icon: "alert", title: "You are offline.", text: "Voice and chat need the gateway. Your draft is kept.", action: { label: "Retry", run: () => window.location.reload() } };
    }
    if (kind === "tool") {
      return { tone: "warn", icon: "alert", title: "A tool is unavailable.", text: "Requests that need it will fail until it is back.", action: { label: "Review", run: () => setSettings(true) } };
    }
    return null;
  }, [authDenied, online, notionState]);

  const attention = needsAttention(notionState, outlookState, OUTLOOK_ENABLED);
  const ids = useMemo(() => recentIds(messages.map((m) => m.text)), [messages]);
  const renamingTop = renaming?.kind === "session" && renaming.where === "top" && renaming.id === activeId;
  const draft = activeSession.draft ?? "";

  return (
    <>
      <AppShell
        railOpen={railOpen}
        focus={focus}
        chatOnly={chatOnly}
        drawer={drawer}
        mobile={mobile}
        boot={boot}
        voiceActive={voiceOn}
        reducedMotion={motion.reduced}
        onCloseDrawer={() => setDrawer(false)}
        rail={
          <Rail
            onCollapse={hideRail}
            onPalette={() => setPalette(true)}
            switcher={
              <ProjectSwitcher project={activeProject} sessionCount={sessionCount(activeProject.id)} open={switcherOpen} onOpenChange={setSwitcherOpen}>
                <ProjectsPanel
                  projects={workspace.projects}
                  activeProjectId={activeProject.id}
                  sessionCount={sessionCount}
                  renamingId={renaming?.kind === "project" ? renaming.id : null}
                  onCreate={createProject}
                  onSelect={selectProject}
                  onMenu={onProjectMenu}
                  onRename={renameProject}
                  onRenameEnd={endRename}
                  createSignal={newProjectSignal}
                />
              </ProjectSwitcher>
            }
            sessions={
              <SessionsPanel
                projects={workspace.projects}
                sessions={workspace.sessions}
                activeProject={activeProject}
                activeSessionId={activeId}
                renamingId={renaming?.kind === "session" && renaming.where === "rail" ? renaming.id : null}
                messageText={messageText}
                onOpen={openSession}
                onNew={() => newSession()}
                onMenu={onSessionMenu}
                onContextMenu={onSessionContext}
                onRename={renameSession}
                onRenameEnd={endRename}
                onStartRename={startRename}
              />
            }
            sources={
              DOCUMENTS_ENABLED ? (
                <SourcesSection
                  projectName={activeProject.name}
                  documents={docs.documents}
                  hidden={docs.hidden}
                  loaded={docs.loaded}
                  error={docs.error}
                  onAdd={(files) => void addDocuments(files)}
                  onRemove={(document) => void removeDocument(document)}
                />
              ) : undefined
            }
          />
        }
        stage={
          <main className="stage" id="stage">
            <TopBar
              title={activeSession.title}
              project={activeProject}
              showRailButton={narrow || !railOpen || focus}
              onShowRail={() => {
                setFocus(false);
                showRail();
              }}
              focus={focus}
              onFocus={() => {
                chooseView("voice");
                setFocus((f) => !f);
              }}
              chatOnly={chatOnly}
              onChatOnly={toggleChatOnly}
              attention={attention}
              settingsOpen={settings}
              onSettings={() => setSettings(true)}
              onRename={(title) => renameSession(activeId, title)}
              renaming={renamingTop}
              onRenameEnd={endRename}
              onStartRename={() => setRenaming({ kind: "session", id: activeId, where: "top" })}
            />
            <Banner content={banner} />
            <VoiceStage
              state={voice.state}
              error={voice.error}
              muted={voice.muted}
              partial={voice.partial}
              heard={voice.heard}
              spoken={voice.spoken}
              announced={voice.announced}
              language={language}
              micLevel={voice.micLevel}
              spectrum={voice.spectrum}
              isDark={resolveTheme(theme, prefersDark) === "dark"}
              reducedMotion={motion.reduced}
              suggestions={SUGGESTIONS}
              onToggle={toggleVoice}
              onMute={() => voice.setMuted(!voice.muted)}
              onEnd={stopVoice}
              onLanguage={() => setLanguage(language === "fr-FR" ? "en-US" : "fr-FR")}
              onSuggest={sendText}
            />
          </main>
        }
        dock={
          <Dock
            title={activeSession.title}
            messageCount={messages.filter((m) => !m.error).length}
            onCopySession={() => void copySession(activeSession)}
            drop={DOCUMENTS_ENABLED ? dropTarget.drop : undefined}
            veil={DOCUMENTS_ENABLED && dropTarget.over ? <DropVeil projectName={activeProject.name} /> : undefined}
          >
            <Messages
              messages={messages}
              busy={busy}
              onRetry={retry}
              onCopy={(text) => void copyAnswer(text)}
              onOpenSettings={() => setSettings(true)}
              onStartFresh={activeSession.conversationId ? startFresh : undefined}
              sources={DOCUMENTS_ENABLED ? { projectId: activeProject.id, known: knownDocuments } : undefined}
            />
            <Composer
              key={activeId}
              apiRef={composer}
              busy={busy}
              resume={resume}
              tech={workspace.ui.tech}
              onTech={() => dispatch({ type: "setUi", change: { tech: !workspace.ui.tech } })}
              draft={draft}
              onDraft={(text) => dispatch({ type: "setDraft", sessionId: activeId, draft: text })}
              recentIds={ids}
              onSend={sendText}
              onResume={() => void send("connected")}
              onAttach={DOCUMENTS_ENABLED ? (files) => void addDocuments(files) : undefined}
              attachTo={activeProject.name}
              voice={chatOnly ? { on: voiceOn, label: voiceOn ? `Voice mode: ${voice.state}. Press to stop` : "Start voice mode", onToggle: toggleVoice } : undefined}
            />
          </Dock>
        }
      />
      <MobileNav
        mobile={mobile}
        drawerOpen={drawer}
        chatOnly={chatOnly}
        onMobile={(view) => {
          setDrawer(false);
          setMobile(view);
        }}
        onDrawer={() => setDrawer((open) => !open)}
      />
      <SettingsDrawer
        open={settings}
        onClose={closeSettings}
        notion={notionState}
        onConnect={connect}
        outlook={outlookState}
        onConnectOutlook={() => {
          closeSettings();
          void send(CONNECT_OUTLOOK);
        }}
        activity={activity}
        onClearActivity={() => setActivity([])}
        warm={warm}
        theme={theme}
        onTheme={setTheme}
        motion={motion.preference}
        onMotion={motion.setPreference}
        language={language}
        onLanguage={setLanguage}
        speakAloud={speakAloud}
        onSpeakAloud={(value) => dispatch({ type: "setUi", change: { speak: value } })}
      />
      <Splash phase={boot} />
      <PopoverMenu menu={menu} onClose={closeMenu} />
      <CommandPalette open={palette} onClose={() => setPalette(false)} commands={commands} />
      <Toaster toasts={toasts} onAction={act} onPause={pause} onResume={resumeToast} />
    </>
  );
}
