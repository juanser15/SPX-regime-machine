---
name: Artifact runtime paths
description: Why filesystem assets in pnpm artifact deployments must not be resolved from process.cwd().
---

Resolve tracked runtime assets from the executing module location or from an explicit configured directory, not from `process.cwd()`.

**Why:** Filtered development commands run with the package directory as cwd, while artifact production commands may run from the workspace root. The same relative traversal can therefore escape the deployed workspace in production.

**How to apply:** For files shared across workspace packages, derive the workspace root deterministically from `import.meta.url`. If a configurable path is relative, resolve it against that same root.