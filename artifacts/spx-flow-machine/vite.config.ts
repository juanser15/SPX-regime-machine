import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import runtimeErrorOverlay from "@replit/vite-plugin-runtime-error-modal";
import { streamlitPlugin } from "./src/streamlitPlugin";

const rawPort = process.env.PORT;

if (!rawPort) {
  throw new Error(
    "PORT environment variable is required but was not provided.",
  );
}

const port = Number(rawPort);

if (Number.isNaN(port) || port <= 0) {
  throw new Error(`Invalid PORT value: "${rawPort}"`);
}

const basePath = process.env.BASE_PATH;

if (!basePath) {
  throw new Error(
    "BASE_PATH environment variable is required but was not provided.",
  );
}

const STREAMLIT_PORT = port + 1;

export default defineConfig({
  base: basePath,
  plugins: [
    react(),
    tailwindcss(),
    runtimeErrorOverlay(),
    streamlitPlugin(STREAMLIT_PORT),
    ...(process.env.NODE_ENV !== "production" &&
    process.env.REPL_ID !== undefined
      ? [
          await import("@replit/vite-plugin-cartographer").then((m) =>
            m.cartographer({
              root: path.resolve(import.meta.dirname, ".."),
            }),
          ),
          await import("@replit/vite-plugin-dev-banner").then((m) =>
            m.devBanner(),
          ),
        ]
      : []),
  ],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
      "@assets": path.resolve(import.meta.dirname, "..", "..", "attached_assets"),
    },
    dedupe: ["react", "react-dom"],
  },
  root: path.resolve(import.meta.dirname),
  build: {
    outDir: path.resolve(import.meta.dirname, "dist/public"),
    emptyOutDir: true,
  },
  server: {
    port,
    strictPort: true,
    host: "0.0.0.0",
    allowedHosts: true,
    fs: {
      strict: true,
    },
    proxy: {
      // Proxy Streamlit's root HTML at /st/ (path-rewritten → / on Streamlit)
      "/st": {
        target: `http://localhost:${STREAMLIT_PORT}`,
        changeOrigin: false,
        ws: true,
        rewrite: (path) => path.replace(/^\/st/, ""),
      },
      // All Streamlit internal paths (loaded from inside the iframe at the parent origin)
      "/_stcore": {
        target: `http://localhost:${STREAMLIT_PORT}`,
        ws: true,
        changeOrigin: false,
      },
      "/static": {
        target: `http://localhost:${STREAMLIT_PORT}`,
        changeOrigin: false,
      },
      "/stream": {
        target: `http://localhost:${STREAMLIT_PORT}`,
        ws: true,
        changeOrigin: false,
      },
      "/component": {
        target: `http://localhost:${STREAMLIT_PORT}`,
        changeOrigin: false,
      },
    },
  },
  preview: {
    port,
    host: "0.0.0.0",
    allowedHosts: true,
  },
});
