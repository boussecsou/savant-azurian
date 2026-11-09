import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  StreamUnsupported,
  WarmupUnsupported,
  createRemoteProject,
  deleteRemoteSession,
  errorMessage,
  getNotionStatus,
  getRemoteProjects,
  getRemoteSessions,
  kindForStatus,
  parseSse,
  sendChat,
  streamChat,
  updateRemoteSession,
  warmUp,
  type StreamEvent,
} from "./api";

afterEach(() => vi.unstubAllGlobals());

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("kindForStatus", () => {
  it.each([
    [401, "auth"],
    [403, "auth"],
    [422, "invalid"],
    [502, "upstream"],
    [503, "upstream"],
    [504, "timeout"],
    [500, "unknown"],
  ])("maps %i to %s", (status, kind) => expect(kindForStatus(status)).toBe(kind));
});

describe("sendChat", () => {
  it("posts the message with the conversation id and returns the next one", async () => {
    const fetch = vi.fn().mockResolvedValue(json({ conversation_id: "resp_2", reply: "Bonjour" }));
    vi.stubGlobal("fetch", fetch);
    await expect(sendChat("Salut", "resp_1")).resolves.toEqual({ conversationId: "resp_2", reply: "Bonjour" });
    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe("/api/chat");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ message: "Salut", conversation_id: "resp_1", mode: "text" });
  });

  it("rejects a malformed reply as an upstream error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ reply: 3 })));
    await expect(sendChat("Salut", undefined)).rejects.toMatchObject({ kind: "upstream" });
  });

  it("maps HTTP failures to a kind", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({}, 504)));
    await expect(sendChat("Salut", undefined)).rejects.toMatchObject({ kind: "timeout" });
  });

  it("reports a network error when the request cannot be sent", async () => {
    const fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    vi.stubGlobal("fetch", fetch);
    await expect(sendChat("Salut", undefined)).rejects.toMatchObject({ kind: "network" });
    // No identity probe: the only call is the chat request itself.
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("reports an auth error when the BFF rejects the owner token", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({}, 401)));
    await expect(sendChat("Salut", undefined)).rejects.toMatchObject({ kind: "auth" });
  });
});

describe("getNotionStatus", () => {
  it("is true only for an explicit connected: true", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ connected: true })));
    await expect(getNotionStatus()).resolves.toBe(true);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ connected: "yes" })));
    await expect(getNotionStatus()).resolves.toBe(false);
  });

  it("surfaces an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({}, 401)));
    await expect(getNotionStatus()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("errorMessage", () => {
  it("never leaks technical details", () => {
    for (const kind of ["auth", "timeout", "upstream", "invalid", "network", "unknown"] as const) {
      expect(errorMessage(kind)).not.toMatch(/\d{3}|stack|undefined/i);
    }
  });
});

describe("parseSse", () => {
  const block = (event: unknown) => `data: ${JSON.stringify(event)}\n\n`;

  it("keeps the sign-in flag of a finished tool call, and only when it is true", () => {
    const text = block({ type: "tool", id: "c2", status: "done", consent: true }) + block({ type: "tool", id: "c3", status: "done", consent: "yes" });
    expect(parseSse(text).events).toEqual([
      { type: "tool", id: "c2", name: undefined, status: "done", consent: true },
      { type: "tool", id: "c3", name: undefined, status: "done" },
    ]);
  });

  it("returns complete events and keeps the unfinished tail", () => {
    const text = block({ type: "delta", text: "Bon" }) + block({ type: "tool", id: "c1", name: "notion-search", status: "running" });
    const { events, rest } = parseSse(text + 'data: {"type":"delta","te');
    expect(events).toEqual([
      { type: "delta", text: "Bon" },
      { type: "tool", id: "c1", name: "notion-search", status: "running" },
    ]);
    expect(rest).toBe('data: {"type":"delta","te');
  });

  it("accepts CRLF separators and skips unknown or malformed blocks", () => {
    const text = 'data: {"type":"delta","text":"a"}\r\n\r\n: ping\n\ndata: not json\n\ndata: {"type":"mystery"}\n\ndata: {"type":"delta","text":""}\n\n';
    expect(parseSse(text).events).toEqual([{ type: "delta", text: "a" }]);
  });

  it("maps done and error events", () => {
    const { events } = parseSse(block({ type: "done", conversation_id: "resp_3" }) + block({ type: "error", kind: "timeout" }) + block({ type: "error", kind: "weird" }));
    expect(events).toEqual([
      { type: "done", conversationId: "resp_3" },
      { type: "error", kind: "timeout" },
      { type: "error", kind: "upstream" },
    ]);
  });
});

function sse(...chunks: string[]) {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

describe("streamChat", () => {
  const data = (event: unknown) => `data: ${JSON.stringify(event)}\n\n`;

  it("reports events as they arrive, even when one is split across chunks", async () => {
    const full = data({ type: "delta", text: "Salut" });
    const fetch = vi.fn().mockResolvedValue(sse(full.slice(0, 12), full.slice(12), data({ type: "done", conversation_id: "resp_2" })));
    vi.stubGlobal("fetch", fetch);
    const seen: StreamEvent[] = [];
    await streamChat("Salut", "resp_1", (event) => seen.push(event));
    expect(seen).toEqual([{ type: "delta", text: "Salut" }, { type: "done", conversationId: "resp_2" }]);
    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe("/api/chat/stream");
    expect(JSON.parse(init.body)).toEqual({ message: "Salut", conversation_id: "resp_1", mode: "text" });
  });

  it("marks a spoken turn so the agent answers for the ear", async () => {
    const fetch = vi.fn().mockResolvedValue(sse(data({ type: "done", conversation_id: "resp_2" })));
    vi.stubGlobal("fetch", fetch);
    await streamChat("Météo ?", undefined, () => undefined, undefined, "voice");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ message: "Météo ?", mode: "voice" });
  });

  it("rejects with the error kind sent by the BFF", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sse(data({ type: "delta", text: "Bon" }), data({ type: "error", kind: "timeout" }))));
    const seen: StreamEvent[] = [];
    await expect(streamChat("Salut", undefined, (event) => seen.push(event))).rejects.toMatchObject({ kind: "timeout" });
    expect(seen).toEqual([{ type: "delta", text: "Bon" }]);
  });

  it("treats a stream that ends without `done` as a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sse(data({ type: "delta", text: "Bon" }))));
    await expect(streamChat("Salut", undefined, () => undefined)).rejects.toMatchObject({ kind: "network" });
  });

  it("signals an older BFF without the route, and maps other statuses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
    await expect(streamChat("x", undefined, () => undefined)).rejects.toBeInstanceOf(StreamUnsupported);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 504 })));
    await expect(streamChat("x", undefined, () => undefined)).rejects.toMatchObject({ kind: "timeout" });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(streamChat("x", undefined, () => undefined)).rejects.toMatchObject({ kind: "network" });
  });
});

describe("warmUp", () => {
  it("posts to the warm-up route and reports readiness", async () => {
    const fetch = vi.fn().mockResolvedValue(json({ ready: true }));
    vi.stubGlobal("fetch", fetch);
    await expect(warmUp()).resolves.toEqual({ ready: true });
    expect(fetch.mock.calls[0][0]).toBe("/api/warmup");
    expect(fetch.mock.calls[0][1].method).toBe("POST");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ ready: false })));
    await expect(warmUp()).resolves.toEqual({ ready: false });
  });

  it("hands over the warm conversation when the BFF provides one", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ ready: true, conversation_id: "caresp_1" })));
    await expect(warmUp()).resolves.toEqual({ ready: true, conversationId: "caresp_1" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ ready: true, conversation_id: "bad id/.." })));
    await expect(warmUp()).resolves.toEqual({ ready: true });
  });
});

describe("warmUp on an older BFF", () => {
  it("reports a missing route separately from a failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
    await expect(warmUp()).rejects.toBeInstanceOf(WarmupUnsupported);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 502 })));
    await expect(warmUp()).rejects.toMatchObject({ kind: "upstream" });
  });
});

describe("chat with server-side sessions", () => {
  it("adds session_id to /api/chat only when it is given", async () => {
    const fetch = vi.fn();
    fetch.mockImplementation(async () => json({ conversation_id: "resp_2", reply: "ok" }));
    vi.stubGlobal("fetch", fetch);
    await sendChat("Salut", "resp_1", undefined, "text", "s1");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      message: "Salut",
      conversation_id: "resp_1",
      mode: "text",
      session_id: "s1",
    });
    await sendChat("Salut", "resp_1");
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ message: "Salut", conversation_id: "resp_1", mode: "text" });
  });

  it("adds session_id to the stream only when it is given", async () => {
    const data = (event: unknown) => `data: ${JSON.stringify(event)}\n\n`;
    const fetch = vi.fn();
    fetch.mockImplementation(async () => sse(data({ type: "done", conversation_id: "resp_2" })));
    vi.stubGlobal("fetch", fetch);
    await streamChat("Salut", undefined, () => undefined, undefined, "text", "s1");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ message: "Salut", mode: "text", session_id: "s1" });
    await streamChat("Salut", undefined, () => undefined);
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ message: "Salut", mode: "text" });
  });
});

describe("workspace routes", () => {
  it("reports sync disabled on 404 or when the BFF is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
    await expect(getRemoteProjects()).resolves.toBeUndefined();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(getRemoteProjects()).resolves.toBeUndefined();
  });

  it("maps well-formed projects and drops malformed rows", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        json([
          { id: "main", name: "Main", color: "#6c80f2", system: true, createdAt: 1 },
          { id: "", name: "Bad", createdAt: 2 },
        ]),
      ),
    );
    await expect(getRemoteProjects()).resolves.toEqual([
      { id: "main", name: "Main", color: "#6c80f2", system: true, createdAt: 1 },
    ]);
  });

  it("reads sessions for a project and writes project/session metadata", async () => {
    const fetch = vi.fn();
    fetch.mockImplementation(async () => json([{ id: "s1", projectId: "main", title: "T", pinned: true, updatedAt: 3, messageCount: 2 }]));
    vi.stubGlobal("fetch", fetch);
    await expect(getRemoteSessions("main")).resolves.toEqual([
      { id: "s1", projectId: "main", title: "T", pinned: true, updatedAt: 3, messageCount: 2 },
    ]);
    expect(fetch.mock.calls[0][0]).toBe("/api/sessions?project=main");

    const writes = vi.fn();
    writes.mockImplementation(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", writes);
    await createRemoteProject({ id: "p1", name: "Lab", color: "#3cb98a" });
    expect(writes.mock.calls[0][0]).toBe("/api/projects");
    expect(writes.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(writes.mock.calls[0][1].body)).toEqual({ id: "p1", name: "Lab", color: "#3cb98a" });

    await updateRemoteSession("s1", { pinned: false });
    expect(writes.mock.calls[1][0]).toBe("/api/sessions/s1");
    expect(writes.mock.calls[1][1].method).toBe("PATCH");

    await deleteRemoteSession("s1");
    expect(writes.mock.calls[2][0]).toBe("/api/sessions/s1");
    expect(writes.mock.calls[2][1].method).toBe("DELETE");
  });
});
