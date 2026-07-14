// Bootlegger service worker
// Static assets: cache-first. Pages: network-first with cached fallback,
// so the app opens instantly from the home screen and still shows the
// last-seen schedule if the connection blips.

const CACHE = 'bootlegger-v1';
const STATIC_ASSETS = [
  '/static/css/style.css',
  '/static/js/booksearch.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Never cache admin/auth or API traffic
  if (url.pathname.startsWith('/admin') || url.pathname.startsWith('/api') ||
      url.pathname === '/login' || url.pathname === '/logout') {
    return;
  }

  // Static assets: cache-first
  if (url.origin === location.origin && url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((cache) => cache.put(request, copy));
        return resp;
      }))
    );
    return;
  }

  // Same-origin pages: network-first, fall back to the last cached copy
  if (url.origin === location.origin) {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
          return resp;
        })
        .catch(() => caches.match(request))
    );
  }
});
