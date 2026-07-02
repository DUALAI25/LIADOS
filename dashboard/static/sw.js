/* Service worker minimo para PWA del dashboard Liados.
   Estrategia: cache-first para assets estaticos (CSS, JS, fonts, manifest),
   network-first para / y APIs (siempre datos en vivo).
   Sin cache de credenciales ni de respuestas autenticadas. */
const CACHE_NAME = 'liados-v5.1.0';
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
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
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
  const isStatic = url.pathname.startsWith('/static/');
  if (!isStatic) {
    // APIs y /: network-only, sin cache (datos en vivo)
    return;
  }

  // Cache-first para assets estaticos
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((resp) => {
        if (resp && resp.status === 200 && resp.type === 'basic') {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put(request, copy));
        }
        return resp;
      }).catch(() => caches.match('/static/app.js'));
    })
  );
});
