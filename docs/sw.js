// はちバス時刻表 service worker（キャッシュファースト）
// data.json を更新したら必ずこのバージョン番号を上げること
const CACHE_NAME = "hachibus-v9";

const PRECACHE = [
  "./",
  "./index.html",
  "./data.json",
  "./manifest.json",
  "./icon-192.png",
  "./icon-512.png",
  "./vendor/leaflet.js",
  "./vendor/leaflet.css",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

// 旧バージョンのキャッシュを削除
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  // data.json / index.html はキャッシュ即応答＋裏で再取得（stale-while-revalidate）。
  // これでバージョン更新を忘れても次回起動時に新ダイヤへ追いつく
  const swr = url.origin === self.location.origin &&
    ["/data.json", "/index.html", "/"].some((p) => url.pathname.endsWith(p));
  if (swr) {
    e.respondWith((async () => {
      const c = await caches.open(CACHE_NAME);
      const hit = await c.match(e.request, { ignoreSearch: true });
      const net = fetch(e.request).then((res) => {
        if (res && res.ok) c.put(e.request, res.clone());
        return res;
      }).catch(() => null);
      if (hit) { e.waitUntil(net); return hit; }
      const res = await net;
      return res || new Response("offline", { status: 503 });
    })());
    return;
  }
  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then(
      (hit) => hit || fetch(e.request)
    )
  );
});
