// Bump CACHE to ship new static assets; the old cache is purged on activate.
const CACHE = 'wcda-v12';
const PRECACHE = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys =>
        Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // API calls always go straight to the network and are never cached.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  // App shell (page navigations + our own JS/CSS): network-first, so a redeploy
  // is picked up on the very next load. The cache is only an offline fallback.
  const isAppShell =
    request.mode === 'navigate' ||
    url.pathname === '/' ||
    url.pathname.startsWith('/static/');

  if (isAppShell) {
    event.respondWith(
      fetch(request)
        .then(response => {
          const copy = response.clone();
          caches.open(CACHE).then(cache => cache.put(request, copy)).catch(() => {});
          return response;
        })
        .catch(() =>
          caches.match(request).then(cached => cached || caches.match('/'))
        )
    );
    return;
  }

  // Other assets (icons, etc.): cache-first is fine.
  event.respondWith(caches.match(request).then(cached => cached || fetch(request)));
});
