// A stand-in for the backend (BFF), so the web client can run with no Azure resource and no sign-in.
// It answers with canned, clearly simulated replies. It speaks the same vocabulary as the real
// /api/chat/stream (delta, tool, done, error) and reports Notion as connected.
// Not part of the product: development, demos and the screenshots of the user guide only.
import { createServer } from "node:http";

const REPLIES = [
  {
    match: /task|notion|todo|to-do/i,
    tool: "notion-search",
    text: "(Simulated reply) I found 3 tasks in your Notion workspace. This is canned text from the local mock backend, not a real agent.",
  },
  {
    match: /vm|server|load|ssh/i,
    tool: "ssh_exec",
    text: "(Simulated reply) The VM load is 0.08, 0.12, 0.09. This is canned text from the local mock backend.",
  },
  {
    match: /./,
    tool: null,
    text: "(Simulated reply) Hello! I am the local mock backend. Run the real agent to get real answers.",
  },
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function json(response, status, body) {
  response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
  response.end(JSON.stringify(body));
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  } catch {
    return {};
  }
}

function pick(message) {
  return REPLIES.find((reply) => reply.match.test(message)) ?? REPLIES[REPLIES.length - 1];
}

async function stream(response, message) {
  response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-store" });
  const send = (event) => response.write(`data: ${JSON.stringify(event)}\n\n`);
  const reply = pick(message);
  if (reply.tool) {
    send({ type: "tool", id: "call-1", name: reply.tool, status: "running" });
    await sleep(700);
    send({ type: "tool", id: "call-1", status: "done" });
  }
  for (const word of reply.text.split(/(?<= )/)) {
    send({ type: "delta", text: word });
    await sleep(25);
  }
  send({ type: "done", conversation_id: `mock-${Date.now()}` });
  response.end();
}

export function createMockBff() {
  return createServer(async (request, response) => {
    const path = new URL(request.url ?? "/", "http://localhost").pathname;
    if (path === "/readiness") return json(response, 200, { status: "ready" });
    if (path === "/api/oauth/notion/status") return json(response, 200, { connected: true });
    if (path === "/api/warmup") return json(response, 200, { ready: true });
    if (path === "/api/chat/stream" && request.method === "POST") {
      const body = await readBody(request);
      return stream(response, String(body.message ?? ""));
    }
    if (path === "/api/chat" && request.method === "POST") {
      const body = await readBody(request);
      return json(response, 200, { conversation_id: `mock-${Date.now()}`, reply: pick(String(body.message ?? "")).text });
    }
    if (/^\/api\/projects\/[^/]+\/documents$/.test(path) && request.method === "GET") return json(response, 200, []);
    // Projects, sessions and speech are not mocked: the web client then keeps its data on this device.
    return json(response, 404, { detail: "Not mocked" });
  });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.env.MOCK_BFF_PORT ?? 8091);
  createMockBff().listen(port, "127.0.0.1", () => console.log(`Mock BFF on http://127.0.0.1:${port}`));
}
