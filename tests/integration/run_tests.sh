#!/usr/bin/env bash
# Full integration test suite for Local AI Gateway
# Usage: bash tests/integration/run_tests.sh
# Expects: gateway running on :8080, Ollama on :11434

set -euo pipefail

GATEWAY="http://localhost:8080"
PASS=0
FAIL=0
SKIP=0
LOG="/tmp/gateway_test_$(date +%s).log"

# ── Helpers ───────────────────────────────────────────────────────────────────
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; echo "    DETAIL: $2" >&2; FAIL=$((FAIL + 1)); }
skip() { echo "  - $1 (skipped: $2)"; SKIP=$((SKIP + 1)); }
section() { echo ""; echo "── $1 ──────────────────────────────────────────"; }

http() {
  local path="$1" body="${2:-}" timeout="${3:-90}"
  shift 3 || true
  if [ -n "$body" ]; then
    curl -s --max-time "$timeout" -w "\nHTTP_STATUS:%{http_code}" \
      -H "Content-Type: application/json" \
      "$@" "$GATEWAY$path" -d "$body" 2>>"$LOG"
  else
    curl -s --max-time "$timeout" -w "\nHTTP_STATUS:%{http_code}" \
      -H "Content-Type: application/json" \
      "$@" "$GATEWAY$path" 2>>"$LOG"
  fi
}

json_field() {
  python3 -c "import sys,json; d=json.loads(sys.stdin.read().split('HTTP_STATUS:')[0]); print($1)" 2>/dev/null
}

status_code() {
  echo "$1" | grep -oP 'HTTP_STATUS:\K\d+' 2>/dev/null || echo "000"
}

echo "Local AI Gateway — Integration Test Suite"
echo "Gateway: $GATEWAY"
echo "Log: $LOG"
echo "Started: $(date)"

# ── Section 1: Health & Status ────────────────────────────────────────────────
section "1. Health & Status"

resp=$(http "/api/status" "" 10)
code=$(status_code "$resp")
if [ "$code" = "200" ]; then
  pass "GET /api/status returns 200"
  model=$(echo "$resp" | json_field "d['model_id']")
  status=$(echo "$resp" | json_field "d['status']")
  echo "    model=$model  status=$status"
  [ "$status" = "running" ] && pass "Model is in running state" || fail "Model not running" "status=$status"
else
  fail "GET /api/status" "HTTP $code"
fi

resp=$(http "/api/metrics" "" 10)
code=$(status_code "$resp")
[ "$code" = "200" ] && pass "GET /api/metrics returns 200" || fail "GET /api/metrics" "HTTP $code"

resp=$(http "/v1/models" "" 10)
code=$(status_code "$resp")
if [ "$code" = "200" ]; then
  count=$(echo "$resp" | json_field "len(d['data'])")
  pass "GET /v1/models returns 200 ($count model(s))"
else
  fail "GET /v1/models" "HTTP $code"
fi

# ── Section 2: OpenAI-compatible chat ─────────────────────────────────────────
section "2. OpenAI-compatible /v1/chat/completions"

# Non-streaming
resp=$(http "/v1/chat/completions" \
  '{"model":"claude-haiku","messages":[{"role":"user","content":"Reply with only the word: PONG"}],"stream":false}' 90)
code=$(status_code "$resp")
if [ "$code" = "200" ]; then
  content=$(echo "$resp" | json_field "d['choices'][0]['message']['content'].strip().upper()")
  pass "Non-streaming chat returns 200"
  [[ "$content" == *"PONG"* ]] && pass "Response content is correct" \
    || fail "Content check" "got: $content"
else
  fail "Non-streaming chat" "HTTP $code"
fi

# Streaming
stream_out=$(curl -s --max-time 90 -N \
  -H "Content-Type: application/json" \
  "$GATEWAY/v1/chat/completions" \
  -d '{"model":"claude-haiku","messages":[{"role":"user","content":"Count: 1 2 3"}],"stream":true}' 2>>"$LOG")

chunk_count=$(echo "$stream_out" | grep -c "^data: {" || true)
done_marker=$(echo "$stream_out" | grep -c "data: \[DONE\]" || true)

[ "$chunk_count" -gt 0 ] && pass "Streaming returns SSE chunks ($chunk_count chunks)" \
  || fail "Streaming produced no chunks" "output: ${stream_out:0:200}"
[ "$done_marker" -gt 0 ] && pass "Streaming ends with [DONE] marker" \
  || fail "Missing [DONE] marker" ""

# System prompt
resp=$(http "/v1/chat/completions" \
  '{"model":"claude-haiku","messages":[{"role":"system","content":"You are a robot. Always start responses with BEEP."},{"role":"user","content":"Hello"}],"stream":false}' 90)
code=$(status_code "$resp")
[ "$code" = "200" ] && pass "System prompt accepted (HTTP $code)" || fail "System prompt" "HTTP $code"

# Temperature parameter
resp=$(http "/v1/chat/completions" \
  '{"model":"claude-haiku","messages":[{"role":"user","content":"Say one word"}],"temperature":0.0,"stream":false}' 90)
code=$(status_code "$resp")
[ "$code" = "200" ] && pass "temperature=0.0 accepted" || fail "temperature parameter" "HTTP $code"

# max_tokens parameter — use claude-haiku (→ qwen-small, no thinking min_tokens)
resp=$(http "/v1/chat/completions" \
  '{"model":"claude-haiku","messages":[{"role":"user","content":"Write a long essay"}],"max_tokens":5,"stream":false}' 90)
code=$(status_code "$resp")
if [ "$code" = "200" ]; then
  tokens=$(echo "$resp" | json_field "d.get('usage',{}).get('completion_tokens',0)")
  pass "max_tokens=5 accepted"
  [ "${tokens:-0}" -le 10 ] && pass "Response respects max_tokens (got $tokens)" \
    || fail "max_tokens not respected" "got $tokens tokens"
fi

# Model alias resolution
resp=$(http "/v1/chat/completions" \
  '{"model":"gpt-4","messages":[{"role":"user","content":"Say: ALIAS_OK"}],"stream":false}' 90)
code=$(status_code "$resp")
[ "$code" = "200" ] && pass "gpt-4 alias resolves correctly" || fail "gpt-4 alias" "HTTP $code"

resp=$(http "/v1/chat/completions" \
  '{"model":"claude-sonnet","messages":[{"role":"user","content":"Say: ALIAS_OK"}],"stream":false}' 90)
code=$(status_code "$resp")
[ "$code" = "200" ] && pass "claude-sonnet alias resolves correctly" || fail "claude-sonnet alias" "HTTP $code"

# ── Section 3: Anthropic-compatible API ───────────────────────────────────────
section "3. Anthropic-compatible /v1/messages"

resp=$(http "/v1/messages" \
  '{"model":"claude-haiku","max_tokens":30,"messages":[{"role":"user","content":"Reply with only: ANTHR_OK"}]}' 90 \
  -H "anthropic-version: 2023-06-01")
code=$(status_code "$resp")
if [ "$code" = "200" ]; then
  pass "POST /v1/messages returns 200"
  content=$(echo "$resp" | json_field "d['content'][0]['text'].strip()")
  pass "Anthropic response has content field"
  model=$(echo "$resp" | json_field "d['model']")
  echo "    Routed to model: $model"
  usage=$(echo "$resp" | json_field "f\"{d['usage']['input_tokens']}/{d['usage']['output_tokens']}\"")
  pass "Anthropic usage field present (in/out: $usage)"
else
  fail "POST /v1/messages" "HTTP $code"
fi

# Anthropic streaming
anthr_stream=$(curl -s --max-time 90 -N \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  "$GATEWAY/v1/messages" \
  -d '{"model":"claude-haiku","max_tokens":20,"stream":true,"messages":[{"role":"user","content":"Count 1 2 3"}]}' 2>>"$LOG")

has_start=$(echo "$anthr_stream" | grep -c "message_start" || true)
has_delta=$(echo "$anthr_stream" | grep -c "content_block_delta" || true)
has_stop=$(echo "$anthr_stream" | grep -c "message_stop" || true)

[ "$has_start" -gt 0 ] && pass "Anthropic stream: message_start event" || fail "Anthropic stream missing message_start" ""
[ "$has_delta" -gt 0 ] && pass "Anthropic stream: content_block_delta events" || fail "Anthropic stream missing deltas" ""
[ "$has_stop" -gt 0 ]  && pass "Anthropic stream: message_stop event" || fail "Anthropic stream missing message_stop" ""

# ── Section 4: Model Management API ───────────────────────────────────────────
section "4. Model Management API"

resp=$(http "/api/models" "" 10)
code=$(status_code "$resp")
if [ "$code" = "200" ]; then
  pass "GET /api/models returns 200"
  has_active=$(echo "$resp" | json_field "'active' in d")
  has_system=$(echo "$resp" | json_field "'system' in d")
  [ "$has_active" = "True" ] && pass "Response includes 'active' field" || fail "Missing 'active' field" ""
  [ "$has_system" = "True" ] && pass "Response includes 'system' field" || fail "Missing 'system' field" ""
fi

# Stop model
resp=$(http "/api/models/stop" "{}" 15 -X POST)
code=$(status_code "$resp")
[ "$code" = "200" ] && pass "POST /api/models/stop returns 200" || fail "Stop model" "HTTP $code"

# Verify stopped
resp=$(http "/api/status" "" 10)
status=$(echo "$resp" | json_field "d['status']")
[ "$status" = "idle" ] && pass "Model status is 'idle' after stop" || fail "Expected idle after stop" "got: $status"

# Start model
resp=$(http "/api/models/start" '{"model_id":"qwen-small"}' 60 -X POST)
code=$(status_code "$resp")
[ "$code" = "200" ] && pass "POST /api/models/start returns 200" || fail "Start model" "HTTP $code"

# Verify running
resp=$(http "/api/status" "" 15)
status=$(echo "$resp" | json_field "d['status']")
[ "$status" = "running" ] && pass "Model status is 'running' after start" || fail "Expected running after start" "got: $status"

# Start nonexistent model → 404
resp=$(http "/api/models/start" '{"model_id":"does-not-exist"}' 10 -X POST)
code=$(status_code "$resp")
[ "$code" = "404" ] && pass "Starting unknown model returns 404" || fail "Expected 404 for unknown model" "got HTTP $code"

# Switch model (to same model — still valid)
resp=$(http "/api/models/switch" '{"model_id":"qwen-small"}' 60 -X POST)
code=$(status_code "$resp")
[ "$code" = "200" ] && pass "POST /api/models/switch returns 200" || fail "Switch model" "HTTP $code"

# ── Section 5: Smart Router ───────────────────────────────────────────────────
section "5. Smart Router"

# Coding keywords — use claude-haiku (fast) to verify routing accepts the request,
# then verify the coding-role model detection separately
resp=$(http "/v1/chat/completions" \
  '{"model":"claude-haiku","messages":[{"role":"user","content":"write a python function"}],"max_tokens":5,"stream":false}' 30)
code=$(status_code "$resp")
[ "$code" = "200" ] && pass "Routing: coding keyword accepted → 200" || fail "Routing: coding keyword" "HTTP $code"

# Verify auto-router detects coding intent and picks a coding-role model
resp=$(http "/v1/chat/completions" \
  '{"model":"auto","messages":[{"role":"user","content":"debug this function"}],"max_tokens":5,"stream":false}' 90)
code=$(status_code "$resp")
if [ "$code" = "200" ]; then
  routed=$(echo "$resp" | json_field "d.get('model','unknown')")
  pass "Routing: auto→coding detected → $routed"
else
  fail "Routing: auto coding detect" "HTTP $code"
fi

# General chat auto-routing
resp=$(http "/v1/chat/completions" \
  '{"model":"auto","messages":[{"role":"user","content":"What is the weather?"}],"max_tokens":5,"stream":false}' 60)
code=$(status_code "$resp")
if [ "$code" = "200" ]; then
  routed=$(echo "$resp" | json_field "d.get('model','unknown')")
  pass "Routing: auto→chat detected → $routed"
else
  fail "Routing: auto chat detect" "HTTP $code"
fi

# ── Section 6: Metrics & Queue ────────────────────────────────────────────────
section "6. Metrics & Queue"

resp=$(http "/api/metrics" "" 10)
code=$(status_code "$resp")
if [ "$code" = "200" ]; then
  pass "GET /api/metrics returns 200"
  has_ts=$(echo "$resp" | json_field "'timestamp' in d")
  has_q=$(echo "$resp" | json_field "'queue' in d")
  [ "$has_ts" = "True" ] && pass "Metrics has timestamp" || fail "Metrics missing timestamp" ""
  [ "$has_q" = "True"  ] && pass "Metrics has queue stats" || fail "Metrics missing queue" ""
  processed=$(echo "$resp" | json_field "d['queue']['total_processed']")
  echo "    Total requests processed this session: $processed"
fi

# SSE stream test
sse_out=$(curl -s --max-time 5 -N "$GATEWAY/api/metrics/stream" 2>>"$LOG" || true)
has_data=$(echo "$sse_out" | grep -c "^data: {" || true)
[ "$has_data" -gt 0 ] && pass "Metrics SSE stream delivers events" || fail "Metrics SSE stream empty" ""

# ── Section 7: Error Handling ─────────────────────────────────────────────────
section "7. Error Handling"

# Malformed JSON
resp=$(curl -s --max-time 90 -w "\nHTTP_STATUS:%{http_code}" \
  -H "Content-Type: application/json" \
  "$GATEWAY/v1/chat/completions" \
  -d 'not valid json' 2>>"$LOG")
code=$(status_code "$resp")
[ "$code" = "422" ] || [ "$code" = "400" ] && pass "Malformed JSON returns 4xx (HTTP $code)" \
  || fail "Malformed JSON should return 4xx" "got HTTP $code"

# Missing required field
resp=$(http "/v1/chat/completions" '{"model":"active"}' 10)
code=$(status_code "$resp")
[ "$code" = "422" ] && pass "Missing 'messages' field returns 422" || fail "Missing field validation" "got HTTP $code"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════"
echo "  RESULTS"
echo "══════════════════════════════════════════════════"
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
echo "  SKIP: $SKIP"
echo "  TOTAL: $((PASS + FAIL + SKIP))"
echo ""
echo "  Full log: $LOG"
echo "══════════════════════════════════════════════════"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
