# Local AI Gateway

A local model orchestration layer with OpenAI and Anthropic-compatible APIs. Run Qwen, Gemma, MiniMax and future models through one endpoint — with smart routing, fallback chains, resource guardrails, and a live dashboard.

```
Open WebUI / Continue / Cline / curl / any OpenAI client
              ↓
    Local AI Gateway  (FastAPI :8080)
              ↓
    ┌─ Model Registry      config/models.yaml
    ├─ Smart Router        coding / chat / agent / long-context
    ├─ Model Lifecycle     start / stop / auto-unload on idle
    ├─ Queue Manager       concurrent request limit
    ├─ Resource Guardrails VRAM / RAM checks
    └─ Model Profiler      tokens/sec benchmark
              ↓
    Adapters: Ollama | llama.cpp | vLLM | SGLang
```

## Quick Start

**Prerequisites:** Ollama installed and running (`ollama serve`).

```bash
git clone <repo>
cd local-ai-gateway

# Pull at least one model
ollama pull qwen2.5:1.5b

# Install package deps
pip install -e .

# Install user services, generate GATEWAY_SECRET, and start the control server
./install.sh

# Preview generated env/service files without changing live systemd config
./install.sh --dry-run

# Check Open WebUI/control/gateway/Ollama wiring
./doctor.sh

# Start the gateway and Ollama
curl -X POST http://172.17.0.1:8089/start \
  -H "X-Gateway-Secret: $(grep '^GATEWAY_SECRET=' ~/.config/local-ai-gateway/gateway.env | cut -d= -f2-)"
```

Manual run is also supported:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8080

# Or use the convenience script
bash start.sh
```

Dashboard: http://localhost:8080  
API docs: http://localhost:8080/docs

## API Endpoints

### Chat (OpenAI-compatible)

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "active",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

### Chat (Anthropic-compatible)

```bash
curl http://localhost:8080/v1/messages \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-haiku",
    "max_tokens": 256,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Model Management

```bash
# List models
curl http://localhost:8080/api/models

# Start a model
curl -X POST http://localhost:8080/api/models/start \
  -H "Content-Type: application/json" \
  -d '{"model_id": "qwen-small"}'

# Stop current model
curl -X POST http://localhost:8080/api/models/stop

# Switch to a different model
curl -X POST http://localhost:8080/api/models/switch \
  -H "Content-Type: application/json" \
  -d '{"model_id": "qwen-coder-fast"}'

# Run a benchmark
curl -X POST http://localhost:8080/api/models/qwen-small/profile

# Live metrics (SSE)
curl -N http://localhost:8080/api/metrics/stream
```

## Connect Your Tools

### Open WebUI

```
Admin Panel → Settings → Connections → OpenAI API
Base URL: http://localhost:8080/v1
API Key:  local
```

If Open WebUI runs in Docker, use the host alias instead:

```
Base URL: http://host.docker.internal:8080/v1
API Key:  local
```

Or run via Docker (pre-connected to the gateway):

```bash
docker run -d \
  -p 3000:8080 \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8080/v1 \
  -e OPENAI_API_KEY=local \
  --add-host=host.docker.internal:host-gateway \
  -v open-webui:/app/backend/data \
  --name open-webui \
  ghcr.io/open-webui/open-webui:main
```

### Open WebUI Gateway Control

The file `openwebui_function.py` is an Open WebUI function that lets you control the gateway from chat. It can:

| Chat command | What it does |
|---|---|
| `start` | Starts Ollama if needed, starts the gateway, and auto-loads the default model |
| `stop` | Unloads the current model, stops the gateway, and stops Ollama when permitted |
| `status` | Shows Ollama, gateway, active model, VRAM, RAM, CPU, and GPU temperature |
| `diagnostics` | Shows service, Docker, secret, and permission checks |
| `switch to local` | Switches the gateway to local/Ollama models |
| `switch to cloud` | Switches the gateway to cloud passthrough models |
| `use fast` | Switches to `qwen-small` |
| `use coding` | Switches to `qwen-coder-fast` |
| `use <model_id>` | Switches to a specific model ID |
| `list models` | Lists the gateway model IDs |

Install it in Open WebUI:

1. Open `http://localhost:3000`.
2. Go to `Admin Panel -> Functions`.
3. Create or import a function.
4. Paste the contents of `openwebui_function.py`.
5. Enable the function.
6. Open the function settings and check these valves:

| Valve | Docker Open WebUI value | Host Open WebUI value |
|---|---|---|
| `GATEWAY_URL` | `http://host.docker.internal:8080` | `http://localhost:8080` |
| `CONTROL_URL` | `http://host.docker.internal:8089` | `http://localhost:8089` |
| `GATEWAY_SECRET` | Same as `GATEWAY_SECRET` env var, or blank if unset | Same as `GATEWAY_SECRET` env var, or blank if unset |
| `OPENAI_API_KEY` | Optional, only for cloud mode | Optional, only for cloud mode |
| `ANTHROPIC_API_KEY` | Optional, only for cloud mode | Optional, only for cloud mode |

The control server runs separately from the gateway. That is why `start` still works when the gateway is offline.

`./install.sh` writes this env file:

```text
~/.config/local-ai-gateway/gateway.env
```

It contains:

| Variable | Purpose |
|---|---|
| `GATEWAY_SECRET` | Shared secret for protected control/profile/diagnostics endpoints |
| `CONTROL_HOST` / `CONTROL_PORT` | Bind address for the always-on control server |
| `GATEWAY_HOST` / `GATEWAY_PORT` | Bind address for the gateway service |
| `GATEWAY_URL` | Control server's URL for the gateway |
| `MODELS_CONFIG` | Active model config loaded on gateway startup |

Recommended user services for Docker-based Open WebUI:

```ini
[Unit]
Description=AI Gateway Control Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/shyam/common_games/local-ai-gateway
EnvironmentFile=-/home/shyam/.config/local-ai-gateway/gateway.env
ExecStart=/home/shyam/.local/bin/uvicorn control_server:app --host ${CONTROL_HOST} --port ${CONTROL_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

```ini
[Unit]
Description=Local AI Gateway
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/shyam/common_games/local-ai-gateway
EnvironmentFile=-/home/shyam/.config/local-ai-gateway/gateway.env
ExecStart=/home/shyam/.local/bin/uvicorn src.main:app --host ${GATEWAY_HOST} --port ${GATEWAY_PORT}
Restart=on-failure
RestartSec=3
TimeoutStopSec=30

[Install]
WantedBy=default.target
```

Use `172.17.0.1` for Docker bridge access. This lets Open WebUI reach the control server through `host.docker.internal` without exposing the control server on every network interface.

After editing the service:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ai-control.service
systemctl --user enable local-ai-gateway.service
systemctl --user restart ai-control.service
```

Verify from the host:

```bash
curl http://172.17.0.1:8089/status
```

Diagnostics:

```bash
curl http://172.17.0.1:8089/diagnostics \
  -H "X-Gateway-Secret: $GATEWAY_SECRET"

curl http://172.17.0.1:8080/api/diagnostics \
  -H "X-Gateway-Secret: $GATEWAY_SECRET"
```

Verify from the Open WebUI container:

```bash
docker exec open-webui python3 - <<'PY'
import urllib.request
print(urllib.request.urlopen("http://host.docker.internal:8089/status", timeout=3).read().decode())
PY
```

Expected response:

```json
{"ollama": false, "gateway": false}
```

If `GATEWAY_SECRET` is set, include it in requests:

```bash
curl http://172.17.0.1:8089/status \
  -H "X-Gateway-Secret: $GATEWAY_SECRET"
```

### Stopping System Ollama Without Prompts

If Ollama is installed as a system service, it usually runs as user `ollama` under `ollama.service`. A user-level control server cannot kill that process directly. It must ask systemd to stop `ollama.service`.

The control server uses:

```bash
systemctl --no-ask-password stop ollama.service
```

This prevents password popups. If your user is already allowed to manage the service, Open WebUI can fully stop Ollama. If not, `stop` will still unload the model and stop the gateway, but it will report that Ollama needs admin permission.

To allow only user `shyam` to start/stop/restart only `ollama.service`, add this polkit rule once:

```bash
sudo tee /etc/polkit-1/rules.d/49-ollama-control.rules >/dev/null <<'EOF'
polkit.addRule(function(action, subject) {
  if (
    subject.user == "shyam" &&
    action.id == "org.freedesktop.systemd1.manage-units" &&
    action.lookup("unit") == "ollama.service" &&
    ["start", "stop", "restart"].indexOf(action.lookup("verb")) >= 0
  ) {
    return polkit.Result.YES;
  }
});
EOF

sudo systemctl restart polkit
```

Test:

```bash
systemctl --no-ask-password start ollama.service
systemctl is-active ollama.service
systemctl --no-ask-password stop ollama.service
systemctl is-active ollama.service
```

If the last command prints `inactive` and no password prompt appears, Open WebUI `stop` can fully stop Ollama.

### Continue (VS Code / JetBrains)

```json
{
  "models": [{
    "title": "Local AI Gateway",
    "provider": "openai",
    "model": "qwen-coder-fast",
    "apiBase": "http://localhost:8080/v1",
    "apiKey": "local"
  }]
}
```

### Python (openai SDK)

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8080/v1", api_key="local")

response = client.chat.completions.create(
    model="active",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True,
)
for chunk in response:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Model Registry (config/models.yaml)

Enable/disable models and set their roles:

```yaml
models:
  - id: qwen-coder-fast
    name: Qwen2.5 Coder 7B
    runner: ollama          # ollama | llamacpp | vllm | sglang
    model: qwen2.5-coder:7b
    role: coding            # coding | chat | agent | long_context
    priority: fast          # fast | balanced | quality
    context_length: 32768
    vram_required_mb: 5000
    enabled: true

default_model: qwen-coder-fast

# Cloud model name aliases — clients using these names work transparently
aliases:
  - alias: claude-sonnet
    model_id: qwen-coder-fast
  - alias: gpt-4
    model_id: qwen-coder-fast

# Fallback chains — tried in order if primary model fails
fallback_chains:
  - name: coding
    models: [qwen-coder-fast, qwen-small]
```

## Smart Router

The router detects task type from the message content and routes accordingly:

| Detected type | Trigger | Model role used |
|---|---|---|
| `coding` | Code/function/class/debug keywords | `coding` role |
| `agent` | Tool definitions present, or tool/execute keywords | `agent` role |
| `long_context` | Message > ~2000 tokens | `long_context` role |
| `chat` | Default | `chat` role |

Override by passing an exact model ID as `"model"` in the request.

## Supported Runtimes

| Runtime | Install | Best for |
|---|---|---|
| **Ollama** | `curl -fsSL https://ollama.com/install.sh \| sh` | GGUF models, easy setup — recommended start |
| **llama.cpp** | Build from source | Fine-grained GGUF control, CPU/GPU |
| **vLLM** | `pip install vllm` | Full-precision HuggingFace models, high throughput |
| **SGLang** | `pip install "sglang[all]"` | Structured generation, high throughput |

## Resource Guardrails

Configured in `src/core/config.py` or via environment variables:

| Setting | Default | Env var |
|---|---|---|
| Max VRAM | 12,000 MB | `MAX_VRAM_MB` |
| Max RAM | 28,000 MB | `MAX_RAM_MB` |
| Max concurrent requests | 2 | — |
| Auto-unload idle timeout | 600s (10min) | `AUTO_UNLOAD_SECONDS` |
| Gateway port | 8080 | `PORT` |
| Models config path | config/models.yaml | `MODELS_CONFIG` |

## FAQ and Fixes

### What improvements are included in this ops pass?

| Area | Improvement |
|---|---|
| Setup | `install.sh` creates user services, env config, and a shared `GATEWAY_SECRET` |
| Diagnostics | `doctor.sh`, control `/diagnostics`, and gateway `/api/diagnostics` explain common failures |
| Service management | The control server prefers `local-ai-gateway.service` over port-killing |
| Docker reachability | Services default to Docker bridge bind `172.17.0.1` for Open WebUI containers |
| Security | Control/profile/diagnostics endpoints support `X-Gateway-Secret` |
| Reliability | Model stop waits briefly for active queued/streaming requests to finish |
| Profile persistence | Local/cloud switches update `.gateway_profile` and `config/active_models.yaml` |
| Open WebUI UX | Adds `diagnostics`, `use fast`, `use coding`, and `use <model_id>` commands |
| Tests | Adds diagnostics and queue idle-wait coverage |

Run this after pulling updates:

```bash
./install.sh
./doctor.sh
```

### `stop` says Ollama stopped, but `status` says Ollama is running

This means the stop command did not verify Ollama after trying to stop it. The current control server reports based on the final health check at `http://localhost:11434/api/tags`.

Check manually:

```bash
curl http://localhost:11434/api/tags
systemctl is-active ollama.service
ps -eo pid,user,comm,args | rg 'ollama|PID'
```

If Ollama is managed by `ollama.service`, make sure the polkit rule in `Stopping System Ollama Without Prompts` is installed.

### Open WebUI says it cannot reach the control server

First check the host:

```bash
systemctl --user status ai-control.service --no-pager
ss -ltnp | rg 8089
curl http://172.17.0.1:8089/status
```

Then check from the container:

```bash
docker exec open-webui python3 - <<'PY'
import urllib.request
print(urllib.request.urlopen("http://host.docker.internal:8089/status", timeout=3).read().decode())
PY
```

If the host works but the container fails, confirm the Open WebUI container has the host alias:

```bash
docker inspect open-webui --format '{{json .HostConfig.ExtraHosts}}'
```

It should include:

```text
host.docker.internal:host-gateway
```

If it does not, recreate Open WebUI with:

```bash
--add-host=host.docker.internal:host-gateway
```

### Why not bind the control server to `0.0.0.0`?

The control server can start and stop local services, so it should not be exposed to the whole LAN. For Docker-based Open WebUI, bind it to the Docker host bridge:

```text
172.17.0.1:8089
```

For host-only use, bind it to:

```text
127.0.0.1:8089
```

Only use `0.0.0.0` if you have a real network access-control plan and `GATEWAY_SECRET` enabled.

### Open WebUI `stop` asks for a password

The control server should use:

```bash
systemctl --no-ask-password stop ollama.service
```

If a password prompt still appears, restart the user service so it is running the latest code:

```bash
systemctl --user daemon-reload
systemctl --user restart ai-control.service
```

If Ollama still cannot be stopped, install the polkit rule in `Stopping System Ollama Without Prompts`.

### Open WebUI `start` says `ollama start timed out`

Check whether systemd can start Ollama without a prompt:

```bash
systemctl --no-ask-password start ollama.service
systemctl is-active ollama.service
journalctl -u ollama.service --since '5 minutes ago' --no-pager
```

If `systemctl` cannot start it without permission, install the polkit rule. If it starts but `/api/tags` is not reachable, check the Ollama listen address and logs.

### Open WebUI `status` shows gateway offline after `stop`

That is expected. The control server stays online on port `8089`; the gateway API on port `8080` is intentionally stopped. Type `start` in Open WebUI to bring the gateway and Ollama back.

### Gateway starts, but no model loads

Check the default model in `config/models.yaml` and whether Ollama has it pulled:

```bash
rg 'default_model|id:|model:' config/models.yaml
ollama list
ollama pull qwen2.5:1.5b
```

Then restart:

```bash
curl -X POST http://172.17.0.1:8089/start
```

### Profile switch to cloud fails

Cloud mode needs API keys. In Open WebUI function settings, set:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
```

Then use:

```text
switch to cloud
```

Request-body keys are used for adapter creation and are not written permanently to `os.environ`.

## Running Tests

```bash
# Unit tests
python3 -m pytest tests/ -v

# Integration tests (requires gateway + Ollama running)
bash tests/integration/run_tests.sh
```

See [TEST_REPORT.md](TEST_REPORT.md) for the full test results.

## Project Structure

```
local-ai-gateway/
├── config/
│   └── models.yaml          # Model definitions, aliases, fallback chains
├── src/
│   ├── main.py              # FastAPI app entry point
│   ├── api/
│   │   ├── openai_compat.py  # POST /v1/chat/completions, GET /v1/models
│   │   ├── anthropic_compat.py # POST /v1/messages
│   │   ├── models_api.py    # /api/models start/stop/switch
│   │   └── metrics_api.py   # /api/metrics, /api/metrics/stream (SSE)
│   ├── core/
│   │   ├── registry.py      # Loads and resolves models.yaml
│   │   ├── router.py        # Task detection + model selection
│   │   ├── lifecycle.py     # Model start/stop/auto-unload
│   │   ├── queue_manager.py # Concurrent request semaphore
│   │   ├── guardrails.py    # VRAM/RAM checks
│   │   └── profiler.py      # tokens/sec benchmark
│   ├── adapters/
│   │   ├── ollama.py        # Ollama HTTP adapter
│   │   ├── llamacpp.py      # llama-server subprocess adapter
│   │   ├── vllm.py          # vLLM subprocess adapter
│   │   └── sglang.py        # SGLang subprocess adapter
│   ├── schemas/
│   │   ├── unified.py       # Internal request/response types
│   │   ├── openai_schema.py # OpenAI API types
│   │   └── anthropic_schema.py # Anthropic API types
│   └── dashboard/static/    # HTML/CSS/JS dashboard
├── tests/
│   ├── test_registry.py
│   ├── test_router.py
│   ├── test_queue_manager.py
│   ├── test_api.py
│   └── integration/
│       └── run_tests.sh     # End-to-end test suite
├── TEST_REPORT.md
├── start.sh
└── pyproject.toml
```
