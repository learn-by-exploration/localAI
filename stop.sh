#!/usr/bin/env bash
# Stop everything cleanly — run this when you're done working

echo "Stopping Local AI Gateway..."

[ -f "$HOME/.config/local-ai-gateway/gateway.env" ] && export $(grep -v '^#' "$HOME/.config/local-ai-gateway/gateway.env" | grep '=' | xargs) 2>/dev/null || true
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080}"

# 1. Unload model from VRAM
curl -s --max-time 5 -X POST "$GATEWAY_URL/api/models/stop" \
  -H "Content-Type: application/json" > /dev/null 2>&1 && echo "  ✓ Model unloaded from VRAM" || true

# 2. Stop gateway
if systemctl --user list-unit-files local-ai-gateway.service --no-legend 2>/dev/null | grep -q '^local-ai-gateway.service'; then
  systemctl --user stop local-ai-gateway.service 2>/dev/null && echo "  ✓ Gateway stopped" || echo "  - Gateway was not running"
else
  fuser -k 8080/tcp 2>/dev/null && echo "  ✓ Gateway stopped" || echo "  - Gateway was not running"
fi

# 3. Stop Ollama
if curl -s --max-time 2 http://localhost:11434/api/tags > /dev/null 2>&1; then
  if systemctl list-unit-files ollama.service --no-legend 2>/dev/null | grep -q '^ollama.service'; then
    systemctl --no-ask-password stop ollama.service 2>/dev/null || true
  else
    pkill -f "ollama serve" 2>/dev/null || true
  fi

  sleep 1
  if curl -s --max-time 2 http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "  - Ollama still running (admin permission may be required for ollama.service)"
  else
    echo "  ✓ Ollama stopped"
  fi
else
  echo "  - Ollama was not running"
fi

# 4. Stop Open WebUI (Docker)
docker stop open-webui 2>/dev/null && echo "  ✓ Open WebUI stopped" || echo "  - Open WebUI was not running"

echo ""
echo "Done. GPU memory freed."
