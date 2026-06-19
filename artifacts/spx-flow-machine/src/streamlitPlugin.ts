import type { Plugin } from "vite";
import { spawn, type ChildProcess } from "child_process";
import * as path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export function streamlitPlugin(streamlitPort: number): Plugin {
  let proc: ChildProcess | null = null;

  return {
    name: "vite-plugin-streamlit",

    configureServer(server) {
      const appPath = path.resolve(
        __dirname,
        "../../../spx-flow-machine/app.py",
      );

      console.log(
        `[streamlit] Starting on port ${streamlitPort} → ${appPath}`,
      );

      proc = spawn(
        "streamlit",
        [
          "run",
          appPath,
          "--server.port",
          String(streamlitPort),
          "--server.address",
          "0.0.0.0",
          "--server.headless",
          "true",
          "--server.enableCORS",
          "false",
          "--server.enableXsrfProtection",
          "false",
        ],
        { stdio: "inherit" },
      );

      proc.on("error", (err) => {
        console.error("[streamlit] Failed to start:", err.message);
      });

      proc.on("close", (code) => {
        console.log(`[streamlit] Exited with code ${code}`);
      });

      server.httpServer?.once("close", () => {
        proc?.kill("SIGTERM");
      });
    },

    closeBundle() {
      proc?.kill("SIGTERM");
    },
  };
}
