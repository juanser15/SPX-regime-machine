#!/usr/bin/env bash
# Entry point for Streamlit inside the Replit artifact workflow.
# The PORT env var is injected by the artifact system (default 21050).
set -euo pipefail
PORT=${PORT:-21050}
cd /home/runner/workspace/spx-flow-machine
exec streamlit run app.py \
  --server.port "$PORT" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false
