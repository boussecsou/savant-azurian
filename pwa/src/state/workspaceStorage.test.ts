import { describe, expect, it } from "vitest";
import { LEGACY_CHAT_KEY, MAX_STORED_MESSAGES, MESSAGES_PREFIX, WORKSPACE_KEY, createBrowserStore, parseWorkspace } from "./workspaceStorage";
import { COLORS, MAIN_ID, createWorkspace, reduce, type Env, type StoredMessage } from "./workspace";

function makeEnv(): Env {
  let n = 0;
  return { now: 10_000, id: () => `id${++n}` };
}

class FakeStorage {
  data = new Map<string, string>();
  /** Keys that refuse to be written, like a full quota. */
  full = new Set<string>();
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    if (this.full.has(key)) throw new Error("QuotaExceededError");
    this.data.set(key, value);
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
}

const legacy = (extra: object = {}) =>
  JSON.stringify({
    messages: [
      { id: "m1", role: "user", text: "Plan my **week**" },
      { id: "m2", role: "assistant", text: "Sure." },
    ],
    conversationId: "caresp_old",
    ...extra,
  });

describe("workspace storage", () => {
  it("starts fresh with Main when nothing is stored", () => {
    const store = createBrowserStore(new FakeStorage());
    const w = store.loadWorkspace(makeEnv());
    expect(w.projects.map((p) => p.id)).toEqual([MAIN_ID]);
    expect(w.sessions).toHaveLength(1);
  });

  it("round-trips a workspace", () => {
    const storage = new FakeStorage();
    const env = makeEnv();
    const store = createBrowserStore(storage);
    const w = reduce(createWorkspace(env), { type: "createProject", name: "Lab", color: COLORS[2] }, env);
    store.saveWorkspace(w);
    expect(store.loadWorkspace(makeEnv())).toEqual(w);
  });

  it("migrates the old single conversation into a Main session, then removes the old key", () => {
    const storage = new FakeStorage();
    storage.data.set(LEGACY_CHAT_KEY, legacy());
    const store = createBrowserStore(storage);
    const w = store.loadWorkspace(makeEnv());

    expect(w.sessions).toHaveLength(1);
    const session = w.sessions[0];
    expect(session).toMatchObject({ projectId: MAIN_ID, title: "Plan my week", messageCount: 2, conversationId: "caresp_old" });
    expect(w.activeSessionId).toBe(session.id);
    expect(store.loadMessages(session.id).map((m) => m.text)).toEqual(["Plan my **week**", "Sure."]);
    expect(storage.data.has(LEGACY_CHAT_KEY)).toBe(false);
    expect(storage.data.has(WORKSPACE_KEY)).toBe(true);
  });

  it("migrates only once: the next load reads the new workspace", () => {
    const storage = new FakeStorage();
    storage.data.set(LEGACY_CHAT_KEY, legacy());
    const store = createBrowserStore(storage);
    const first = store.loadWorkspace(makeEnv());
    expect(store.loadWorkspace(makeEnv())).toEqual(first);
  });

  it("keeps the old conversation when the new data cannot be written", () => {
    const storage = new FakeStorage();
    storage.data.set(LEGACY_CHAT_KEY, legacy());
    storage.full.add(WORKSPACE_KEY);
    const w = createBrowserStore(storage).loadWorkspace(makeEnv());
    expect(w.sessions[0].messageCount).toBe(2);
    expect(storage.data.has(LEGACY_CHAT_KEY)).toBe(true);
  });

  it("does not create a session from an empty old chat", () => {
    const storage = new FakeStorage();
    storage.data.set(LEGACY_CHAT_KEY, JSON.stringify({ messages: [] }));
    const w = createBrowserStore(storage).loadWorkspace(makeEnv());
    expect(w.sessions[0].messageCount).toBe(0);
  });

  it("falls back to a fresh workspace on corrupt data", () => {
    const storage = new FakeStorage();
    storage.data.set(WORKSPACE_KEY, "{not json");
    const w = createBrowserStore(storage).loadWorkspace(makeEnv());
    expect(w.projects.map((p) => p.id)).toEqual([MAIN_ID]);
  });

  it("repairs a stored workspace that lost Main or points at nothing", () => {
    const w = parseWorkspace(
      JSON.stringify({ v: 1, projects: [{ id: "p1", name: "Lab", color: "#nope" }], sessions: [{ id: "s1", projectId: "p1", title: "T" }], activeProjectId: "zzz", activeSessionId: "zzz", ui: { railTab: "weird" } }),
      makeEnv(),
    )!;
    expect(w.projects.map((p) => p.id)).toEqual([MAIN_ID, "p1"]);
    expect(w.projects[1].color).toBe(COLORS[0]);
    expect(w.ui.railTab).toBe("sessions");
    expect(w.sessions.some((s) => s.id === w.activeSessionId)).toBe(true);
  });

  it("rejects another version", () => {
    expect(parseWorkspace(JSON.stringify({ v: 2, projects: [], sessions: [] }), makeEnv())).toBeUndefined();
  });
});

describe("message storage", () => {
  const message = (i: number): StoredMessage => ({ id: `m${i}`, role: i % 2 ? "assistant" : "user", text: `t${i}`, at: i });

  it("keeps the last 100 messages and drops everything but the text", () => {
    const storage = new FakeStorage();
    const store = createBrowserStore(storage);
    const many = Array.from({ length: 130 }, (_, i) => ({ ...message(i), tools: [{ id: "x" }], streaming: true }) as StoredMessage);
    store.saveMessages("s1", many);
    const back = store.loadMessages("s1");
    expect(back).toHaveLength(MAX_STORED_MESSAGES);
    expect(back[0].id).toBe("m30");
    expect(back[0]).not.toHaveProperty("tools");
    expect(back[0]).not.toHaveProperty("streaming");
  });

  it("deletes a session's messages", () => {
    const storage = new FakeStorage();
    const store = createBrowserStore(storage);
    store.saveMessages("s1", [message(1)]);
    store.deleteSession("s1");
    expect(storage.data.has(MESSAGES_PREFIX + "s1")).toBe(false);
    expect(store.loadMessages("s1")).toEqual([]);
  });

  it("ignores malformed stored messages", () => {
    const storage = new FakeStorage();
    storage.data.set(MESSAGES_PREFIX + "s1", JSON.stringify([{ id: "a", role: "user", text: "ok", at: 1 }, { id: 2 }, null, { id: "b", role: "robot", text: "x" }]));
    expect(createBrowserStore(storage).loadMessages("s1").map((m) => m.id)).toEqual(["a"]);
  });
});

describe("unavailable storage", () => {
  it("never throws without storage", () => {
    const store = createBrowserStore(undefined);
    const w = store.loadWorkspace(makeEnv());
    expect(() => store.saveWorkspace(w)).not.toThrow();
    expect(() => store.saveMessages("s", [])).not.toThrow();
    expect(store.loadMessages("s")).toEqual([]);
    expect(() => store.deleteSession("s")).not.toThrow();
  });

  it("never throws when every call throws", () => {
    const hostile = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    };
    const store = createBrowserStore(hostile);
    const w = store.loadWorkspace(makeEnv());
    expect(w.projects).toHaveLength(1);
    expect(() => store.saveWorkspace(w)).not.toThrow();
    expect(() => store.saveMessages("s", [])).not.toThrow();
    expect(() => store.deleteSession("s")).not.toThrow();
  });
});
