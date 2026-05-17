import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

const DATA_BASE_URL =
  process.env.VITE_DATA_URL ||
  "https://raw.githubusercontent.com/mvbulgakova/hyperbolic-geometry-app/data";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icons/*.png", "icons/*.svg"],
      manifest: false, // используем свой public/manifest.json
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg}"],
        runtimeCaching: [
          {
            urlPattern: new RegExp(`^${DATA_BASE_URL}/meta/`),
            handler: "StaleWhileRevalidate",
            options: {
              cacheName: "mpgu-meta",
              expiration: { maxAgeSeconds: 3600 },
            },
          },
          {
            urlPattern: new RegExp(`^${DATA_BASE_URL}/institutes/`),
            handler: "CacheFirst",
            options: {
              cacheName: "mpgu-schedules",
              expiration: { maxAgeSeconds: 21600 }, // 6 часов
            },
          },
        ],
      },
    }),
  ],
  define: {
    __DATA_BASE_URL__: JSON.stringify(DATA_BASE_URL),
  },
});
