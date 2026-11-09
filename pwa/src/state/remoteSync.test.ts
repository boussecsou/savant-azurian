import { describe, expect, it } from "vitest";
import {
  COLORS,
  MAIN_ID,
  createWorkspace,
  reduce,
  type Env,
  type Project,
  type Workspace,
} from "./workspace";
import {
  forgetProject,
  forgetSession,
  planSync,
  snapshotFromServer,
  toProjects,
  toSessions,
  wasProjectSynced,
  wasSessionSynced,
} from "./remoteSync";

function makeEnv(start = 1000): Env {
  let n = 0;
  return { now: start, id: () => `id${++n}` };
}

function run(workspace: Workspace, env: Env, ...actions: Parameters<typeof reduce>[1][]): Workspace {
  return actions.reduce((w, action) => reduce(w, action, env), workspace);
}

describe("planSync", () => {
  it("sends nothing when the server already holds the workspace", () => {
    const env = makeEnv();
    const w = createWorkspace(env);
    const snapshot = snapshotFromServer(w.projects, w.sessions);
    expect(planSync(w, snapshot)).toEqual({
      createProjects: [],
      updateProjects: [],
      createSessions: [],
      updateSessions: [],
    });
  });

  it("creates a project and its sessions, but leaves untouched sessions local", () => {
    const env = makeEnv();
    const w = createWorkspace(env);
    const snapshot = snapshotFromServer(w.projects, w.sessions);
    const withLab = run(w, env, { type: "createProject", name: "Lab", color: COLORS[1] });

    const plan = planSync(withLab, snapshot);
    expect(plan.createProjects.map((p) => p.name)).toEqual(["Lab"]);
    // createProject also makes an empty session: it waits for ensureSession.
    expect(plan.createSessions).toEqual([]);
  });

  it("creates a session once it has messages", () => {
    const env = makeEnv();
    const w = createWorkspace(env);
    const snapshot = snapshotFromServer(w.projects, []);
    const used = run(w, env, { type: "turn", sessionId: w.activeSessionId, role: "user", text: "Hello" });

    const plan = planSync(used, snapshot);
    expect(plan.createSessions.map((s) => s.id)).toEqual([w.activeSessionId]);
    expect(plan.createSessions[0].messageCount).toBe(1);
  });

  it("updates a renamed project", () => {
    const env = makeEnv();
    const w = createWorkspace(env);
    const snapshot = snapshotFromServer(w.projects, w.sessions);
    const renamed = run(w, env, { type: "renameProject", id: MAIN_ID, name: "Home" });
    expect(planSync(renamed, snapshot).updateProjects).toEqual([{ id: MAIN_ID, name: "Home" }]);
  });

  it("patches a renamed, pinned or moved session", () => {
    const env = makeEnv();
    const w = createWorkspace(env);
    const id = w.activeSessionId;
    const lab: Project = { id: "lab", name: "Lab", color: COLORS[2], createdAt: 1 };
    const withLab: Workspace = { ...w, projects: [...w.projects, lab] };
    const snapshot = snapshotFromServer(withLab.projects, withLab.sessions);

    expect(planSync(run(withLab, env, { type: "renameSession", id, title: "Plan" }), snapshot).updateSessions).toEqual([
      { id, title: "Plan", titleEdited: true },
    ]);
    expect(planSync(run(withLab, env, { type: "pinSession", id, pinned: true }), snapshot).updateSessions).toEqual([
      { id, pinned: true },
    ]);
    expect(planSync(run(withLab, env, { type: "moveSession", id, projectId: "lab" }), snapshot).updateSessions).toEqual([
      { id, projectId: "lab" },
    ]);
  });

  it("sends nothing for a session that disappeared locally; discard is the only delete", () => {
    const env = makeEnv();
    const w = createWorkspace(env);
    const id = w.activeSessionId;
    const snapshot = snapshotFromServer(w.projects, w.sessions);
    const deleted = run(w, env, { type: "deleteSession", id });

    const plan = planSync(deleted, snapshot);
    expect(plan).toEqual({ createProjects: [], updateProjects: [], createSessions: [], updateSessions: [] });
    expect(wasSessionSynced(snapshot, id)).toBe(true);

    // After the Undo window, discard drops the server copy.
    expect(wasSessionSynced(forgetSession(snapshot, id), id)).toBe(false);
  });

  it("waits for discard before dropping a project and its sessions server-side", () => {
    const env = makeEnv();
    const w = createWorkspace(env);
    const withLab = run(w, env, { type: "createProject", name: "Lab", color: COLORS[1] });
    const lab = withLab.projects[1];
    const snapshot = snapshotFromServer(withLab.projects, withLab.sessions);

    const deleted = run(withLab, env, { type: "deleteProject", id: lab.id });
    expect(planSync(deleted, snapshot)).toEqual({
      createProjects: [],
      updateProjects: [],
      createSessions: [],
      updateSessions: [],
    });
    expect(wasProjectSynced(snapshot, lab.id)).toBe(true);

    const afterDiscard = forgetProject(snapshot, lab.id);
    expect(wasProjectSynced(afterDiscard, lab.id)).toBe(false);
    expect(Object.values(afterDiscard.sessions).some((s) => s.projectId === lab.id)).toBe(false);
  });
});

describe("server mapping", () => {
  it("repairs colours, marks Main as a system project and drops duplicates", () => {
    const projects = toProjects([
      { id: MAIN_ID, name: "Main", color: "not-a-colour", createdAt: 1 },
      { id: MAIN_ID, name: "Main again", color: COLORS[0], createdAt: 1 },
    ]);
    expect(projects).toEqual([{ id: MAIN_ID, name: "Main", color: COLORS[0], system: true, createdAt: 1 }]);
  });

  it("gives a session its default title and history count", () => {
    const sessions = toSessions([
      { id: "s1", projectId: MAIN_ID, title: " ", pinned: false, updatedAt: 2, messageCount: 3.7 },
    ]);
    expect(sessions[0]).toMatchObject({ title: "New session", messageCount: 3 });
  });
});
