/* 秒开门 · 离线外壳缓存 */
const CACHE = 'quickopen-shell-v4';
const SHELL = [
  './', './index.html', './manifest.webmanifest',
  './icon.svg', './icon-dark.svg', './icon-light.svg',
  './icon-192.png', './icon-512.png',
  './icon-light-192.png', './icon-light-512.png',
  './icon-mono-512.png', './apple-touch-icon.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const u = new URL(req.url);
  if (u.origin !== self.location.origin) return;
  if (u.pathname.indexOf('/api/') === 0) return; // 接口永不缓存

  const isDoc = req.mode === 'navigate' || u.pathname === '/' || u.pathname.endsWith('/index.html');
  if (isDoc) {
    // 页面走网络优先，保证更新能生效；断网时回退到缓存
    e.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put('./index.html', copy));
        return res;
      }).catch(() => caches.match('./index.html'))
    );
    return;
  }
  e.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(req, copy));
      return res;
    }))
  );
});
