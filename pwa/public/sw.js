// Minimal service worker: makes the app installable and quick to reopen.
// It never touches /api, so chat and the Notion connection always hit the network.
// Bump the version whenever a file under /icons changes: icons are cached first and keep their names.
const SHELL = "sa2-shell-v2";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      for (const key of await caches.keys()) {
        if (key.startsWith("sa2-") && key !== SHELL) await caches.delete(key);
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(openPage(request));
  } else if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    // Build output is fingerprinted, so a cached copy never goes stale.
    event.respondWith(cacheFirst(request));
  }
});

async function openPage(request) {
  try {
    const response = await fetch(request);
    // Only a real page is kept: never a sign-in redirect or an error.
    if (response.ok && response.type === "basic") {
      (await caches.open(SHELL)).put("/index.html", response.clone());
    }
    return response;
  } catch {
    return (await caches.match("/index.html")) || Response.error();
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok && response.type === "basic") {
    (await caches.open(SHELL)).put(request, response.clone());
  }
  return response;
}
