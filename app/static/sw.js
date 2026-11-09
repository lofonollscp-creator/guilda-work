/* Service worker de Guilda Work. Caché: SOLO los recursos estáticos (/static/); nunca toca páginas, API, formularios
   ni nada con sesión: todo lo que no sea un GET a /static/ va directo a la red. Además muestra los avisos push (Web Push)
   y, al tocarlos, abre la pantalla del aviso. */
const CACHE = "gw-estaticos-1";
const OFFLINE = "gw-offline-1";                        // la pantalla «Sin conexión» del portal (igual para todos, sin datos de nadie) y lo que necesita para pintarse
const PAGINA_OFFLINE = "/portal/sin-conexion";
const MAXIMO = 250;                                   // entradas; al pasarse se borran las más antiguas

async function guardarPaginaOffline() {
  try {
    const r = await fetch(PAGINA_OFFLINE, { cache: "reload" });
    if (!r.ok) return;
    const html = await r.clone().text();
    const cache = await caches.open(OFFLINE);
    await cache.put(PAGINA_OFFLINE, r);
    const estaticos = Array.from(new Set(html.match(/\/static\/[^"'\s)]+/g) || []));
    const est = await caches.open(CACHE);
    await Promise.all(estaticos.map((u) => est.match(u).then((h) => h || fetch(u).then((x) => x.ok && est.put(u, x)))));
  } catch (_) { /* sin red al instalar: se guardará en la próxima visita */ }
}
let ultimaActualizacionOffline = 0;

self.addEventListener("install", (e) => { e.waitUntil(guardarPaginaOffline().then(() => self.skipWaiting())); });

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if ((k.startsWith("gw-estaticos-") && k !== CACHE) || (k.startsWith("gw-offline-") && k !== OFFLINE)) await caches.delete(k);
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
  // Páginas del portal: siempre de la red; solo si no hay conexión se enseña la pantalla «Sin conexión» (nunca se guarda ninguna página con datos de una persona).
  if (req.mode === "navigate" && url.origin === self.location.origin && url.pathname.startsWith("/portal/") && url.pathname !== PAGINA_OFFLINE) {
    e.respondWith(fetch(req).then((r) => {
      if (Date.now() - ultimaActualizacionOffline > 3600 * 1000) { ultimaActualizacionOffline = Date.now(); e.waitUntil(guardarPaginaOffline()); }
      return r;
    }).catch(async () => (await (await caches.open(OFFLINE)).match(PAGINA_OFFLINE)) || Response.error()));
    return;
  }
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
