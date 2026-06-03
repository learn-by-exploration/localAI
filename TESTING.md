# Testing

Use this checklist after changing setup scripts, services, control-server behavior, or Open WebUI integration.

## Dry-Run Install

Preview generated env/service files without modifying live user services:

```bash
./install.sh --dry-run
```

Expected:

- files are written under `/tmp/local-ai-gateway-dry-run`
- no live `~/.config/local-ai-gateway/gateway.env` is created
- live `~/.config/systemd/user/ai-control.service` is not modified

Inspect generated files:

```bash
cat /tmp/local-ai-gateway-dry-run/config/gateway.env
cat /tmp/local-ai-gateway-dry-run/systemd/ai-control.service
cat /tmp/local-ai-gateway-dry-run/systemd/local-ai-gateway.service
```

Verify generated service units:

```bash
systemd-analyze --user verify \
  /tmp/local-ai-gateway-dry-run/systemd/ai-control.service \
  /tmp/local-ai-gateway-dry-run/systemd/local-ai-gateway.service
```

## Doctor

Run:

```bash
./doctor.sh
```

Expected on an idle machine:

- `ai-control.service` is running
- Open WebUI can reach the control server if the `open-webui` container is running
- gateway and Ollama may be stopped
- suggested Open WebUI valves are printed

## Control Diagnostics

Test the current source code in-process without restarting the live service:

```bash
python3 - <<'PY'
from fastapi.testclient import TestClient
import control_server

client = TestClient(control_server.app)
for path in ["/status", "/diagnostics"]:
    resp = client.get(path)
    print(path, resp.status_code, sorted(resp.json().keys()))
PY
```

Expected:

```text
/status 200 [...]
/diagnostics 200 [...]
```

If the live endpoint returns `404`, the running `ai-control.service` has not been restarted since the diagnostics code was added:

```bash
curl http://172.17.0.1:8089/diagnostics
```

Activate the new code with:

```bash
systemctl --user restart ai-control.service
```

Or run the full installer:

```bash
./install.sh
```

## Compile and Unit Tests

Run:

```bash
python3 -m compileall src control_server.py openwebui_function.py
python3 -m pytest -q --no-cov
bash -n install.sh doctor.sh start.sh stop.sh switch.sh
git diff --check
```

Expected:

```text
38 passed
```

The FastAPI `TestClient` suite may print a Starlette deprecation warning about `httpx`; this is currently non-fatal.

## Open WebUI Container Reachability

From inside the Open WebUI container:

```bash
docker exec open-webui python3 - <<'PY'
import urllib.request
print(urllib.request.urlopen("http://host.docker.internal:8089/status", timeout=3).read().decode())
PY
```

Expected:

```json
{"ollama": false, "gateway": false}
```

If it fails, check:

```bash
docker inspect open-webui --format '{{json .HostConfig.ExtraHosts}}'
ss -ltnp | rg '8089|8080|11434'
systemctl --user status ai-control.service --no-pager
```

## Git State

Before pushing:

```bash
git status --short --branch
git log --oneline --decorate -3
```

After pushing, `main` should be aligned with `origin/main`.
