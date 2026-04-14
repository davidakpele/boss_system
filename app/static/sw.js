/* BOSS System — Service Worker v1.2 */
const CACHE = 'boss-cache-v2';

const PRECACHE = [
  '/dashboard',
  '/static/css/custom.css',
  '/static/js/app.js',
];

function isCacheable(response) {
  if (!response) return false;
  if (response.status === 0) return false;
  if (response.status !== 200) return false;
  if (response.headers.get('content-range')) return false;
  return true;
}

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(PRECACHE).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const { request } = e;
  const url = new URL(request.url);
  if (request.method !== 'GET') return;
  if (request.headers.get('upgrade') === 'websocket') return;
  if (request.headers.get('range')) return;
  if (url.pathname.startsWith('/ask-boss/chat')  ||
      url.pathname.startsWith('/messages/ws')    ||
      url.pathname.startsWith('/push/')) return;

  const mediaExts = /\.(mp4|webm|ogg|mp3|wav|flac|m4a|mov|avi)(\?|$)/i;
  if (mediaExts.test(url.pathname)) return;

  const isStatic = url.pathname.startsWith('/static/') ||
                   url.pathname.startsWith('/uploads/') ||
                   url.hostname !== self.location.hostname;

  if (isStatic) {
    e.respondWith(
      caches.match(request).then(hit => {
        if (hit) return hit;
        return fetch(request).then(res => {
          if (isCacheable(res)) {
            const clone = res.clone();
            caches.open(CACHE).then(c => c.put(request, clone));
          }
          return res;
        });
      })
    );
  } else {
    e.respondWith(
      fetch(request)
        .then(res => {
          if (isCacheable(res) && request.mode === 'navigate') {
            const clone = res.clone();
            caches.open(CACHE).then(c => c.put(request, clone));
          }
          return res;
        })
        .catch(() =>
          caches.match(request).then(hit => hit || offlinePage())
        )
    );
  }
});

function offlinePage() {
  return new Response(
    `<!DOCTYPE html><html><head><title>Offline — BOSS</title>
<style>
  *{box-sizing:border-box}
  body{font-family:sans-serif;background:#080c14;color:#e2e8f0;
       display:flex;align-items:center;justify-content:center;
       height:100vh;text-align:center;margin:0}
  h2{color:#3b82f6;font-size:24px}
  p{color:#64748b;margin-top:8px}
  button{margin-top:20px;padding:10px 28px;background:#3b82f6;color:#fff;
         border:none;border-radius:8px;font-size:14px;cursor:pointer}
</style></head>
<body><div>
  <h2><i class="fa-solid fa-tower-broadcast" style="margin-right:8px;"></i>You're offline</h2>
  <p>Cached pages are still available.<br>Connect to the internet for live data.</p>
  <button onclick="location.reload()">Retry</button>
</div></body></html>`,
    { headers: { 'Content-Type': 'text/html' } }
  );
}
self.addEventListener('push', e => {
  if (!e.data) return;
  let d = {};
  try { d = e.data.json(); } catch { d = { title: 'BOSS', body: e.data.text() }; }

  e.waitUntil(self.registration.showNotification(d.title || 'BOSS System', {
    body:     d.body  || '',
    icon:     d.icon  || '/static/img/icon-192.png',
    badge:    d.badge || '/static/img/icon-72.png',
    tag:      d.tag   || 'boss-notif',
    renotify: true,
    vibrate:  [200, 100, 200],
    data:     { url: d.url || '/dashboard' },
    actions:  [
      { action: 'open',    title: 'Open'    },
      { action: 'dismiss', title: 'Dismiss' },
    ],
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  if (e.action === 'dismiss') return;
  const target = e.notification.data?.url || '/dashboard';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const c of list) {
        if (c.url.startsWith(self.location.origin) && 'focus' in c) {
          c.navigate(target);
          return c.focus();
        }
      }
      return clients.openWindow(target);
    })
  );
});