const CACHE = 'barista-ai-v3';
const PRECACHE = [
  '/',
  '/static/style.css?v=20260517',
  '/static/desktop.css?v=20260517',
  '/static/app.js?v=20260517',
  '/static/manifest.json?v=20260517',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Always go network-first for API calls
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  // Cache-first for static assets, network fallback
  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request))
  );
});
