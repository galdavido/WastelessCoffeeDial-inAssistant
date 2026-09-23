// Bump CACHE to ship new static assets; the old cache is purged on activate.
// Keep this in step with the ?v= query on the CSS/JS tags in index.html.
// CSS and JS are NOT precached by bare path: they are versioned URLs, and
// precaching the unversioned path is what previously let a stale app.js pair
// up with a fresh style.css. They are cached on first fetch instead.
const CACHE = 'wcda-v40';
const PRECACHE = [
  '/',
  '/static/manifest.json',
  // The faces are versioned by this cache, not by a query string, and the
  // app looks wrong in the fallback stack -- so they are precached.
  '/static/fonts/hanken-grotesk-latin.woff2',
  '/static/fonts/hanken-grotesk-latin-ext.woff2',
  '/static/fonts/instrument-serif-latin.woff2',
  '/static/fonts/instrument-serif-latin-ext.woff2',
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
    // cache: 'reload' skips the browser's own HTTP cache, so "network-first"
    // really means the network rather than a stale heuristic cache entry.
    event.respondWith(
      fetch(request, { cache: 'reload' })
        .catch(() => fetch(request))
        .then(response => {
          // Only a good response may become the offline copy. Caching a 404 or
          // a 500 would replay that error whenever the network is down.
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then(cache => cache.put(request, copy)).catch(() => {});
          }
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
