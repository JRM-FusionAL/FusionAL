#!/usr/bin/env bash
# Smoke test for a running commander-mcp-server instance.
# Run this after `docker compose up -d commander` to confirm the deploy
# is actually healthy and every tool category works — the same checks
# used to verify the build before it shipped.
#
# Usage: ./smoke-test.sh [base_url]
#   default base_url: http://localhost:8108

set -uo pipefail

BASE="${1:-http://localhost:8108}"
MCP="$BASE/mcp"
H1="Content-Type: application/json"
H2="Accept: application/json, text/event-stream"
PASS=0
FAIL=0

pass() { echo "  PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

call() {
  # $1 = id, $2 = tool name, $3 = json args
  curl -s "$MCP" -H "$H1" -H "$H2" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":$1,\"method\":\"tools/call\",\"params\":{\"name\":\"$2\",\"arguments\":$3}}"
}

echo "== commander-mcp-server smoke test against $BASE =="

echo "[1] Health check"
HEALTH=$(curl -s --max-time 5 "$BASE/health")
if echo "$HEALTH" | grep -q '"status":"ok"'; then pass "server is up ($HEALTH)"; else fail "health check ($HEALTH)"; fi

echo "[2] MCP initialize handshake"
INIT=$(curl -s --max-time 5 "$MCP" -H "$H1" -H "$H2" \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke-test","version":"1.0"}}}')
if echo "$INIT" | grep -q '"serverInfo"'; then pass "initialize responded"; else fail "initialize ($INIT)"; fi

echo "[3] tools/list returns all 21 tools"
COUNT=$(curl -s --max-time 5 "$MCP" -H "$H1" -H "$H2" \
  -d '{"jsonrpc":"2.0","id":0,"method":"tools/list","params":{}}' \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin)['result']['tools']))" 2>/dev/null)
if [ "$COUNT" = "21" ]; then pass "21 tools registered"; else fail "expected 21 tools, got '$COUNT'"; fi

echo "[4] fs_write_file -> fs_read_file round trip"
WRITE=$(call 1 fs_write_file '{"path":"smoke-test/probe.txt","content":"probe line one\nprobe line two\n"}')
READ=$(call 2 fs_read_file '{"path":"smoke-test/probe.txt"}')
if echo "$READ" | grep -q "probe line one"; then pass "write/read round trip"; else fail "write/read ($WRITE / $READ)"; fi

echo "[5] fs_edit_block surgical replace"
EDIT=$(call 3 fs_edit_block '{"path":"smoke-test/probe.txt","old_str":"probe line two","new_str":"EDITED line two"}')
VERIFY=$(call 4 fs_read_file '{"path":"smoke-test/probe.txt"}')
if echo "$VERIFY" | grep -q "EDITED line two"; then pass "edit_block applied"; else fail "edit_block ($EDIT / $VERIFY)"; fi

echo "[6] Path escape is denied"
ESCAPE=$(call 5 fs_read_file '{"path":"/etc/passwd"}')
if echo "$ESCAPE" | grep -q "Access denied"; then pass "path escape correctly denied"; else fail "path escape NOT denied: $ESCAPE"; fi

echo "[7] Dangerous command is blocked"
DANGER=$(call 6 proc_start '{"command":"rm -rf /","timeout_ms":300}')
if echo "$DANGER" | grep -q "blocked by security policy"; then pass "rm -rf / correctly blocked"; else fail "dangerous command NOT blocked: $DANGER"; fi

echo "[8] proc_start / interactive session survives its initial wait"
START=$(call 7 proc_start '{"command":"cat","timeout_ms":300}')
PID=$(echo "$START" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['structuredContent']['pid'])" 2>/dev/null)
STATUS=$(echo "$START" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['structuredContent']['status'])" 2>/dev/null)
if [ "$STATUS" = "running" ] && [ -n "$PID" ]; then pass "session $PID still running after initial wait"; else fail "session died early: $START"; fi

echo "[9] proc_write_input -> proc_read_output echo"
if [ -n "${PID:-}" ]; then
  call 8 proc_write_input "{\"pid\":$PID,\"input\":\"echo-check\"}" > /dev/null
  sleep 0.3
  ECHO=$(call 9 proc_read_output "{\"pid\":$PID}")
  if echo "$ECHO" | grep -q "echo-check"; then pass "stdin/stdout round trip"; else fail "no echo back: $ECHO"; fi
  call 10 proc_terminate "{\"pid\":$PID,\"force\":true}" > /dev/null
else
  fail "skipped (no pid from step 8)"
fi

echo
echo "== $PASS passed, $FAIL failed =="
[ "$FAIL" -eq 0 ]
