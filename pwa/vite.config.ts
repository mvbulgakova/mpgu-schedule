import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// jsDelivr — бесплатный CDN с узлами в России, зеркалирует GitHub автоматически
const JSDELIVR = `https://cdn.jsdelivr.net/gh/mvbulgakova/mpgu-schedule@data`;

// raw.githubusercontent.com — резервный (может блокироваться)
const GITHUB_RAW = `https://raw.githubusercontent.com/mvbulgakova/mpgu-schedule/data`;

// Позволяет переопределить основной URL через env (например, Cloudflare Worker)
const DATA_BASE_URL = process.env.VITE_PROXY_URL || JSDELIVR;
const DATA_FALLBACK_URL = DATA_BASE_URL !== GITHUB_RAW ? GITHUB_RAW : "";

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
      manifest: false,
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg}"],
        importScripts: ["sw-notifications.js"],
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
              expiration: { maxAgeSeconds: 21600 },
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
