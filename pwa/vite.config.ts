import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Прямой URL на GitHub (используется как fallback)
const GITHUB_RAW = `https://raw.githubusercontent.com/mvbulgakova/mpgu-schedule/data`;

// Если задан VITE_PROXY_URL (Cloudflare Worker или иной прокси) — он становится
// основным источником данных, а GitHub raw — резервным.
// Если прокси не задан — данные читаются напрямую с GitHub.
const DATA_BASE_URL = process.env.VITE_PROXY_URL || GITHUB_RAW;
const DATA_FALLBACK_URL = process.env.VITE_PROXY_URL ? GITHUB_RAW : "";

// Паттерны для Workbox: нужно покрыть оба URL
const dataPatterns = [DATA_BASE_URL, ...(DATA_FALLBACK_URL ? [DATA_FALLBACK_URL] : [])];

function escapeRegex(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export default defineConfig({
  base: process.env.VITE_BASE_URL ?? "/",
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icons/*.png", "icons/*.svg"],
      manifest: false, // используем свой public/manifest.json
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg}"],
        runtimeCaching: [
          ...dataPatterns.map((base) => ({
            urlPattern: new RegExp(`^${escapeRegex(base)}/meta/`),
            handler: "StaleWhileRevalidate" as const,
            options: {
              cacheName: "mpgu-meta",
              expiration: { maxAgeSeconds: 3600 },
            },
          })),
          ...dataPatterns.map((base) => ({
            urlPattern: new RegExp(`^${escapeRegex(base)}/institutes/`),
            handler: "CacheFirst" as const,
            options: {
              cacheName: "mpgu-schedules",
              expiration: { maxAgeSeconds: 21600 }, // 6 часов
            },
          })),
        ],
      },
    }),
  ],
  define: {
    __DATA_BASE_URL__: JSON.stringify(DATA_BASE_URL),
    __DATA_FALLBACK_URL__: JSON.stringify(DATA_FALLBACK_URL),
  },
});
