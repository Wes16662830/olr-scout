// OLR Scout service worker: app-shell cache + web push. API calls are never cached
// (prices must be live).
const SHELL = "olr-scout-shell-v2";
const BASE = new URL(self.registration.scope).pathname; // "/" locally, "/olr-scout/" on GitHub Pages

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll([BASE, BASE + "manifest.webmanifest", BASE + "icon.svg"])));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.includes("/api/")) return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const copy = r.clone();
        caches.open(SHELL).then((c) => c.put(e.request, copy));
        return r;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match(BASE)))
  );
});

self.addEventListener("push", (e) => {
  let data = { title: "OLR Scout", body: "Auction update" };
  try { data = e.data.json(); } catch (_) {}
  e.waitUntil(self.registration.showNotification(data.title || "OLR Scout", {
    body: data.body, icon: "/icon.svg", tag: `lot-${data.lot_id}-${data.kind}`, data,
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const id = e.notification.data && e.notification.data.lot_id;
  e.waitUntil(self.clients.openWindow(id ? `${BASE}lot/${id}` : BASE));
});
