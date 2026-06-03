#!/usr/bin/env bash
# Install/update local user services and generate a gateway secret.

set -euo pipefail
cd "$(dirname "$0")"

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
fi

CONFIG_DIR="$HOME/.config/local-ai-gateway"
SYSTEMD_DIR="$HOME/.config/systemd/user"
ENV_FILE="$CONFIG_DIR/gateway.env"
OUT_CONFIG_DIR="$CONFIG_DIR"
OUT_SYSTEMD_DIR="$SYSTEMD_DIR"

if [ "$DRY_RUN" = "1" ]; then
  OUT_CONFIG_DIR="/tmp/local-ai-gateway-dry-run/config"
  OUT_SYSTEMD_DIR="/tmp/local-ai-gateway-dry-run/systemd"
  ENV_FILE="$OUT_CONFIG_DIR/gateway.env"
  rm -rf /tmp/local-ai-gateway-dry-run
fi

mkdir -p "$OUT_CONFIG_DIR" "$OUT_SYSTEMD_DIR"

if [ "$DRY_RUN" != "1" ] && [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

GATEWAY_SECRET="${GATEWAY_SECRET:-$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)}"

cat > "$ENV_FILE" <<EOF
GATEWAY_SECRET=$GATEWAY_SECRET
CONTROL_HOST=${CONTROL_HOST:-172.17.0.1}
CONTROL_PORT=${CONTROL_PORT:-8089}
GATEWAY_HOST=${GATEWAY_HOST:-172.17.0.1}
GATEWAY_PORT=${GATEWAY_PORT:-8080}
GATEWAY_URL=http://${GATEWAY_HOST:-172.17.0.1}:${GATEWAY_PORT:-8080}
MODELS_CONFIG=${MODELS_CONFIG:-config/active_models.yaml}
EOF

sed "s#%h#$HOME#g" services/ai-control.service > "$OUT_SYSTEMD_DIR/ai-control.service"
sed "s#%h#$HOME#g" services/local-ai-gateway.service > "$OUT_SYSTEMD_DIR/local-ai-gateway.service"

if [ "$DRY_RUN" = "1" ]; then
  echo "Dry run only. Files were written to /tmp/local-ai-gateway-dry-run:"
  echo "  $ENV_FILE"
  echo "  $OUT_SYSTEMD_DIR/ai-control.service"
  echo "  $OUT_SYSTEMD_DIR/local-ai-gateway.service"
  echo ""
  cat "$ENV_FILE"
  exit 0
fi

systemctl --user daemon-reload
systemctl --user enable --now ai-control.service

echo "Installed user services."
echo "Control URL: http://${CONTROL_HOST:-172.17.0.1}:${CONTROL_PORT:-8089}"
echo "Gateway URL: http://${GATEWAY_HOST:-172.17.0.1}:${GATEWAY_PORT:-8080}"
echo ""
echo "Open WebUI function valves:"
echo "  CONTROL_URL: http://host.docker.internal:${CONTROL_PORT:-8089}"
echo "  GATEWAY_URL:  http://host.docker.internal:${GATEWAY_PORT:-8080}"
echo "  GATEWAY_SECRET: $GATEWAY_SECRET"
echo ""
echo "Run ./doctor.sh to verify everything."
