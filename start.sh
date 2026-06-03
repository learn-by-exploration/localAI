#!/usr/bin/env bash
# Start everything — run this when you sit down to work

set -euo pipefail
cd "$(dirname "$0")"

# ── Load .env if present ──────────────────────────────────────────────────────
[ -f .env ] && export $(grep -v '^#' .env | grep '=' | xargs) 2>/dev/null || true

# ── Ollama ────────────────────────────────────────────────────────────────────
if ! curl -s --max-time 2 http://localhost:11434/api/tags > /dev/null 2>&1; then
  echo "Starting Ollama..."
  ollama serve > /tmp/ollama.log 2>&1 &
  sleep 3
  echo "  ✓ Ollama running"
else
  echo "  ✓ Ollama already running"
fi

# ── Open WebUI (Docker) ───────────────────────────────────────────────────────
if ! curl -s --max-time 2 http://localhost:3000 > /dev/null 2>&1; then
  echo "Starting Open WebUI..."
  docker start open-webui > /dev/null 2>&1 && echo "  ✓ Open WebUI starting at http://localhost:3000" \
    || echo "  ⚠  Open WebUI container not found — run setup first"
else
  echo "  ✓ Open WebUI already running"
fi

# ── Gateway ───────────────────────────────────────────────────────────────────
if curl -s --max-time 2 http://localhost:8080/api/status > /dev/null 2>&1; then
  echo "  ✓ Gateway already running"
else
  echo "Starting gateway..."
  fuser -k 8080/tcp 2>/dev/null || true
  mkdir -p data

  if ! ~/.local/bin/uvicorn --version > /dev/null 2>&1; then
    pip install uvicorn --break-system-packages -q
  fi

  ~/.local/bin/uvicorn src.main:app --host 0.0.0.0 --port 8080 > /tmp/gateway.log 2>&1 &

  until grep -q "Application startup complete\|address already in use" /tmp/gateway.log 2>/dev/null; do
    sleep 2
  done
  echo "  ✓ Gateway running at http://localhost:8080"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Everything is running:"
echo "  Dashboard:  http://localhost:8080"
echo "  Open WebUI: http://localhost:3000  (login: admin@local.ai / localai2026!)"
echo "  API:        http://localhost:8080/v1"
echo ""
echo "When done: bash stop.sh"
