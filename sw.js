// 离线缓存：先联网取最新，取不到才用上次缓存的内容，并在响应头里标记 X-From-Cache，页面据此提示“显示的是旧数据”
const CACHE = "signal-v3";
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  const key = req.url.split("?")[0];          // 数据请求带 ?t= 时间戳，缓存时去掉
  e.respondWith(
    fetch(req).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(key, copy)); }
      return res;
    }).catch(() => caches.match(key).then(r => {
      if (!r) return caches.match("./");
      const h = new Headers(r.headers); h.set("X-From-Cache", "1");
      return r.blob().then(b => new Response(b, { status: 200, headers: h }));
    }))
  );
});
