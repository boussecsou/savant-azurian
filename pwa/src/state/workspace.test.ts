import { describe, expect, it } from "vitest";
import {
  COLORS,
  MAIN_ID,
  NEW_SESSION_TITLE,
  autoTitle,
  checkProjectName,
  createWorkspace,
  findSession,
  isOpen,
  normalize,
  reduce,
  sessionsOf,
  type Action,
  type Env,
  type Workspace,
} from "./workspace";

function makeEnv(start = 1000) {
  let n = 0;
  const env: Env = { now: start, id: () => `id${++n}` };
  return env;
}

function run(workspace: Workspace, env: Env, ...actions: Action[]): Workspace {
  return actions.reduce((w, a) => reduce(w, a, env), workspace);
}

function setup() {
  const env = makeEnv();
  return { env, w: createWorkspace(env) };
}

describe("createWorkspace", () => {
  it("starts with the Main project and one empty session", () => {
    const { w } = setup();
    expect(w.projects).toHaveLength(1);
    expect(w.projects[0]).toMatchObject({ id: MAIN_ID, name: "Main", system: true });
    expect(w.sessions).toHaveLength(1);
    expect(w.sessions[0]).toMatchObject({ projectId: MAIN_ID, title: NEW_SESSION_TITLE, messageCount: 0 });
    expect(w.activeSessionId).toBe(w.sessions[0].id);
  });
});

describe("titles", () => {
  it("strips Markdown and cuts at 42 characters", () => {
    expect(autoTitle("**Hello** [world](http://x.y)")).toBe("Hello world");
    const title = autoTitle("a".repeat(60)) as string;
    expect(title).toHaveLength(42);
    expect(title.endsWith("…")).toBe(true);
    expect(autoTitle("  ***  ")).toBeUndefined();
  });

  it("titles a session from its first user message only, unless it was renamed", () => {
    const { env, w } = setup();
    const id = w.activeSessionId;
    const first = run(w, env, { type: "turn", sessionId: id, role: "user", text: "Plan my week" }, { type: "turn", sessionId: id, role: "assistant", text: "Sure" }, { type: "turn", sessionId: id, role: "user", text: "Other" });
    expect(findSession(first, id)).toMatchObject({ title: "Plan my week", messageCount: 3 });

    const renamed = run(w, env, { type: "renameSession", id, title: "My title" }, { type: "turn", sessionId: id, role: "user", text: "Plan my week" });
    expect(findSession(renamed, id)?.title).toBe("My title");
  });

  it("ignores an empty rename", () => {
    const { env, w } = setup();
    expect(run(w, env, { type: "renameSession", id: w.activeSessionId, title: "  " })).toBe(w);
  });
});

describe("new session", () => {
  it("reuses the empty session of the project instead of piling up", () => {
    const { env, w } = setup();
    const again = run(w, env, { type: "newSession" });
    expect(again.sessions).toHaveLength(1);
    expect(again.activeSessionId).toBe(w.activeSessionId);
  });

  it("creates one at the head once the current one has messages", () => {
    const { env, w } = setup();
    const used = run(w, env, { type: "turn", sessionId: w.activeSessionId, role: "user", text: "hi" }, { type: "newSession" });
    expect(used.sessions).toHaveLength(2);
    expect(used.sessions[0].id).toBe(used.activeSessionId);
    expect(used.sessions[0].messageCount).toBe(0);
  });
});

describe("projects", () => {
  it("creates a project, activates it and gives it a session", () => {
    const { env, w } = setup();
    const next = run(w, env, { type: "createProject", name: "  Cloud   study ", color: COLORS[2] });
    const project = next.projects[1];
    expect(project).toMatchObject({ name: "Cloud study", color: COLORS[2] });
    expect(next.activeProjectId).toBe(project.id);
    expect(findSession(next, next.activeSessionId)?.projectId).toBe(project.id);
  });

  it("refuses duplicates (case-insensitive), empty and too long names", () => {
    const { env, w } = setup();
    expect(checkProjectName(w, "main")).toEqual({ ok: false, error: "A project named “main” already exists" });
    expect(checkProjectName(w, "   ").ok).toBe(false);
    expect(checkProjectName(w, "x".repeat(41)).ok).toBe(false);
    expect(run(w, env, { type: "createProject", name: "MAIN", color: COLORS[1] })).toBe(w);
  });

  it("lets a project keep its own name when renamed in another case", () => {
    const { env, w } = setup();
    const next = run(w, env, { type: "createProject", name: "Lab", color: COLORS[1] });
    const id = next.projects[1].id;
    expect(run(next, env, { type: "renameProject", id, name: "LAB" }).projects[1].name).toBe("LAB");
  });

  it("never deletes Main", () => {
    const { env, w } = setup();
    expect(run(w, env, { type: "deleteProject", id: MAIN_ID })).toBe(w);
  });

  it("deletes a project with its sessions, falls back to Main, and can restore both", () => {
    const { env, w } = setup();
    const withProject = run(w, env, { type: "createProject", name: "Lab", color: COLORS[1] });
    const project = withProject.projects[1];
    const labSessions = sessionsOf(withProject, project.id);
    const activeBefore = withProject.activeSessionId;

    const deleted = run(withProject, env, { type: "deleteProject", id: project.id });
    expect(deleted.projects.map((p) => p.id)).toEqual([MAIN_ID]);
    expect(deleted.sessions.some((s) => s.projectId === project.id)).toBe(false);
    expect(deleted.activeProjectId).toBe(MAIN_ID);
    expect(findSession(deleted, deleted.activeSessionId)).toBeDefined();

    const restored = run(deleted, env, { type: "restoreProject", project, sessions: labSessions, activeSessionId: activeBefore });
    expect(restored.projects.map((p) => p.id)).toEqual([MAIN_ID, project.id]);
    expect(restored.activeSessionId).toBe(activeBefore);
    expect(restored.activeProjectId).toBe(project.id);
  });

  it("selecting a project opens its newest session, or starts one", () => {
    const { env, w } = setup();
    const two = run(w, env, { type: "createProject", name: "Lab", color: COLORS[1] });
    const back = run(two, env, { type: "selectProject", id: MAIN_ID });
    expect(back.activeProjectId).toBe(MAIN_ID);
    expect(findSession(back, back.activeSessionId)?.projectId).toBe(MAIN_ID);
  });
});

describe("sessions", () => {
  it("opening a session makes its project active", () => {
    const { env, w } = setup();
    const two = run(w, env, { type: "createProject", name: "Lab", color: COLORS[1] });
    const mainSession = sessionsOf(two, MAIN_ID)[0];
    const opened = run(two, env, { type: "openSession", id: mainSession.id });
    expect(opened.activeProjectId).toBe(MAIN_ID);
  });

  it("moves a session to another project without touching its conversation id", () => {
    const { env, w } = setup();
    const id = w.activeSessionId;
    const two = run(w, env, { type: "setConversation", sessionId: id, conversationId: "caresp_1" }, { type: "createProject", name: "Lab", color: COLORS[1] });
    const lab = two.projects[1].id;
    const moved = run(two, env, { type: "moveSession", id, projectId: lab });
    expect(findSession(moved, id)).toMatchObject({ projectId: lab, conversationId: "caresp_1" });
    expect(run(two, env, { type: "moveSession", id, projectId: "nope" })).toBe(two);
  });

  it("deleting the active session opens the newest of the same project, else creates one", () => {
    const { env, w } = setup();
    const a = w.activeSessionId;
    const withTwo = run(w, env, { type: "turn", sessionId: a, role: "user", text: "first" }, { type: "newSession" });
    const b = withTwo.activeSessionId;

    const afterB = run(withTwo, env, { type: "deleteSession", id: b });
    expect(afterB.activeSessionId).toBe(a);

    const alone = run(afterB, env, { type: "deleteSession", id: a });
    expect(alone.sessions).toHaveLength(1);
    expect(alone.sessions[0]).toMatchObject({ projectId: MAIN_ID, messageCount: 0 });
    expect(alone.activeSessionId).toBe(alone.sessions[0].id);
  });

  it("restores a deleted session and reactivates it", () => {
    const { env, w } = setup();
    const id = w.activeSessionId;
    const session = findSession(w, id)!;
    const deleted = run(w, env, { type: "deleteSession", id });
    const restored = run(deleted, env, { type: "restoreSession", session, active: true });
    expect(restored.activeSessionId).toBe(id);
    expect(run(restored, env, { type: "restoreSession", session, active: false })).toBe(restored);
  });

  it("pins, stores and clears a draft, and tracks the conversation id", () => {
    const { env, w } = setup();
    const id = w.activeSessionId;
    const next = run(w, env, { type: "pinSession", id, pinned: true }, { type: "setDraft", sessionId: id, draft: "hello" }, { type: "setConversation", sessionId: id, conversationId: "caresp_9" });
    expect(findSession(next, id)).toMatchObject({ pinned: true, draft: "hello", conversationId: "caresp_9" });
    expect(findSession(run(next, env, { type: "setDraft", sessionId: id, draft: "" }), id)).not.toHaveProperty("draft");
  });

  it("ignores a draft or conversation id that did not change, and forgets a conversation on request", () => {
    const { env, w } = setup();
    const id = w.activeSessionId;
    expect(run(w, env, { type: "setDraft", sessionId: id, draft: "" })).toBe(w);
    const withConv = run(w, env, { type: "setConversation", sessionId: id, conversationId: "caresp_1" });
    expect(run(withConv, env, { type: "setConversation", sessionId: id, conversationId: "caresp_1" })).toBe(withConv);
    const forgotten = run(withConv, env, { type: "setConversation", sessionId: id, conversationId: undefined });
    expect(findSession(forgotten, id)).not.toHaveProperty("conversationId");
  });

  it("a turn updates only its own session, wherever the owner is now", () => {
    const { env, w } = setup();
    const a = w.activeSessionId;
    const used = run(w, env, { type: "turn", sessionId: a, role: "user", text: "x" }, { type: "newSession" });
    const later: Env = { ...env, now: 5000 };
    const next = reduce(used, { type: "turn", sessionId: a, role: "assistant", text: "answer" }, later);
    expect(findSession(next, a)).toMatchObject({ messageCount: 2, updatedAt: 5000 });
    expect(next.activeSessionId).toBe(used.activeSessionId);
  });
});

describe("ui", () => {
  it("expands only the active project until the owner chooses", () => {
    const { env, w } = setup();
    expect(isOpen(w, MAIN_ID)).toBe(true);
    const closed = run(w, env, { type: "setOpen", projectId: MAIN_ID, open: false });
    expect(isOpen(closed, MAIN_ID)).toBe(false);
    expect(run(closed, env, { type: "setUi", change: { railTab: "projects", tech: true } }).ui).toMatchObject({ railTab: "projects", tech: true, speak: true });
  });
});

describe("hydrate", () => {
  it("takes the server's projects and sessions but keeps the owner's UI choices", () => {
    const env = makeEnv();
    const local = run(createWorkspace(env), env, { type: "setUi", change: { railTab: "projects", tech: true } });
    const projects = [
      { id: MAIN_ID, name: "Main", color: COLORS[0], system: true as const, createdAt: 1 },
      { id: "lab", name: "Lab", color: COLORS[2], createdAt: 2 },
    ];
    const sessions = [
      { id: "s1", projectId: "lab", title: "Server chat", pinned: true, updatedAt: 5, messageCount: 2 },
      { id: "s0", projectId: MAIN_ID, title: "Main chat", pinned: false, updatedAt: 3, messageCount: 0 },
    ];

    const next = run(local, env, { type: "hydrate", projects, sessions });
    expect(next.projects).toEqual(projects);
    expect(next.sessions).toEqual(sessions);
    expect(next.ui).toEqual(local.ui);
  });

  it("keeps the active session when the server still has it", () => {
    const env = makeEnv();
    const local = createWorkspace(env);
    const id = local.activeSessionId;
    const sessions = [
      { id, projectId: "lab", title: "Kept", pinned: false, updatedAt: 8, messageCount: 1 },
      { id: "newer", projectId: MAIN_ID, title: "Newer", pinned: false, updatedAt: 9, messageCount: 1 },
    ];
    const projects = [
      { id: MAIN_ID, name: "Main", color: COLORS[0], system: true as const, createdAt: 1 },
      { id: "lab", name: "Lab", color: COLORS[2], createdAt: 2 },
    ];

    const next = run(local, env, { type: "hydrate", projects, sessions });
    expect(next.activeSessionId).toBe(id);
    expect(next.activeProjectId).toBe("lab");
  });

  it("opens the newest Main session when the active one is gone", () => {
    const env = makeEnv();
    const local = createWorkspace(env);
    const sessions = [
      { id: "lab-chat", projectId: "lab", title: "Lab", pinned: false, updatedAt: 20, messageCount: 1 },
      { id: "main-old", projectId: MAIN_ID, title: "Old", pinned: false, updatedAt: 4, messageCount: 1 },
      { id: "main-new", projectId: MAIN_ID, title: "New", pinned: false, updatedAt: 6, messageCount: 1 },
    ];
    const projects = [
      { id: MAIN_ID, name: "Main", color: COLORS[0], system: true as const, createdAt: 1 },
      { id: "lab", name: "Lab", color: COLORS[2], createdAt: 2 },
    ];

    const next = run(local, env, { type: "hydrate", projects, sessions });
    expect(next.activeSessionId).toBe("main-new");
    expect(next.activeProjectId).toBe(MAIN_ID);
  });

  it("starts a local empty session when the server knows none", () => {
    const env = makeEnv();
    const local = run(createWorkspace(env), env, { type: "setUi", change: { speak: false } });

    const next = run(local, env, { type: "hydrate", projects: [], sessions: [] });
    expect(next.projects.map((p) => p.id)).toEqual([MAIN_ID]);
    expect(next.sessions).toHaveLength(1);
    expect(findSession(next, next.activeSessionId)).toMatchObject({ projectId: MAIN_ID, messageCount: 0 });
    expect(next.ui.speak).toBe(false);
  });
});

describe("normalize", () => {
  it("restores Main, rehomes orphans and repairs the active ids", () => {
    const env = makeEnv();
    const broken: Workspace = {
      v: 1,
      projects: [{ id: "p1", name: "Lab", color: COLORS[1], createdAt: 1 }],
      sessions: [{ id: "s1", projectId: "gone", title: "t", pinned: false, updatedAt: 1, messageCount: 1 }],
      activeProjectId: "p1",
      activeSessionId: "missing",
      ui: { railTab: "sessions", open: {}, tech: false, speak: true },
    };
    const fixed = normalize(broken, env);
    expect(fixed.projects.some((p) => p.id === MAIN_ID)).toBe(true);
    expect(fixed.sessions.find((s) => s.id === "s1")?.projectId).toBe(MAIN_ID);
    expect(findSession(fixed, fixed.activeSessionId)?.projectId).toBe(fixed.activeProjectId);
    expect(fixed.activeProjectId).toBe("p1");
  });
});
