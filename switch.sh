#!/usr/bin/env bash
# ── Local AI Gateway — Profile Switcher ──────────────────────────────────────
#
# Usage:
#   ./switch.sh              show current profile
#   ./switch.sh local        switch to local models (Ollama)
#   ./switch.sh cloud        switch to cloud APIs (OpenAI / Anthropic)
#   ./switch.sh status       show gateway status and active model
#
# Requirements for cloud mode:
#   export OPENAI_API_KEY=sk-...
#   export ANTHROPIC_API_KEY=sk-ant-...
#   (or put them in .env)

set -euo pipefail

GATEWAY_URL="http://localhost:8080"
ENV_FILE=".env"
STATE_FILE=".gateway_profile"
LOCAL_CONFIG="config/models.yaml"
CLOUD_CONFIG="config/cloud_models.yaml"
ACTIVE_CONFIG="config/active_models.yaml"
LOG="/tmp/gateway.log"

# ── Load .env if it exists ────────────────────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' "$ENV_FILE" | grep '=' | xargs) 2>/dev/null || true
fi

# ── Helpers ───────────────────────────────────────────────────────────────────
current_profile() {
  cat "$STATE_FILE" 2>/dev/null || echo "local"
}

gateway_running() {
  curl -s --max-time 3 "$GATEWAY_URL/api/status" -o /dev/null -w "%{http_code}" 2>/dev/null | grep -q "200"
}

restart_gateway() {
  local profile="$1"
  echo "  Restarting gateway in $profile mode..."

  # Stop old instance
  fuser -k 8080/tcp 2>/dev/null || true
  sleep 1

  # Set the active config
  cp "$2" "$ACTIVE_CONFIG"

  # Start gateway
  local env_prefix=""
  if [ "$profile" = "cloud" ]; then
    env_prefix="MODELS_CONFIG=$ACTIVE_CONFIG"
  else
    env_prefix="MODELS_CONFIG=$ACTIVE_CONFIG"
  fi

  cd "$(dirname "$0")"
  mkdir -p data
  env $env_prefix ~/.local/bin/uvicorn src.main:app \
    --host 0.0.0.0 --port 8080 > "$LOG" 2>&1 &

  echo -n "  Waiting for gateway"
  for i in {1..30}; do
    echo -n "."
    sleep 2
    if grep -q "Application startup complete" "$LOG" 2>/dev/null; then
      echo " ready"
      return 0
    fi
    if grep -q "address already in use\|Error" "$LOG" 2>/dev/null; then
      echo " ERROR"
      tail -5 "$LOG"
      return 1
    fi
  done
  echo " timed out"
  return 1
}

show_status() {
  local profile
  profile=$(current_profile)
  echo "Profile:  $profile"

  if gateway_running; then
    result=$(curl -s --max-time 5 "$GATEWAY_URL/api/status" 2>/dev/null)
    model=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('model_name') or d.get('model_id') or '—')" 2>/dev/null || echo "—")
    status=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])" 2>/dev/null || echo "—")
    vram=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); s=d['system']; print(f\"{s['vram_used_mb']}MB/{s['vram_total_mb']}MB\" if s['vram_used_mb'] else 'N/A')" 2>/dev/null || echo "—")
    echo "Gateway:  running (:8080)"
    echo "Model:    $model ($status)"
    echo "VRAM:     $vram"
  else
    echo "Gateway:  offline"
  fi
}

switch_to_local() {
  echo "Switching to LOCAL mode (Ollama)..."

  if ! curl -s --max-time 3 "http://localhost:11434/api/tags" -o /dev/null 2>/dev/null; then
    echo "  ⚠  Ollama not running. Start it first: ollama serve"
    exit 1
  fi

  echo "local" > "$STATE_FILE"
  restart_gateway "local" "$LOCAL_CONFIG"

  echo ""
  echo "  ✓ Local mode active"
  echo "  Models: $(curl -s "$GATEWAY_URL/v1/models" | python3 -c "import sys,json; print(', '.join(m['id'] for m in json.load(sys.stdin)['data']))" 2>/dev/null)"
  echo "  Endpoint: $GATEWAY_URL/v1"
}

switch_to_cloud() {
  echo "Switching to CLOUD mode..."

  local missing=()
  [ -z "${OPENAI_API_KEY:-}" ] && missing+=("OPENAI_API_KEY")
  [ -z "${ANTHROPIC_API_KEY:-}" ] && missing+=("ANTHROPIC_API_KEY")

  if [ ${#missing[@]} -gt 0 ]; then
    echo ""
    echo "  Missing API keys: ${missing[*]}"
    echo ""
    echo "  Set them in .env:"
    echo "    OPENAI_API_KEY=sk-..."
    echo "    ANTHROPIC_API_KEY=sk-ant-..."
    echo ""
    echo "  Or export before running:"
    echo "    export OPENAI_API_KEY=sk-..."
    echo "    ./switch.sh cloud"
    exit 1
  fi

  echo "  OpenAI key:    ${OPENAI_API_KEY:0:8}..."
  echo "  Anthropic key: ${ANTHROPIC_API_KEY:0:12}..."

  echo "cloud" > "$STATE_FILE"
  restart_gateway "cloud" "$CLOUD_CONFIG"

  echo ""
  echo "  ✓ Cloud mode active"
  echo "  Models: $(curl -s "$GATEWAY_URL/v1/models" | python3 -c "import sys,json; print(', '.join(m['id'] for m in json.load(sys.stdin)['data']))" 2>/dev/null)"
  echo "  Endpoint: $GATEWAY_URL/v1"
  echo "  (requests are forwarded to OpenAI / Anthropic)"
}

# ── Main ──────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")"

case "${1:-}" in
  local)
    switch_to_local
    ;;
  cloud)
    switch_to_cloud
    ;;
  status|"")
    show_status
    ;;
  *)
    echo "Usage: $0 [local|cloud|status]"
    exit 1
    ;;
esac
