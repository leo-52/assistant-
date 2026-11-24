/* Service worker de l'appli Bourse : réseau d'abord (les mises à jour arrivent tout de suite), copie locale en secours hors ligne. */
const VERSION = "v1";
const COQUE = ["./", "index.html", "manifest.webmanifest", "icones/icone-192.png", "icones/icone-180.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open("coque-" + VERSION).then(c => c.addAll(COQUE)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(cles => Promise.all(cles.filter(k => !k.endsWith("-" + VERSION)).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  const donnees = u.pathname.includes("/data/");
  const cache = (donnees ? "data-" : "coque-") + VERSION;
  const cle = donnees ? u.pathname : e.request;
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const copie = r.clone(); caches.open(cache).then(c => c.put(cle, copie)); }
    return r;
  }).catch(() => caches.match(cle, { ignoreSearch: true }).then(r => r || Response.error())));
});
/* Notifications poussées (étape suivante) : affiche le message reçu, ouvre l'appli au toucher. */
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data.json(); } catch { d = { title: "Bourse", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "Bourse", {
    body: d.body || "", tag: d.tag, icon: "icones/icone-192.png", data: { url: d.url || "./" } }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(self.clients.openWindow(e.notification.data && e.notification.data.url || "./"));
});
