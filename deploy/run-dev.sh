#!/usr/bin/env bash
# Quick foreground launcher for manual / dev runs on Linux.
# For production use the systemd unit installed by setup.sh.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip wheel
    .venv/bin/pip install -r requirements-linux.txt
fi

exec .venv/bin/uvicorn src.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips='*'
