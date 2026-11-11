import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, expect, test } from "vitest";
// @ts-expect-error plain JavaScript module without types
import { createMockBff } from "./mock-bff.mjs";

const server = createMockBff();
let base = "";

beforeAll(async () => {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
afterAll(() => new Promise((resolve) => server.close(resolve)));

test("reports Notion as connected and the agent as ready", async () => {
  expect(await (await fetch(`${base}/api/oauth/notion/status`)).json()).toEqual({ connected: true });
  expect(await (await fetch(`${base}/api/warmup`, { method: "POST" })).json()).toEqual({ ready: true });
});

test("streams tool steps, text and a final done event for a Notion request", async () => {
  const response = await fetch(`${base}/api/chat/stream`, { method: "POST", body: JSON.stringify({ message: "list my tasks" }) });
  const events = (await response.text())
    .split("\n\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line.replace(/^data: /, "")));
  expect(events[0]).toMatchObject({ type: "tool", name: "notion-search", status: "running" });
  expect(events.some((event) => event.type === "delta")).toBe(true);
  expect(events.at(-1)).toMatchObject({ type: "done" });
});

test("does not mock projects, so the web client keeps its data locally", async () => {
  expect((await fetch(`${base}/api/projects`)).status).toBe(404);
});
