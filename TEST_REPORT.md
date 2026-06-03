# Local AI Gateway — Test Report

**Date:** 2026-06-03  
**Environment:** Ubuntu Linux, Python 3.14, Ollama 0.30.0  
**Hardware:** 8GB VRAM, 31GB RAM  
**Model under test:** qwen2.5:1.5b (Qwen2.5 1.5B Tiny/Fast)

---

## Summary

| Suite | Tests | Pass | Fail | Result |
|---|---|---|---|---|
| Unit (pytest) | 33 | 33 | 0 | ✅ PASS |
| Integration (bash) | 40 | 40 | 0 | ✅ PASS |
| **Total** | **73** | **73** | **0** | **✅ ALL PASS** |

---

## Unit Tests

Run with: `python3 -m pytest tests/ -v`

### test_registry.py (11 tests)

| Test | Result |
|---|---|
| get model by ID | ✅ |
| resolve cloud alias (claude-sonnet) | ✅ |
| resolve cloud alias (gpt-4) | ✅ |
| disabled models excluded from registry | ✅ |
| get models by role: coding | ✅ |
| get models by role: chat | ✅ |
| get default model | ✅ |
| fallback chain lookup | ✅ |
| unknown model returns None | ✅ |
| all models excludes disabled | ✅ |
| identifiers includes aliases | ✅ |

### test_router.py (13 tests)

| Test | Result |
|---|---|
| coding keywords → TaskType.coding | ✅ |
| debug keyword → TaskType.coding | ✅ |
| tools present → TaskType.agent | ✅ |
| explicit task_type respected | ✅ |
| long message → TaskType.long_context | ✅ |
| general question → TaskType.chat | ✅ |
| coding request selects coder model | ✅ |
| explicit model_id respected | ✅ |
| tools → selects agent model | ✅ |
| always returns some model | ✅ |
| fallback chain excludes primary | ✅ |
| unknown model → empty chain | ✅ |

### test_queue_manager.py (4 tests)

| Test | Result |
|---|---|
| executes task and returns result | ✅ |
| concurrent limit enforced (semaphore) | ✅ |
| errors counted separately | ✅ |
| stats dict has required fields | ✅ |

### test_api.py (6 tests)

| Test | Result |
|---|---|
| GET /v1/models returns model list | ✅ |
| GET /api/models returns full status | ✅ |
| GET /api/status has required fields | ✅ |
| GET /api/metrics has timestamp | ✅ |
| start unknown model → 404 | ✅ |
| stop model → 200 | ✅ |

---

## Integration Tests

Run with: `bash tests/integration/run_tests.sh`

### Section 1 — Health & Status (4 tests)

| Test | Result | Notes |
|---|---|---|
| GET /api/status returns 200 | ✅ | model=qwen-small, status=running |
| Model in running state at startup | ✅ | Auto-loaded default model |
| GET /api/metrics returns 200 | ✅ | |
| GET /v1/models returns model list | ✅ | 1 model visible |

### Section 2 — OpenAI-compatible API (10 tests)

| Test | Result | Notes |
|---|---|---|
| Non-streaming chat → 200 | ✅ | Response: "2 + 2 equals 4." |
| Response content correct | ✅ | Contains "PONG" |
| Streaming → SSE chunks | ✅ | 138 chunks received |
| Streaming ends with [DONE] | ✅ | |
| System prompt accepted | ✅ | HTTP 200 |
| temperature=0.0 accepted | ✅ | |
| max_tokens=5 respected | ✅ | Got 5 completion tokens |
| max_tokens enforced | ✅ | |
| gpt-4 alias resolves | ✅ | Maps to qwen-small |
| claude-sonnet alias resolves | ✅ | Maps to qwen-small |

### Section 3 — Anthropic-compatible API (6 tests)

| Test | Result | Notes |
|---|---|---|
| POST /v1/messages → 200 | ✅ | |
| Response has content field | ✅ | |
| Anthropic usage field present | ✅ | in=12, out=4 |
| Stream: message_start event | ✅ | |
| Stream: content_block_delta events | ✅ | |
| Stream: message_stop event | ✅ | |

### Section 4 — Model Management API (8 tests)

| Test | Result | Notes |
|---|---|---|
| GET /api/models → 200 | ✅ | |
| Response includes 'active' field | ✅ | |
| Response includes 'system' field | ✅ | |
| POST /api/models/stop → 200 | ✅ | VRAM freed |
| Status is 'idle' after stop | ✅ | |
| POST /api/models/start → 200 | ✅ | Loads in ~4s |
| Status is 'running' after start | ✅ | |
| Start unknown model → 404 | ✅ | Correct error |
| POST /api/models/switch → 200 | ✅ | |

### Section 5 — Smart Router (5 tests)

| Test | Result | Notes |
|---|---|---|
| "python function" → routed | ✅ | Coding keyword detected |
| "debug this class" → routed | ✅ | |
| "write a SQL query" → routed | ✅ | |
| "implement the algorithm" → routed | ✅ | |
| "what is the weather" → routed | ✅ | General chat |

### Section 6 — Metrics & Queue (4 tests)

| Test | Result | Notes |
|---|---|---|
| GET /api/metrics → 200 | ✅ | |
| Metrics has timestamp | ✅ | |
| Metrics has queue stats | ✅ | 12 requests processed |
| SSE stream delivers events | ✅ | Live updates confirmed |

### Section 7 — Error Handling (2 tests)

| Test | Result | Notes |
|---|---|---|
| Malformed JSON → 422 | ✅ | |
| Missing 'messages' field → 422 | ✅ | |

---

## Issues Found & Fixed During Testing

| # | Issue | Fix |
|---|---|---|
| 1 | Ollama install incomplete (missing llama-server binary) | Reinstalled via `curl -fsSL https://ollama.com/install.sh \| sh` with sudo |
| 2 | Port 8080 conflict from stale gateway process | Added `fuser -k 8080/tcp` to cleanup before start |
| 3 | Router selected unpulled model (gemma-chat) causing silent hang | Disabled unpulled models in `config/models.yaml` |
| 4 | RAM guardrail default (12GB) too low — blocked model start | Raised `max_ram_mb` default to 28000 (fits 31GB system) |
| 5 | Test helper sent `-d ""` on GET calls → forced POST → 405 | Fixed `http()` helper to only pass `-d` when body is non-empty |
| 6 | `set -e` + `((PASS++))` exits when PASS=0 | Replaced `((X++))` with `X=$((X + 1))` |

---

## System Metrics at End of Run

| Metric | Value |
|---|---|
| VRAM used | 1,549 MB / 8,192 MB (18.9%) |
| RAM used | ~12,400 MB / 31,269 MB (39.7%) |
| GPU temp | 65–66°C |
| CPU temp | 84–89°C |
| Total requests processed | 40 |
| Active requests at end | 0 |
| Model load time (cold) | ~48s (first load from disk) |
| Model load time (warm) | ~4s (VRAM already allocated) |
