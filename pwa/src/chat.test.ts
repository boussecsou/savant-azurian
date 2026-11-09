import { describe, expect, it } from "vitest";
import { fromStored, loadChat, toStored } from "./chat";

function memory(initial?: string) {
  const data = new Map<string, string>(initial === undefined ? [] : [["sa2-chat-v1", initial]]);
  return { getItem: (key: string) => data.get(key) ?? null };
}

describe("legacy chat reader", () => {
  it("reads messages and the conversation id of the old storage", () => {
    const raw = JSON.stringify({ messages: [{ id: "1", role: "user", text: "Salut", extra: "dropped" }], conversationId: "resp_1" });
    expect(loadChat(memory(raw))).toEqual({ messages: [{ id: "1", role: "user", text: "Salut" }], conversationId: "resp_1" });
  });

  it("ignores error notices", () => {
    const raw = JSON.stringify({ messages: [{ id: "1", role: "assistant", text: "", error: "timeout" }] });
    expect(loadChat(memory(raw)).messages).toEqual([]);
  });

  it("keeps only the most recent 100 messages", () => {
    const messages = Array.from({ length: 130 }, (_, i) => ({ id: String(i), role: "user", text: "m" }));
    const loaded = loadChat(memory(JSON.stringify({ messages }))).messages;
    expect(loaded).toHaveLength(100);
    expect(loaded[0].id).toBe("30");
  });

  it.each(["not json", '{"messages":"nope"}', '{"messages":[{"role":"system","text":"x","id":"1"}]}'])(
    "survives corrupt data: %s",
    (raw) => expect(loadChat(memory(raw)).messages).toEqual([]),
  );

  it("survives missing storage", () => {
    expect(loadChat(undefined).messages).toEqual([]);
  });
});

describe("stored messages", () => {
  it("keeps text, channel and date, and drops live-turn details", () => {
    const stored = toStored(
      { id: "1", role: "assistant", text: "Voici", voice: true, streaming: true, live: true, tools: [{ id: "c", name: "notion-search", status: "done" }], trace: { agent: 900 } },
      42,
    );
    expect(stored).toEqual({ id: "1", role: "assistant", text: "Voici", voice: true, at: 42 });
  });

  it("round-trips", () => {
    const stored = { id: "1", role: "user" as const, text: "Hi", at: 7 };
    expect(toStored(fromStored(stored), 0)).toEqual(stored);
  });
});
