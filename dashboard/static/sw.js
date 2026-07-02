/* Service worker del dashboard Liados.
   - Cache-first para /static/* (assets versionados por su cache name).
   - Network-only para APIs y /.
   - Versionado: bump CACHE_NAME para invalidar todo el cache.
   - Fallback explicito: si la red falla y no hay cache, devuelve un JSON
     con error (no un HTML "Offline" que seria confuso para una API). */

const CACHE_NAME = 'liados-static-v2';
const STATIC_ASSETS = [
  '/static/tokens.css',
  '/static/app.css',
  '/static/app.js',
  '/static/manifest.webmanifest',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg',
  '/static/fonts/Inter-Variable.woff2',
  '/static/fonts/JetBrainsMono-Variable.woff2',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .catch((e) => console.warn('[SW] install fallo:', e))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Solo cachear GETs del mismo origen bajo /static/
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith('/static/')) return;  // /, /api/*: network-only

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((resp) => {
        // Solo cachear 200 OK del mismo origen
        if (resp && resp.status === 200 && resp.type === 'basic') {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put(request, copy)).catch(() => {});
        }
        return resp;
      }).catch((err) => {
        // Red caida + sin cache: devolver 504 explicito
        console.warn('[SW] fetch failed:', request.url, err);
        return new Response(
          JSON.stringify({ error: 'offline', detail: 'Sin conexion y sin cache para ' + url.pathname }),
          { status: 504, headers: { 'Content-Type': 'application/json' } }
        );
      });
    })
  );
});

// Mensaje desde la app para forzar update (util para QA)
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
