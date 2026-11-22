// Speicherpunkt: Offline-Cache. Bei jeder neuen Version VERSION erhöhen.
const VERSION = "sp-v10";
const FILES = ["./", "index.html", "manifest.webmanifest", "icons/favicon.svg", "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png", "fonts/lora.woff2", "fonts/lora-italic.woff2", "fonts/inter-400.woff2", "fonts/inter-500.woff2", "fonts/inter-600.woff2"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
// Netz zuerst (damit Updates sofort ankommen), sonst aus dem Cache
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET" || new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(
    fetch(e.request).then(r => {
      const copy = r.clone();
      if (r.ok) caches.open(VERSION).then(c => c.put(e.request, copy));
      return r;
    }).catch(() => caches.match(e.request).then(r => r || caches.match("index.html")))
  );
});

// Erinnerung anzeigen. Der Inhalt kommt verschlüsselt vom Server: t = Projekt, b = nächster Schritt, p = Projekt-Nummer.
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch {}
  e.waitUntil(self.registration.showNotification(String(d.t || "Speicherpunkt").slice(0, 80), {
    body: String(d.b || "Dein nächster Schritt wartet.").slice(0, 240),
    tag: d.p ? "sp-" + d.p : "sp", icon: "icons/icon-192.png", badge: "icons/icon-192.png", data: { p: typeof d.p === "string" ? d.p : "" }
  }));
});
// Tipp auf die Mitteilung: App öffnen (oder nach vorne holen) und das Projekt zeigen.
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const p = (e.notification.data && e.notification.data.p) || "";
  const url = new URL(p ? "./?p=" + encodeURIComponent(p) : "./", self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    const open = list.find(c => c.url.startsWith(self.registration.scope) && "focus" in c);
    if (open) { if (p) open.postMessage({ open: p }); return open.focus(); }
    return self.clients.openWindow(url);
  }));
});
