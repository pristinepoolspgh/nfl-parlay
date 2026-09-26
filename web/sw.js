// Network first, so a Home Screen launch always gets the newest board
// when there's signal; the last good copy is the fallback offline.
const CACHE = "pb-v1";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  e.respondWith(
    fetch(req).then(res => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req.mode === "navigate" ? "/" : req, copy));
      }
      return res;
    }).catch(() => caches.match(req.mode === "navigate" ? "/" : req)
      .then(m => m || caches.match("/")))
  );
});

// Alerts from the board's push service (supabase/functions/parlay-push).
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; }
  catch (_) { d = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "Parlay Board", {
    body: d.body || "",
    tag: d.tag || "pb",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { url: d.url || "/" },
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true })
    .then(ws => {
      for (const w of ws) {
        if ("focus" in w) return w.focus().then(f => f.navigate ? f.navigate(url) : f);
      }
      return clients.openWindow(url);
    }));
});
