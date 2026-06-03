#!/usr/bin/env bash
# Diagnose gateway, control server, Ollama, Docker, and Open WebUI connectivity.

set -u
cd "$(dirname "$0")"

ENV_FILE="$HOME/.config/local-ai-gateway/gateway.env"
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

CONTROL_HOST="${CONTROL_HOST:-172.17.0.1}"
CONTROL_PORT="${CONTROL_PORT:-8089}"
GATEWAY_HOST="${GATEWAY_HOST:-172.17.0.1}"
GATEWAY_PORT="${GATEWAY_PORT:-8080}"
CONTROL_URL="http://${CONTROL_HOST}:${CONTROL_PORT}"
GATEWAY_URL="${GATEWAY_URL:-http://${GATEWAY_HOST}:${GATEWAY_PORT}}"

pass() { printf "✓ %s\n" "$*"; }
warn() { printf "! %s\n" "$*"; }
fail() { printf "✗ %s\n" "$*"; }

echo "Local AI Gateway doctor"
echo ""

systemctl --user is-active --quiet ai-control.service && pass "ai-control.service is running" || fail "ai-control.service is not running"
systemctl --user is-active --quiet local-ai-gateway.service && pass "local-ai-gateway.service is running" || warn "local-ai-gateway.service is not running"
systemctl is-active --quiet ollama.service && pass "ollama.service is running" || warn "ollama.service is not running"

if curl -s --max-time 3 "$CONTROL_URL/status" ${GATEWAY_SECRET:+-H "X-Gateway-Secret: $GATEWAY_SECRET"} >/dev/null; then
  pass "control server reachable at $CONTROL_URL"
else
  fail "control server not reachable at $CONTROL_URL"
fi

if curl -s --max-time 3 "$GATEWAY_URL/api/status" >/dev/null; then
  pass "gateway reachable at $GATEWAY_URL"
else
  warn "gateway not reachable at $GATEWAY_URL"
fi

if curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null; then
  pass "Ollama API reachable"
else
  warn "Ollama API not reachable"
fi

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^open-webui$'; then
  pass "open-webui container is running"
  docker exec open-webui python3 - <<PY 2>/dev/null && pass "Open WebUI can reach control server" || fail "Open WebUI cannot reach control server"
import urllib.request
req = urllib.request.Request("http://host.docker.internal:${CONTROL_PORT}/status")
${GATEWAY_SECRET:+req.add_header("X-Gateway-Secret", "$GATEWAY_SECRET")}
urllib.request.urlopen(req, timeout=3).read()
PY
else
  warn "open-webui container not running or Docker unavailable"
fi

if systemctl list-unit-files ollama.service --no-legend 2>/dev/null | grep -q '^ollama.service'; then
  pass "ollama.service is installed"
  if systemctl --no-ask-password show ollama.service -p ActiveState >/dev/null 2>&1; then
    pass "systemd can inspect ollama.service without a prompt"
  else
    warn "systemd cannot inspect ollama.service without a prompt"
  fi
else
  warn "ollama.service is not installed; direct ollama serve fallback will be used"
fi

echo ""
echo "Suggested Open WebUI valves:"
echo "  CONTROL_URL=http://host.docker.internal:${CONTROL_PORT}"
echo "  GATEWAY_URL=http://host.docker.internal:${GATEWAY_PORT}"
echo "  GATEWAY_SECRET=${GATEWAY_SECRET:-<blank>}"
