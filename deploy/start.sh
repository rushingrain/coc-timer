#!/usr/bin/env bash
set -euo pipefail

cd /opt/coc-timer
exec /opt/coc-timer/.venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1
