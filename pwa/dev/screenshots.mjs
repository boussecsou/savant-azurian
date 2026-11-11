// Takes the screenshots of the user guide from a running web client, with the installed Chromium
// driven over the Chrome DevTools Protocol (no extra dependency: `ws` ships with Vite).
//
//   npm run dev:mock -- --port 5199 --host 127.0.0.1        # in one terminal
//   CHROME=/path/to/chrome node dev/screenshots.mjs [outDir] [url]
//   CHROME=... SA2_SHOTS_SCRIPT=/abs/path/steps.mjs node dev/screenshots.mjs   # your own steps
//
// Not part of the product or of CI: it exists so the guide's images can be regenerated.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import WebSocket from "ws";

const chrome = process.env.CHROME;
if (!chrome) throw new Error("Set CHROME to the path of a Chromium or Chrome binary.");
const outDir = process.argv[2] ?? "../docs/assets/user-guide";
const url = process.argv[3] ?? "http://127.0.0.1:5199/";
const port = 9333;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

mkdirSync(outDir, { recursive: true });
const profile = mkdtempSync(join(tmpdir(), "sa2-shots-"));
const browser = spawn(
  chrome,
  [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--hide-scrollbars",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    "--window-size=1440,900",
    "about:blank",
  ],
  { stdio: "ignore" },
);

async function target() {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = list.find((entry) => entry.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {
      /* not ready yet */
    }
    await sleep(200);
  }
  throw new Error("Chromium did not start");
}

const socket = new WebSocket(await target());
await new Promise((resolve) => socket.on("open", resolve));
let counter = 0;
const waiting = new Map();
socket.on("message", (data) => {
  const message = JSON.parse(data);
  if (message.id && waiting.has(message.id)) waiting.get(message.id)(message);
});
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++counter;
    waiting.set(id, (message) => (message.error ? reject(new Error(message.error.message)) : resolve(message.result)));
    socket.send(JSON.stringify({ id, method, params }));
  });
const evaluate = async (expression) =>
  (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;

const helpers = {
  sleep,
  send,
  evaluate,
  async shot(name, scheme = "light") {
    await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: scheme }] });
    await sleep(300);
    const { data } = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(outDir, `${name}.png`), Buffer.from(data, "base64"));
    console.log("saved", `${name}.png`);
  },
  click: (text) =>
    evaluate(`(() => {
      const all = [...document.querySelectorAll('button, [role=button], a, [role=tab], [role=menuitem]')];
      const wanted = ${JSON.stringify(text.toLowerCase())};
      const el = all.find((e) => (e.getAttribute('aria-label') || e.textContent || '').trim().toLowerCase().includes(wanted));
      if (!el) return false;
      el.click();
      return true;
    })()`),
  focus: (selector) =>
    evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); if (!e) return false; e.focus(); return true; })()`),
  type: (text) => send("Input.insertText", { text }),
  async key(key, code, modifiers = 0) {
    await send("Input.dispatchKeyEvent", { type: "keyDown", key, code, modifiers, windowsVirtualKeyCode: key.length === 1 ? key.toUpperCase().charCodeAt(0) : 13 });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key, code, modifiers });
  },
  text: () => evaluate("document.body.innerText.slice(0, 2000)"),
  labels: () =>
    evaluate(`[...document.querySelectorAll('button, [role=button], [role=tab], textarea, input')]
      .map((e) => (e.getAttribute('aria-label') || e.textContent || e.placeholder || '').trim().slice(0, 40) + ' | ' + e.tagName).join('\\n')`),
};

await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url });
await sleep(2500);

try {
  if (process.env.SA2_SHOTS_SCRIPT) {
    await (await import(process.env.SA2_SHOTS_SCRIPT)).default(helpers);
  } else {
    await helpers.shot("first-screen");
    console.log(await helpers.labels());
  }
} finally {
  socket.close();
  browser.kill();
}
