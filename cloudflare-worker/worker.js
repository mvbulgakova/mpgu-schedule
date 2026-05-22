/**
 * Cloudflare Worker: прокси для данных расписания МПГУ.
 *
 * Проксирует запросы с raw.githubusercontent.com, добавляет кэш
 * и CORS-заголовки. Обеспечивает работу PWA при блокировке GitHub CDN.
 *
 * Развёртывание:
 *   npm install -g wrangler
 *   wrangler login
 *   wrangler deploy
 */

const GITHUB_BASE =
  "https://raw.githubusercontent.com/mvbulgakova/mpgu-schedule/data";

// TTL кэша: метаданные обновляются чаще, расписания — реже
const TTL_META = 60 * 60;       // 1 час
const TTL_SCHEDULE = 6 * 60 * 60; // 6 часов

export default {
  async fetch(request, _env, ctx) {
    if (request.method === "OPTIONS") {
      return corsPreflightResponse();
    }
    if (request.method !== "GET") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    const url = new URL(request.url);
    // Путь вида /meta/index.json или /institutes/123/schedule.json
    const path = url.pathname;

    const githubUrl = `${GITHUB_BASE}${path}`;
    const cache = caches.default;
    const cacheKey = new Request(githubUrl, { method: "GET" });

    // Сначала проверяем кэш Cloudflare
    let response = await cache.match(cacheKey);
    if (response) {
      return addCors(response);
    }

    // Запрашиваем GitHub
    let upstream;
    try {
      upstream = await fetch(githubUrl, {
        headers: {
          "User-Agent": "MPGU-Schedule-Proxy/1.0",
          Accept: "application/json, */*",
        },
      });
    } catch (err) {
      return new Response(`Upstream error: ${err.message}`, { status: 502 });
    }

    if (!upstream.ok) {
      return new Response(upstream.statusText, { status: upstream.status });
    }

    const ttl = path.startsWith("/meta/") ? TTL_META : TTL_SCHEDULE;
    const headers = new Headers(upstream.headers);
    headers.set("Cache-Control", `public, max-age=${ttl}`);
    headers.set("Access-Control-Allow-Origin", "*");
    headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
    headers.set("Vary", "Accept-Encoding");

    response = new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers,
    });

    // Кладём в кэш асинхронно, не блокируем ответ
    ctx.waitUntil(cache.put(cacheKey, response.clone()));
    return response;
  },
};

function corsPreflightResponse() {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Max-Age": "86400",
    },
  });
}

function addCors(response) {
  const headers = new Headers(response.headers);
  headers.set("Access-Control-Allow-Origin", "*");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}
