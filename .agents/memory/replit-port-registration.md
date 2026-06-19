---
name: Replit port registration for artifact workflows
description: Artifact-managed workflows fail the health check for any port not listed in .replit [[ports]] — even if the app is genuinely listening on that port.
---

## Rule

Before calling `restart_workflow` for any artifact whose `localPort` is not 8080 or 8081, add that port to the `.replit` `[[ports]]` section via `verifyAndReplaceDotReplit`.

**Without a `[[ports]]` entry the workflow health checker returns `DIDNT_OPEN_A_PORT` every time, regardless of whether the app is actually listening.**

## Why

The Replit workflow health checker verifies port availability through the proxy/port-registry layer, not via raw TCP connect. Only ports declared in `.replit [[ports]]` are visible to it. Ports above ~10 000 assigned by `createArtifact` are not auto-registered.

Symptom: `code: DIDNT_OPEN_A_PORT, message: workflow "..." timed out: didn't open port XXXXX` even when `curl http://localhost:XXXXX/` returns HTTP 200 from inside the container.

## How to apply

1. Read `.replit`.
2. Add `[[ports]] localPort = XXXXX  externalPort = XXXXX` for the artifact's port.
3. Call `verifyAndReplaceDotReplit({ tempFilePath: ".replit.edit", dotReplitPath: ".replit" })`.
4. Then call `restart_workflow` — it will succeed.

## Extra: running Python/Streamlit inside a Vite artifact

Because artifact-managed workflows only reliably recognize Vite dev servers, wrap Streamlit in Vite:

- Add a `vite-plugin-streamlit` in `src/streamlitPlugin.ts` (spawns `streamlit run` as a child process in `configureServer`).
- Add proxy rules in `vite.config.ts`: `/st` (path-rewritten → `/`), `/_stcore`, `/static`, `/stream`, `/component`.
- `App.tsx`: full-viewport `<iframe src="/st/" />` with a health-poll loading screen (`fetch("/_stcore/health")`).
- `package.json` dev script: `vite --config vite.config.ts --host 0.0.0.0` (NOT `node proxy.mjs`).
