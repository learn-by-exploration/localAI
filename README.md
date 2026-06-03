# Local AI Gateway

Run local AI models through a single OpenAI and Anthropic-compatible endpoint. Smart routing, fallback chains, VRAM guardrails, live dashboard, and zero-config tool integration.

```
opencode / VS Code Continue / Open WebUI / Claude Code / curl / any OpenAI client
                              ↓
                 Local AI Gateway  :8080
                              ↓
         ┌─ Model Registry      config/models.yaml
         ├─ Smart Router        coding → qwen3 | chat → gemma4 | fast → qwen-small
         ├─ Model Lifecycle     start / stop / auto-unload after 10min idle
         ├─ Queue Manager       max concurrent requests (semaphore)
         ├─ Resource Guardrails VRAM / RAM checks before loading
         └─ Model Profiler      tokens/sec benchmark
                              ↓
         Adapters: Ollama | llama.cpp | vLLM | SGLang | Cloud (OpenAI/Anthropic)
```

## Current models (pulled)

| ID | Ollama name | Role | VRAM | Notes |
|---|---|---|---|---|
| `qwen3-8b` | `qwen3:8b` | coding | ~5.5 GB | Default. Thinking mode, best for code. |
| `gemma4-chat` | `gemma4:e4b` | chat | ~9.6 GB | 128k context, general purpose. |
| `qwen-small` | `qwen2.5:1.5b` | chat | ~1.5 GB | Instant responses, minimal VRAM. |

Add more in `config/models.yaml` and enable with `ollama pull <name>`.

---

## Quick start

```bash
# 1. Install Ollama (if not already installed)
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull models
ollama pull qwen3:8b        # best for coding (~5 GB)
ollama pull qwen2.5:1.5b    # fast fallback (~1 GB)

# 3. Start everything
cd local-ai-gateway
bash start.sh
```

**URLs after start:**
- Dashboard: http://localhost:8080
- API: http://localhost:8080/v1
- Open WebUI: http://localhost:3000 (Docker, auto-started)

**Stop when done:**
```bash
bash stop.sh
```

Or from Open WebUI → **Gateway Control** model → type `stop`.

---

## API reference

### Chat — OpenAI format

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-8b",
    "messages": [{"role": "user", "content": "Write a quicksort in Python"}],
    "stream": true
  }'
```

### Chat — Anthropic format

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

### Model management

```bash
# List enabled models
curl http://localhost:8080/api/models

# Load a model
curl -X POST http://localhost:8080/api/models/start \
  -H "Content-Type: application/json" -d '{"model_id": "qwen3-8b"}'

# Unload current model (free VRAM)
curl -X POST http://localhost:8080/api/models/stop

# Switch to a different model
curl -X POST http://localhost:8080/api/models/switch \
  -H "Content-Type: application/json" -d '{"model_id": "qwen-small"}'

# Benchmark current model (tokens/sec)
curl -X POST http://localhost:8080/api/models/qwen3-8b/profile

# Live system metrics (SSE stream)
curl -N http://localhost:8080/api/metrics/stream
```

### Profile switching (local ↔ cloud)

```bash
# Switch to local Ollama models (default)
curl -X POST http://localhost:8080/api/profile \
  -H "Content-Type: application/json" -d '{"profile": "local"}'

# Switch to cloud APIs
curl -X POST http://localhost:8080/api/profile \
  -H "Content-Type: application/json" \
  -d '{"profile": "cloud", "openai_api_key": "sk-...", "anthropic_api_key": "sk-ant-..."}'

# Check current profile
curl http://localhost:8080/api/profile
```

---

## Model aliases

Any of these names in `"model"` are accepted and mapped to local models. No client reconfiguration needed.

| Name | Routes to | Notes |
|---|---|---|
| `qwen3-8b` | qwen3:8b | Direct ID |
| `qwen-small` | qwen2.5:1.5b | Direct ID |
| `gemma4-chat` | gemma4:e4b | Direct ID |
| `active` | qwen3-8b | Default best model |
| `claude-sonnet` | qwen3-8b | |
| `claude-sonnet-4-6` | qwen3-8b | Versioned (used by Claude Code CLI) |
| `claude-opus` | qwen3-8b | |
| `claude-haiku` | qwen-small | |
| `claude-haiku-4-5` | qwen-small | Versioned |
| `gpt-4` | qwen3-8b | |
| `gpt-4o` | qwen3-8b | |
| `gpt-3.5-turbo` | qwen-small | |
| `auto` | smart-routed | Task-type detection |

Update aliases in `config/models.yaml` when you pull new models.

---

## Coding tools integration

### openai SDK (Python)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="local"          # required field, value ignored
)

# Non-streaming
response = client.chat.completions.create(
    model="qwen3-8b",
    messages=[{"role": "user", "content": "Write a binary search function"}],
)
print(response.choices[0].message.content)

# Streaming
stream = client.chat.completions.create(
    model="qwen3-8b",
    messages=[{"role": "user", "content": "Explain recursion"}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

**Note on Qwen3:** It uses ~1300 thinking tokens before answering. For reliable results set `max_tokens >= 2048`, or omit it to let Ollama decide. For instant responses use `model="qwen-small"`.

### anthropic SDK (Python)

```python
import anthropic

client = anthropic.Anthropic(
    base_url="http://localhost:8080",
    api_key="local"
)

message = client.messages.create(
    model="claude-sonnet",   # → qwen3-8b via alias
    max_tokens=500,
    messages=[{"role": "user", "content": "Review this code: ..."}]
)
print(message.content[0].text)
```

### opencode (terminal AI coding assistant)

The global config at `~/.config/opencode/config.json` adds a `local` provider:

```bash
# List local models
opencode models local

# Use in any project
opencode --model local/qwen3-8b
opencode --model local/qwen-small    # faster
```

Or launch the TUI from your project folder:
```bash
opencode              # press 'm' to pick local/qwen3-8b
```

### VS Code — Continue extension

Config at `~/.continue/config.json` — already set up with all three models.

- `Ctrl+L` — open Continue sidebar for chat
- `Ctrl+I` — inline edit (highlight code first)
- Bottom of sidebar: pick **Qwen3 8B** or **Qwen 2.5 1.5B**

### Claude Code CLI (`--print` mode)

Claude Code's `--print` (chat/explain) mode works with the local gateway. Agentic mode (file editing, bash) requires real Claude models.

```bash
# One-off — set per command
ANTHROPIC_BASE_URL=http://localhost:8080 ANTHROPIC_API_KEY=local \
  claude --print "explain this function" --output-format text

# Permanent alias in ~/.bashrc
alias claude-local='ANTHROPIC_BASE_URL=http://localhost:8080 ANTHROPIC_API_KEY=local claude --print --output-format text'

# Then use anywhere
claude-local "what does this code do?"
claude-local "review main.py for bugs"
```

### Open WebUI

Running at http://localhost:3000 — login: `admin@local.ai` / `localai2026!`

The **Gateway Control** model (pipe function) is pre-installed. Select it in the dropdown and type:

| Command | Action |
|---|---|
| `start` | Start Ollama + gateway, auto-load default model |
| `stop` | Unload model, stop gateway + Ollama (WebUI stays running) |
| `status` | Current profile, active model, VRAM/RAM/CPU/GPU temp |
| `switch to local` | Switch to Ollama models |
| `switch to cloud` | Switch to OpenAI/Anthropic APIs |
| `list models` | Show available models |

---

## Smart router

When `"model": "auto"` (or any unrecognised name that's not an alias), the router detects task type from message content:

| Detected | Trigger | Routes to |
|---|---|---|
| `coding` | code/function/class/debug/SQL/Python keywords | `coding` role model → qwen3-8b |
| `agent` | tools present, or tool/execute/bash keywords | `agent` role model |
| `long_context` | message > ~2000 tokens | `long_context` role model → gemma4-chat |
| `chat` | default | `chat` role model → gemma4-chat |

Explicit model ID (e.g. `"model": "qwen-small"`) always bypasses routing.

---

## Model registry (`config/models.yaml`)

```yaml
models:
  - id: qwen3-8b
    name: Qwen3 8B (Coding + Thinking)
    runner: ollama          # ollama | llamacpp | vllm | sglang
    model: qwen3:8b
    role: coding            # coding | chat | agent | long_context
    priority: quality       # fast | balanced | quality
    context_length: 32768
    vram_required_mb: 5500
    enabled: true
    extra:
      min_tokens: 2048      # Qwen3 needs budget for thinking phase

default_model: qwen3-8b

aliases:
  - alias: claude-sonnet
    model_id: qwen3-8b

fallback_chains:
  - name: coding
    models: [qwen3-8b, gemma4-chat, qwen-small]
```

### Adding a new model

```bash
# 1. Pull it
ollama pull llama3.2:3b

# 2. Add to config/models.yaml
- id: llama3-fast
  name: Llama 3.2 3B
  runner: ollama
  model: llama3.2:3b
  role: chat
  priority: fast
  context_length: 128000
  vram_required_mb: 2000
  enabled: true

# 3. Restart gateway (or hot-switch via API)
bash stop.sh && bash start.sh
```

---

## Supported runtimes

| Runtime | Install | Best for |
|---|---|---|
| **Ollama** | `curl -fsSL https://ollama.com/install.sh \| sh` | GGUF models, easy setup — start here |
| **llama.cpp** | Build from source | Fine-grained GGUF control, CPU/GPU |
| **vLLM** | `pip install vllm` | Full-precision HuggingFace models, high throughput |
| **SGLang** | `pip install "sglang[all]"` | Structured generation, high throughput |

---

## Resource guardrails

| Setting | Default | Env var |
|---|---|---|
| Max VRAM | 12,000 MB | `MAX_VRAM_MB` |
| Max RAM | 28,000 MB | `MAX_RAM_MB` |
| Max concurrent requests | 2 | — |
| Auto-unload idle | 600s (10 min) | `AUTO_UNLOAD_SECONDS` |
| Gateway port | 8080 | `PORT` |
| Models config | config/models.yaml | `MODELS_CONFIG` |

---

## Security

The control server (port 8089) and `/api/profile` endpoint support an optional shared secret:

```bash
# Set in .env
GATEWAY_SECRET=my-secret

# Pass in requests
curl http://localhost:8089/status -H "X-Gateway-Secret: my-secret"
```

Without `GATEWAY_SECRET`, both services are localhost-only (bound to `127.0.0.1`) and require no auth — safe for personal use.

---

## Tests

```bash
# Unit tests (38 tests, ~3s)
python3 -m pytest tests/ -v

# Integration tests (38 tests, requires gateway + Ollama running)
bash tests/integration/run_tests.sh
```

See [TEST_REPORT.md](TEST_REPORT.md) for full results.

---

## Project structure

```
local-ai-gateway/
├── config/
│   ├── models.yaml              # Local model definitions, aliases, fallback chains
│   └── cloud_models.yaml        # Cloud API model definitions (OpenAI, Anthropic)
├── src/
│   ├── main.py                  # FastAPI app, startup/shutdown
│   ├── api/
│   │   ├── openai_compat.py     # POST /v1/chat/completions, GET /v1/models
│   │   ├── anthropic_compat.py  # POST /v1/messages
│   │   ├── models_api.py        # /api/models start/stop/switch/profile
│   │   ├── metrics_api.py       # /api/metrics, /api/metrics/stream (SSE)
│   │   └── profile_api.py       # /api/profile (hot-reload local/cloud switch)
│   ├── core/
│   │   ├── registry.py          # Loads and resolves models.yaml
│   │   ├── router.py            # Task-type detection + model selection
│   │   ├── lifecycle.py         # Model start/stop/auto-unload (asyncio.Lock)
│   │   ├── queue_manager.py     # Semaphore for concurrent requests + streaming
│   │   ├── guardrails.py        # VRAM/RAM checks via nvidia-smi / psutil
│   │   ├── profiler.py          # tokens/sec benchmark, persistent cache
│   │   └── profile_manager.py   # Hot-reload local↔cloud profile switching
│   ├── adapters/
│   │   ├── ollama.py            # Ollama HTTP adapter (primary)
│   │   ├── llamacpp.py          # llama-server subprocess adapter
│   │   ├── vllm.py              # vLLM subprocess adapter
│   │   ├── sglang.py            # SGLang subprocess adapter
│   │   ├── cloud_openai.py      # OpenAI API passthrough
│   │   └── cloud_anthropic.py   # Anthropic API passthrough
│   ├── schemas/
│   │   ├── unified.py           # Internal request/response types
│   │   ├── openai_schema.py     # OpenAI API schema
│   │   └── anthropic_schema.py  # Anthropic API schema (accepts list system blocks)
│   └── dashboard/static/        # HTML/CSS/JS live dashboard
├── control_server.py            # Always-on control server :8089
├── openwebui_function.py        # Open WebUI pipe function (Gateway Control)
├── tests/
│   ├── test_registry.py
│   ├── test_router.py
│   ├── test_queue_manager.py
│   ├── test_api.py
│   └── integration/
│       └── run_tests.sh
├── start.sh                     # Start Ollama + Open WebUI + gateway
├── stop.sh                      # Stop everything, free VRAM
├── switch.sh                    # CLI profile switcher (local/cloud)
├── TEST_REPORT.md
└── pyproject.toml
```
