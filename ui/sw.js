// Service worker for the AKARI PWA. Network-first, cached shell for offline.
// Only same-origin GET navigations and /assets/* are ever cached. API calls
// (/diagnose, /admin/*, /feedback/*) and cross-origin requests pass straight
// through to the network and are never stored.
const CACHE = "akari-v1";
const SHELL = ["/", "/manifest.webmanifest", "/assets/pwa/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL))
      .catch(() => {})
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function cacheable(req, url) {
  if (req.mode === "navigate") return true;
  return url.pathname.startsWith("/assets/") || url.pathname === "/manifest.webmanifest";
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (!cacheable(req, url)) return;

  e.respondWith(
    fetch(req)
      .then((res) => {
        // Only cache good basic responses. An auth redirect or a 5xx must
        // never be written into the shell or it gets served offline.
        if (res && res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(req).then((r) => r || (req.mode === "navigate" ? caches.match("/") : undefined)))
  );
});
