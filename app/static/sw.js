/* Service worker de Guilda Work: SOLO guarda en caché los recursos estáticos (/static/).
   Nunca toca páginas, API, formularios ni nada con sesión: todo lo que no sea un GET a /static/ va directo a la red. */
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
