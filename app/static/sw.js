/* Service worker de Guilda Work. Caché: SOLO los recursos estáticos (/static/); nunca toca páginas, API, formularios
   ni nada con sesión: todo lo que no sea un GET a /static/ va directo a la red. Además muestra los avisos push (Web Push)
   y, al tocarlos, abre la pantalla del aviso. */
const CACHE = "gw-estaticos-1";
const MAXIMO = 250;                                   // entradas; al pasarse se borran las más antiguas

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k.startsWith("gw-estaticos-") && k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

async function recortar(cache) {
  const claves = await cache.keys();
  for (const k of claves.slice(0, Math.max(0, claves.length - MAXIMO))) await cache.delete(k);
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || req.headers.has("range")) return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith("/static/")) return;

  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const guardada = await cache.match(req);
    // URL versionada (?v=<mtime>): cambia con cada despliegue, así que lo guardado nunca puede ser antiguo.
    if (guardada && url.searchParams.has("v")) return guardada;
    // Sin versión (fuentes e iconos que pide el CSS): se sirve lo guardado y se refresca por detrás.
    const red = fetch(req).then((r) => {
      if (r.ok && r.type === "basic") { cache.put(req, r.clone()).then(() => recortar(cache)); }
      return r;
    });
    if (guardada) { red.catch(() => {}); return guardada; }
    return red;
  })());
});

// --- Avisos push: la carga la fabrica el servidor (app/push.py): {titulo, cuerpo, url (ruta propia), tag}
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { titulo: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.titulo || "Guilda Work", {
    body: d.cuerpo || "",
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
    tag: d.tag || "guilda",
    data: { url: d.url && d.url.startsWith("/") && !d.url.startsWith("//") ? d.url : "/hoy/" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const destino = new URL(e.notification.data && e.notification.data.url || "/hoy/", self.location.origin).href;
  e.waitUntil((async () => {
    const ventanas = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const v of ventanas) {
      if (new URL(v.url).origin === self.location.origin && "focus" in v) { await v.focus(); if ("navigate" in v) await v.navigate(destino); return; }
    }
    await self.clients.openWindow(destino);
  })());
});
