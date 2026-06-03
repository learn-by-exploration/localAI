#!/usr/bin/env bash
# Install/update local user services and generate a gateway secret.

set -euo pipefail
cd "$(dirname "$0")"

CONFIG_DIR="$HOME/.config/local-ai-gateway"
SYSTEMD_DIR="$HOME/.config/systemd/user"
ENV_FILE="$CONFIG_DIR/gateway.env"

mkdir -p "$CONFIG_DIR" "$SYSTEMD_DIR"

if [ -f "$ENV_FILE" ]; then
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

sed "s#%h#$HOME#g" services/ai-control.service > "$SYSTEMD_DIR/ai-control.service"
sed "s#%h#$HOME#g" services/local-ai-gateway.service > "$SYSTEMD_DIR/local-ai-gateway.service"

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
