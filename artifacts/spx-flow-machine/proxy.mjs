/**
 * proxy.mjs
 * ---------
 * Thin Node.js HTTP+WebSocket reverse proxy that:
 *   1. Starts Streamlit as a child process on STREAMLIT_PORT (PORT+1)
 *   2. Listens on PORT (the Replit-assigned port, e.g. 21050)
 *   3. Forwards every HTTP request and WebSocket upgrade to Streamlit
 *
 * This wrapper exists because the Replit artifact health check requires a
 * Node.js process to register on the assigned port. Streamlit (Python/Uvicorn)
 * opens the port correctly but the health check does not detect it.
 */

import http from "http";
import httpProxy from "http-proxy";
import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const PORT = parseInt(process.env.PORT ?? "21050", 10);
const STREAMLIT_PORT = PORT + 1;
const STREAMLIT_APP = path.resolve(__dirname, "../../spx-flow-machine/app.py");

// ── Start Streamlit ──────────────────────────────────────────────────────────

console.log(`[proxy] Starting Streamlit on port ${STREAMLIT_PORT}…`);

const streamlit = spawn(
  "streamlit",
  [
    "run", STREAMLIT_APP,
    "--server.port", String(STREAMLIT_PORT),
    "--server.address", "0.0.0.0",
    "--server.headless", "true",
    "--server.enableCORS", "false",
    "--server.enableXsrfProtection", "false",
  ],
  {
    stdio: "inherit",
    env: {
      ...process.env,
      PORT: String(STREAMLIT_PORT),
    },
  }
);

streamlit.on("error", (err) => {
  console.error("[proxy] Failed to start Streamlit:", err.message);
  process.exit(1);
});

streamlit.on("close", (code) => {
  console.log(`[proxy] Streamlit exited with code ${code}`);
  process.exit(code ?? 0);
});

// Forward SIGTERM/SIGINT to Streamlit
for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, () => {
    streamlit.kill(sig);
  });
}

// ── Wait for Streamlit to be ready ───────────────────────────────────────────

async function waitForStreamlit(port, maxWaitMs = 30_000) {
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get(
          `http://127.0.0.1:${port}/_stcore/health`,
          (res) => { res.resume(); resolve(); }
        );
        req.on("error", reject);
        req.setTimeout(1000, () => { req.destroy(); reject(new Error("timeout")); });
      });
      return true;
    } catch {
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  return false;
}

// ── Start proxy server ────────────────────────────────────────────────────────

const proxy = httpProxy.createProxyServer({
  target: `http://127.0.0.1:${STREAMLIT_PORT}`,
  ws: true,
  changeOrigin: false,
});

proxy.on("error", (err, req, res) => {
  console.error("[proxy] Proxy error:", err.message);
  if (res && !res.headersSent) {
    res.writeHead(502, { "Content-Type": "text/plain" });
    res.end("Bad Gateway — Streamlit not ready yet. Please refresh.");
  }
});

const server = http.createServer((req, res) => {
  proxy.web(req, res);
});

server.on("upgrade", (req, socket, head) => {
  proxy.ws(req, socket, head);
});

// Bind the proxy port first (so the Replit health check passes), then wait
// for Streamlit to be ready in the background.
server.listen(PORT, "0.0.0.0", async () => {
  console.log(`[proxy] Listening on port ${PORT} → forwarding to Streamlit :${STREAMLIT_PORT}`);
  const ready = await waitForStreamlit(STREAMLIT_PORT);
  if (ready) {
    console.log(`[proxy] Streamlit is ready. Dashboard live on port ${PORT}.`);
  } else {
    console.warn("[proxy] Streamlit did not become ready within 30s. Proxy will still forward.");
  }
});
