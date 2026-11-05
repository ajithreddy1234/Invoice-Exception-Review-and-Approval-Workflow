import { defineConfig } from "vite";

export default defineConfig({
  base: "/",
  build: { outDir: "dist", emptyOutDir: true, assetsInlineLimit: 0 },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
