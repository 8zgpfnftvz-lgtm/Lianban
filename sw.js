/* 天天板 · 连板统计 PWA Service Worker
 * 只缓存同源页面本体；腾讯行情、东财涨停池、开盘啦接口不缓存。
 */
const CACHE = 'ttb-lbtj-v20261126-3';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './manifest.webmanifest',
  './icon-32.png',
  './icon-180.png',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable-512.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;

  let url;
  try { url = new URL(req.url); } catch (e) { return; }
  if (url.origin !== self.location.origin) return;   // 行情/接口走网络

  // 导航请求：先显示上次缓存，同时后台更新下一条版本。
  if (req.mode === 'navigate') {
    const cached = caches.match('./index.html').then(hit => hit || caches.match('./'));
    const network = fetch(req).then(res => {
      if (res && res.ok) {
        const copy = res.clone();
        return caches.open(CACHE).then(async cache => {
          const previous = await cache.match('./index.html');
          const changed = previous && previous.headers.get('etag') !== res.headers.get('etag');
          await cache.put('./index.html', copy);
          if (changed) {
            const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
            clients.forEach(client => client.postMessage({ type: 'INDEX_UPDATED' }));
          }
          return res;
        });
      }
      return res;
    }).catch(() => null);
    event.waitUntil(network.catch(() => {}));
    event.respondWith(cached.then(hit => hit || network).then(res => res || caches.match('./')));
    return;
  }

  // 盘后数据每天更新：网络优先，失败时回退到上一次缓存。
  if (url.pathname.endsWith('/dabanke_data.json')) {
    event.respondWith(
      fetch(req).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(cache => cache.put(req, copy)).catch(() => {});
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // 静态资源：缓存优先
  event.respondWith(
    caches.match(req).then(hit => {
      if (hit) return hit;
      return fetch(req).then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(cache => cache.put(req, copy)).catch(() => {});
        }
        return res;
      });
    })
  );
});
