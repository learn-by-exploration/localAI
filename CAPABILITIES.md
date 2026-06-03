# System Capabilities

Last tested: 2026-06-03 | Hardware: 8GB VRAM laptop | Models: qwen3:8b, gemma4:e4b, qwen2.5:1.5b

---

## What it can do

### Code generation
Qwen3 8B uses a thinking phase (~1300 tokens of internal reasoning) before writing code. Output is correct, typed, and handles edge cases. Tested: JWT decoder in 8 lines, palindrome checker, sorting algorithms.

```python
# Example: correct JWT payload decoder
def decode_jwt_payload(jwt_str: str) -> dict:
    parts = jwt_str.split('.')
    payload = parts[1].replace('-', '+').replace('_', '/')
    decoded = base64.b64decode(payload)
    return json.loads(decoded.decode('utf-8'))
```

### Bug finding and code review
Identifies both runtime bugs and logic errors. On the null-pointer test it found the `len(None)` crash AND the downstream `None['name']` dereference, with clear explanations and fixes.

### Multi-turn conversations
Remembers context across turns. Tested: "My project uses Python 3.11 and FastAPI" → follow-up "best way to add rate limiting?" returned FastAPI-specific advice without re-mentioning the stack.

### System prompts / personas
Qwen3 reliably follows structured output instructions. Useful for building apps that parse AI responses.

```json
// System: "Respond only as JSON: {\"answer\": \"...\", \"confidence\": 0.9}"
// Input: "Boiling point of water? 2+2?"
{"answer": "Boiling point is 100°C. 2+2 equals 4.", "confidence": 0.9}
```

### Structured output (JSON)
With a strong system prompt, Qwen3 returns valid JSON for structured tasks:

```json
// "Analyze this function and return JSON with bugs, improvements, complexity"
{
  "bugs": ["No division-by-zero guard", "No fallback for unknown op"],
  "improvements": ["Use a dict to map ops to lambdas"],
  "complexity": "low"
}
```

### Code explanation
- qwen-small (1.5B): explains simple code in 1-2 seconds
- qwen3 (8B): explains complex patterns (closures, recursion, algorithms) with depth

### Long-context document Q&A (128k)
Gemma4 E4B supports 128k token context. Paste an entire codebase, long spec, or documentation and ask questions about it.

### API for applications
Full OpenAI-compatible REST API at `http://localhost:8080/v1`. Drop-in replacement for any OpenAI or Anthropic client — swap the base URL.

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8080/v1", api_key="local")
```

### Concurrent requests
Queue manager handles multiple clients simultaneously. opencode + VS Code Continue + your own app can all use the gateway at the same time (up to 2 concurrent, configurable).

---

## What it does NOT do well

### Claude Code agentic mode
Claude Code's file-editing and bash execution requires the model to output Anthropic tool-call JSON. Local models respond in plain text. `claude --print` (chat/explain) works fine; the full agentic loop does not.

**Workaround:** use `opencode` for file editing, `claude --print` for questions.

### Auto-routing misses some prompts
The smart router matches specific keywords (`python`, `function`, `debug`, `class`, `sql`, etc.). Prompts without these keywords route to `chat` (gemma4) even if they're coding questions. Example: "Write a FastAPI route" doesn't match because "FastAPI" isn't a keyword.

**Workaround:** explicitly pass `"model": "qwen3-8b"` or a coding alias (`claude-sonnet`, `gpt-4`).

### Vision / image understanding
None of the currently pulled models are multimodal.

**If needed:** pull `llava` or `gemma3` (supports vision) and add to models.yaml.

### Real-time web search
No internet access. Knowledge cutoff applies (Qwen3: early 2025).

**Workaround:** paste content into the prompt, or add a RAG pipeline.

### Speed on complex tasks
Qwen3 8B: 20-30 seconds per complex coding task (thinking mode uses the time well).
For instant responses use `qwen-small` (~1-2s) or pull `qwen3:4b` (~10s, 2.5GB).

---

## Hardware limits (8GB VRAM)

| Model | VRAM | Speed | Best for |
|---|---|---|---|
| qwen3:8b | 5.5 GB | 20-30s | Code, reasoning, bugs |
| gemma4:e4b | 9.6 GB† | 15-25s | Long context (128k), general |
| qwen2.5:1.5b | 1.5 GB | 1-2s | Quick Q&A, autocomplete |
| qwen3:4b | ~2.5 GB | ~10s | Balance of speed + quality |

† Gemma4 at 9.6GB exceeds 8GB VRAM — Ollama offloads some layers to RAM. Works but slower.

Gateway loads one model at a time, switches on demand, and auto-unloads after 10 minutes idle.

---

## Quality ceiling

**Qwen3 8B ≈ GPT-3.5 level** on most coding tasks.

Handles well:
- Explaining and reviewing code
- Writing boilerplate and standard implementations
- Debugging known patterns
- Q&A, documentation, code comments
- Structured output for app development
- Quick local testing without burning cloud credits

Struggles with:
- Complex multi-file refactoring decisions (no full codebase awareness)
- Subtle architectural tradeoffs in large systems
- Very recent frameworks and libraries (training cutoff)
- Tasks requiring web search or real-time data

---

## Tool integration summary

| Tool | Works | Mode |
|---|---|---|
| opencode | ✅ Full | TUI, file editing, `--model local/qwen3-8b` |
| VS Code Continue | ✅ Full | Chat (`Ctrl+L`), inline (`Ctrl+I`), autocomplete |
| Open WebUI | ✅ Full | Browser chat, model switching, Gateway Control |
| Claude Code `--print` | ✅ Chat only | Questions, explanations, reviews |
| Claude Code agentic | ❌ | Tool calls not supported by local models |
| Any OpenAI SDK app | ✅ Full | Set `base_url="http://localhost:8080/v1"` |
| Any Anthropic SDK app | ✅ Full | Set `base_url="http://localhost:8080"` |
| curl / raw HTTP | ✅ Full | Standard POST to `/v1/chat/completions` |
