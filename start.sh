#!/usr/bin/env bash
# Start everything — run this when you sit down to work

set -euo pipefail
cd "$(dirname "$0")"

# ── Load .env if present ──────────────────────────────────────────────────────
[ -f .env ] && export $(grep -v '^#' .env | grep '=' | xargs) 2>/dev/null || true
[ -f "$HOME/.config/local-ai-gateway/gateway.env" ] && export $(grep -v '^#' "$HOME/.config/local-ai-gateway/gateway.env" | grep '=' | xargs) 2>/dev/null || true

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080}"

# ── Ollama ────────────────────────────────────────────────────────────────────
if ! curl -s --max-time 2 http://localhost:11434/api/tags > /dev/null 2>&1; then
  echo "Starting Ollama..."
  if systemctl list-unit-files ollama.service --no-legend 2>/dev/null | grep -q '^ollama.service'; then
    systemctl --no-ask-password start ollama.service 2>/dev/null || true
  else
    ollama serve > /tmp/ollama.log 2>&1 &
  fi
  sleep 3
  curl -s --max-time 2 http://localhost:11434/api/tags > /dev/null 2>&1 && echo "  ✓ Ollama running" \
    || echo "  ⚠  Ollama did not start"
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
if curl -s --max-time 2 "$GATEWAY_URL/api/status" > /dev/null 2>&1; then
  echo "  ✓ Gateway already running"
else
  echo "Starting gateway..."
  if systemctl --user list-unit-files local-ai-gateway.service --no-legend 2>/dev/null | grep -q '^local-ai-gateway.service'; then
    systemctl --user start local-ai-gateway.service
  else
    fuser -k 8080/tcp 2>/dev/null || true
    mkdir -p data

    if ! ~/.local/bin/uvicorn --version > /dev/null 2>&1; then
      pip install uvicorn --break-system-packages -q
    fi

    ~/.local/bin/uvicorn src.main:app --host 0.0.0.0 --port 8080 > /tmp/gateway.log 2>&1 &

    until grep -q "Application startup complete\|address already in use" /tmp/gateway.log 2>/dev/null; do
      sleep 2
    done
  fi
  echo "  ✓ Gateway running"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Everything is running:"
echo "  Dashboard:  $GATEWAY_URL"
echo "  Open WebUI: http://localhost:3000  (login: admin@local.ai / localai2026!)"
echo "  API:        $GATEWAY_URL/v1"
echo ""
echo "When done: bash stop.sh"
