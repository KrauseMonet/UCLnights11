/* The service worker: it makes the site installable and repeat visits quick. It does not
   make the game playable offline, because every draft and room needs the API; an
   installed icon that opened onto a broken page would be worse than none. The rules are
   the cricket site's (its A132):

   1. /api/* is never cached. A room is polled every few seconds and a cached reply would
      be a wrong answer, not a stale one.
   2. Pages are network first; the cache is only for being offline. Pages are served
      must-revalidate so a deploy shows at once, and a cache-first worker would undo that.
   3. Scripts and styles carry a content hash in their URL (tools.stamp_assets), so they
      are cache first: a hit is by definition the right file for the page that asked.
      Other static files (crests, brand, fonts) are shown from the cache and refreshed
      behind it, since their URLs don't change when they do. */

const VERSION = "uclnights11-v1";
const SHELL = `${VERSION}-shell`;
const ASSETS = `${VERSION}-assets`;
const PAGES = `${VERSION}-pages`;
const PRECACHE = ["/offline", "/static/brand/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(PRECACHE)).catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((names) => Promise.all(names.filter((n) => !n.startsWith(VERSION)).map((n) => caches.delete(n))))
    .then(() => self.clients.claim()));
});

function keep(cache, req, res) {
  if (res.ok) { const copy = res.clone(); caches.open(cache).then((c) => c.put(req, copy)); }
  return res;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;                     // a pick must always reach the server
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;         // rule 1

  if (url.pathname.startsWith("/static/")) {
    if (url.searchParams.has("v")) {                    // rule 3: hashed, cache first
      event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => keep(ASSETS, req, res))));
    } else {                                            // unhashed: cached copy now, fresh one for next time
      event.respondWith(caches.match(req).then((hit) => {
        const fresh = fetch(req).then((res) => keep(ASSETS, req, res));
        if (!hit) return fresh;
        fresh.catch(() => {});                          // offline: the cached copy stands
        return hit;
      }));
    }
    return;
  }

  if (req.mode === "navigate") {                        // rule 2
    event.respondWith(fetch(req).then((res) => keep(PAGES, req, res))
      .catch(() => caches.match(req).then((hit) => hit || caches.match("/offline"))));
  }
});
