#!/usr/bin/env bash
#
# Tests for the agy backend of scripts/polish-gemini.sh
#
# A stand-in agy (tests/mocks/agy-mock.py) replaces the real Antigravity CLI
# through HUMANIZE_POLISH_AGY_BIN, and the loopback OpenRouter mock answers
# the fallback cases. No network access is needed and nothing real is called.
#
# Covers: agy as the default backend; how agy is run (stream-json output,
# model and effort, strict tool permission, deny rules, the deny-all hook,
# an empty temporary workspace that is removed afterwards, the prompt on
# standard input and never on the command line, credentials kept from agy);
# explicit errors for a missing agy, a signed-out agy, a used-up quota, rate
# limits, unknown models, timeouts and malformed output; rejection of any
# tool use; the OpenRouter fallback (off by default); backend selection;
# records; and interruption.
#

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/test-helpers.sh"

RUNNER="$PROJECT_ROOT/scripts/polish-gemini.sh"
AGY_MOCK="$SCRIPT_DIR/mocks/agy-mock.py"
OR_MOCK="$SCRIPT_DIR/mocks/openrouter-mock.py"

echo "========================================"
echo "Polish Gemini agy Backend Tests"
echo "========================================"

if ! command -v python3 >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
    skip "polish-gemini agy tests" "python3 and jq are required"
    print_test_summary "Polish Gemini agy Backend Test Summary"
    exit 0
fi

TEST_DIR="$(mktemp -d)"
MOCK_PID=""
cleanup() {
    if [[ -n "$MOCK_PID" ]]; then
        kill "$MOCK_PID" 2>/dev/null
        wait "$MOCK_PID" 2>/dev/null
    fi
    rm -rf "$TEST_DIR"
}
trap cleanup EXIT

PROJ="$TEST_DIR/project"
mkdir -p "$PROJ" "$TEST_DIR/cache" "$TEST_DIR/xdg" "$TEST_DIR/tmp" "$TEST_DIR/bin"
export CLAUDE_PROJECT_DIR="$PROJ"
export XDG_CACHE_HOME="$TEST_DIR/cache"
export XDG_CONFIG_HOME="$TEST_DIR/xdg"
unset HUMANIZE_CONFIG OPENROUTER_API_KEY HUMANIZE_POLISH_PYTHON HUMANIZE_POLISH_BLOCK_RATIO HUMANIZE_POLISH_DOC_RATIO
unset HUMANIZE_POLISH_BACKEND GEMINI_API_KEY GOOGLE_API_KEY GOOGLE_APPLICATION_CREDENTIALS AGY_ADC_AUTH
export HTTPS_PROXY="http://127.0.0.1:9" HTTP_PROXY="http://127.0.0.1:9"
export https_proxy="$HTTPS_PROXY" http_proxy="$HTTP_PROXY"
unset NO_PROXY no_proxy

# The stand-in agy, made executable in a private folder.
cp "$AGY_MOCK" "$TEST_DIR/bin/agy"
chmod +x "$TEST_DIR/bin/agy"
export HUMANIZE_POLISH_AGY_BIN="$TEST_DIR/bin/agy"
AGY_SCEN="$TEST_DIR/agy-scenario.json"
AGY_LOG="$TEST_DIR/agy-log.jsonl"
export AGY_MOCK_SCENARIO="$AGY_SCEN"
export AGY_MOCK_LOG="$AGY_LOG"

TEST_KEY="sk-or-test-key-$$-UNIQUEMARKER"

# OpenRouter mock for the fallback cases.
OR_SCEN="$TEST_DIR/or-scenario.json"
printf '{"id":"init","responses":[{}]}\n' > "$OR_SCEN"
python3 -I "$OR_MOCK" --port-file "$TEST_DIR/port" --scenario "$OR_SCEN" &
MOCK_PID=$!
for _ in $(seq 1 100); do
    [[ -s "$TEST_DIR/port" ]] && break
    sleep 0.1
done
if [[ ! -s "$TEST_DIR/port" ]]; then
    fail "OpenRouter mock starts" "a port file" "none"
    print_test_summary "Polish Gemini agy Backend Test Summary"
    exit 1
fi
export HUMANIZE_POLISH_BASE_URL="http://127.0.0.1:$(cat "$TEST_DIR/port")/api/v1"

SCEN_N=0
OR_LOG=""
OR_DEFAULT='[{}]'
# set_agy <json> [openrouter responses json]
set_agy() {
    SCEN_N=$((SCEN_N + 1))
    printf '%s\n' "$1" > "$AGY_SCEN"
    : > "$AGY_LOG"
    OR_LOG="$TEST_DIR/or-requests-$SCEN_N.jsonl"
    : > "$OR_LOG"
    printf '{"id":"s%d","log":"%s","responses":%s}\n' "$SCEN_N" "$OR_LOG" "${2:-$OR_DEFAULT}" > "$OR_SCEN"
}

agy_runs() { if [[ -s "$AGY_LOG" ]]; then wc -l < "$AGY_LOG" | tr -d ' '; else echo 0; fi; }
or_requests() { if [[ -s "$OR_LOG" ]]; then wc -l < "$OR_LOG" | tr -d ' '; else echo 0; fi; }
agy_json() { sed -n "1p" "$AGY_LOG" | jq -r "$@"; }

write_project_config() {
    mkdir -p "$PROJ/.humanize"
    printf '%s\n' "$1" > "$PROJ/.humanize/config.json"
}
clear_project_config() { rm -f "$PROJ/.humanize/config.json"; }

OUT="$TEST_DIR/out"
ERR="$TEST_DIR/err"
RC=0
run_polish() {
    TMPDIR="$TEST_DIR/tmp" "$RUNNER" "$@" > "$OUT" 2> "$ERR"
    RC=$?
}
run_polish_key() {
    OPENROUTER_API_KEY="$TEST_KEY" TMPDIR="$TEST_DIR/tmp" "$RUNNER" "$@" > "$OUT" 2> "$ERR"
    RC=$?
}

outcome_line() { tail -n 1 "$ERR"; }

assert_outcome() {
    local name="$1" outcome="$2" reason="$3" delivered="$4" rc="$5"
    local want="polish-gemini: outcome=$outcome reason=$reason delivered=$delivered"
    if [[ "$(outcome_line)" == "$want" && "$RC" == "$rc" ]]; then
        pass "$name"
    else
        fail "$name" "$want (exit $rc)" "$(outcome_line) (exit $RC)"
    fi
}

assert_same_file() {
    if cmp -s "$2" "$3"; then pass "$1"; else fail "$1" "identical to $(basename "$2")" "$(head -c 300 "$3")"; fi
}

assert_err_has() {
    if grep -Fq -- "$2" "$ERR"; then pass "$1"; else fail "$1" "$2" "$(cat "$ERR")"; fi
}

DOC="$TEST_DIR/doc.md"
cat > "$DOC" << 'EOF'
# Retry Policy

The orchestrator leverages an idempotent retry envelope so transient upstream faults get absorbed, capped at 2 attempts per request. Run `humanize monitor rlcr` to watch it.
EOF

echo ""
echo "--- Default backend and how agy is run ---"

set_agy '{"replace":[["leverages","uses"]]}'
run_polish --input "$DOC"
assert_outcome "agy is the default backend and its reply is delivered" polished ok yes 0
if grep -q "The orchestrator uses an idempotent" "$OUT"; then pass "the polished text comes from agy"; else fail "polished text" "uses" "$(cat "$OUT")"; fi
if [[ "$(agy_runs)" == "1" && "$(or_requests)" == "0" ]]; then pass "one agy run and no OpenRouter request"; else fail "backend calls" "1 agy, 0 OpenRouter" "$(agy_runs) agy, $(or_requests) OpenRouter"; fi
assert_err_has "the run names the model and effort" "running agy (model=gemini-4-neon effort=medium)"

ARGV="$(agy_json '.argv | join(" ")')"
SETTINGS="$(agy_json '.argv as $a | ($a | index("--settings")) as $i | $a[$i + 1]')"
if [[ "$(agy_json '.argv as $a | ($a | index("--model")) as $i | $a[$i + 1]')" == "gemini-4-neon" && \
      "$(agy_json '.argv as $a | ($a | index("--effort")) as $i | $a[$i + 1]')" == "medium" ]]; then
    pass "default model gemini-4-neon with effort medium"
else
    fail "default agy model and effort" "--model gemini-4-neon --effort medium" "$ARGV"
fi
for want in "--output-format stream-json" "--disable-slash-commands" "--sandbox" "--print-timeout 900s" "--log-file"; do
    if [[ " $ARGV " == *" $want"* ]]; then pass "agy runs with $want"; else fail "agy argv has $want" "$want" "$ARGV"; fi
done
for bad in --dangerously-skip-permissions -p --print --prompt -i --mode --add-dir --continue --conversation; do
    if [[ "$(agy_json --arg f "$bad" '.argv | index($f)')" == "null" ]]; then pass "agy runs without $bad"; else fail "agy argv lacks $bad" "absent" "$ARGV"; fi
done
if jq -e '.toolPermission == "strict" and .agentMode == "" and .allowNonWorkspaceAccess == false
          and .trustedWorkspaces == [] and .useG1Credits == false and .permissions.allow == []
          and (.permissions.deny | sort) == (["command(*)","mcp(*)","read_file(*)","read_url(*)","write_file(*)"] | sort)' \
       <<< "$SETTINGS" >/dev/null; then
    pass "session settings lock every tool down and keep AI credits off"
else
    fail "agy session settings" "strict, deny rules, no credits" "$SETTINGS"
fi
if [[ "$(agy_json '.files | join(",")')" == ".agents/hooks.json" ]] && \
   [[ "$(agy_json '.cwd')" == */tmp/humanize-polish-agy-*/workspace ]]; then
    pass "agy runs in an empty temporary workspace holding only the hook file"
else
    fail "agy workspace" "only .agents/hooks.json under TMPDIR" "$(agy_json '.cwd') $(agy_json '.files | join(",")')"
fi
if agy_json '.hooks' | jq -e '.["humanize-polish-no-tools"].PreToolUse[0].matcher == "*"' >/dev/null && \
   [[ "$(agy_json '.hooks' | jq -r '.["humanize-polish-no-tools"].PreToolUse[0].hooks[0].command' | sh)" == '{"decision":"deny","reason":"Polish runs allow no tools."}' ]]; then
    pass "the workspace hook denies every tool call"
else
    fail "deny-all hook" "matcher * printing a deny decision" "$(agy_json '.hooks')"
fi
if [[ -z "$(ls "$TEST_DIR/tmp" | grep humanize-polish-agy-)" ]]; then pass "the temporary workspace is removed after the run"; else fail "workspace cleanup" "removed" "$(ls "$TEST_DIR/tmp")"; fi
STDIN_TEXT="$(agy_json '.stdin')"
if grep -Fq "Do not call any tool" <<< "$STDIN_TEXT" && grep -Fq "You are a copy editor." <<< "$STDIN_TEXT" && \
   grep -Fq "transient upstream faults" <<< "$STDIN_TEXT"; then
    pass "the contract and the document go to agy on standard input"
else
    fail "agy stdin" "preface, contract and document" "$(head -c 300 <<< "$STDIN_TEXT")"
fi
if [[ "$ARGV" != *"transient upstream"* && "$ARGV" != *"copy editor"* ]]; then pass "the document is never on the agy command line"; else fail "argv privacy" "no document text" "$ARGV"; fi

set_agy '{}'
OPENROUTER_API_KEY="$TEST_KEY" GEMINI_API_KEY="g-test" GOOGLE_API_KEY="g-test" GOOGLE_APPLICATION_CREDENTIALS="/x" AGY_ADC_AUTH=1 \
    TMPDIR="$TEST_DIR/tmp" "$RUNNER" --input "$DOC" > "$OUT" 2> "$ERR"
RC=$?
if [[ "$(agy_json '[.env[]] | any')" == "false" ]]; then
    pass "agy never sees the OpenRouter key or pay-per-call Google credentials"
else
    fail "agy environment" "no credential variables" "$(agy_json '.env')"
fi
assert_outcome "an identical reply is unchanged" unchanged identical yes 0

echo ""
echo "--- Model, effort and backend selection ---"

write_project_config '{"gemini_polish_agy_model": "gemini-4-carbon", "gemini_polish_reasoning_effort": "high"}'
set_agy '{}'
run_polish --input "$DOC"
if [[ "$(agy_json '.argv as $a | ($a | index("--model")) as $i | $a[$i + 1]')" == "gemini-4-carbon" && \
      "$(agy_json '.argv as $a | ($a | index("--effort")) as $i | $a[$i + 1]')" == "high" ]]; then
    pass "config sets the agy model and the effort"
else
    fail "config agy model" "gemini-4-carbon high" "$(agy_json '.argv | join(" ")')"
fi
set_agy '{}'
run_polish --input "$DOC" --model gemini-3.8-flash --effort low
if [[ "$(agy_json '.argv as $a | ($a | index("--model")) as $i | $a[$i + 1]')" == "gemini-3.8-flash" && \
      "$(agy_json '.argv as $a | ($a | index("--effort")) as $i | $a[$i + 1]')" == "low" ]]; then
    pass "--model and --effort override the config for agy"
else
    fail "CLI agy model" "gemini-3.8-flash low" "$(agy_json '.argv | join(" ")')"
fi
clear_project_config

set_agy '{}'
run_polish --input "$DOC" --model 'gemini;rm'
assert_outcome "an agy model name with shell characters is a usage error" failed usage_error no 1
if [[ "$(agy_runs)" == "0" ]]; then pass "agy is not run after a usage error"; else fail "no agy run" "0" "$(agy_runs)"; fi

set_agy '{}'
run_polish_key --input "$DOC" --backend openrouter
assert_outcome "--backend openrouter uses OpenRouter" unchanged identical yes 0
if [[ "$(agy_runs)" == "0" && "$(or_requests)" == "1" && \
      "$(sed -n 1p "$OR_LOG" | jq -r '.body.model')" == "google/gemini-4-neon" && \
      "$(sed -n 1p "$OR_LOG" | jq -r '.body.reasoning.effort')" == "medium" ]]; then
    pass "OpenRouter defaults to google/gemini-4-neon at medium, and agy is not run"
else
    fail "openrouter backend" "0 agy, 1 request, neon medium" "$(agy_runs) agy, $(or_requests) requests, $(sed -n 1p "$OR_LOG" | jq -c '{m:.body.model,e:.body.reasoning.effort}')"
fi

set_agy '{}'
HUMANIZE_POLISH_BACKEND=openrouter OPENROUTER_API_KEY="$TEST_KEY" TMPDIR="$TEST_DIR/tmp" "$RUNNER" --input "$DOC" > "$OUT" 2> "$ERR"
RC=$?
if [[ "$(agy_runs)" == "0" && "$(or_requests)" == "1" ]]; then pass "HUMANIZE_POLISH_BACKEND selects OpenRouter"; else fail "env backend" "OpenRouter" "$(agy_runs) agy"; fi

write_project_config '{"gemini_polish_backend": "openrouter"}'
set_agy '{}'
run_polish_key --input "$DOC"
if [[ "$(agy_runs)" == "0" && "$(or_requests)" == "1" ]]; then pass "gemini_polish_backend selects OpenRouter"; else fail "config backend" "OpenRouter" "$(agy_runs) agy"; fi
set_agy '{}'
run_polish_key --input "$DOC" --backend agy
if [[ "$(agy_runs)" == "1" && "$(or_requests)" == "0" ]]; then pass "--backend agy overrides the config"; else fail "CLI backend wins" "agy" "$(agy_runs) agy, $(or_requests) requests"; fi
write_project_config '{"gemini_polish_backend": "gemini"}'
set_agy '{}'
run_polish --input "$DOC"
if [[ "$(agy_runs)" == "1" ]] && grep -Fq "ignoring invalid gemini_polish_backend in config: gemini" "$ERR"; then
    pass "an invalid backend in config is reported and agy is used"
else
    fail "invalid config backend" "diag and agy" "$(cat "$ERR")"
fi
clear_project_config

set_agy '{}'
run_polish --input "$DOC" --backend gemini
assert_outcome "an unknown --backend is a usage error" failed usage_error no 1

write_project_config '{"gemini_polish_enabled": false}'
set_agy '{}'
run_polish --input "$DOC" --auto
assert_outcome "--auto with polishing disabled skips without running agy" skipped disabled yes 0
if [[ "$(agy_runs)" == "0" ]]; then pass "agy is not run when disabled"; else fail "disabled" "0 runs" "$(agy_runs)"; fi
clear_project_config

echo ""
echo "--- Explicit errors, original kept ---"

HUMANIZE_POLISH_AGY_BIN="$TEST_DIR/bin/no-such-agy" TMPDIR="$TEST_DIR/tmp" "$RUNNER" --input "$DOC" > "$OUT" 2> "$ERR"
RC=$?
assert_outcome "a missing agy is skipped with agy_not_found" skipped agy_not_found yes 0
assert_same_file "a missing agy delivers the original" "$DOC" "$OUT"
assert_err_has "a missing configured agy is named" "gemini_polish_agy_bin is not an executable file"

EMPTY_PATH_DIR="$TEST_DIR/emptypath"
mkdir -p "$EMPTY_PATH_DIR"
for tool in bash env python3 jq dirname mktemp cat rm chmod mkfifo stat sed tr head tail cmp wc ls mv cp date grep sleep kill uname git; do
    p="$(command -v "$tool" 2>/dev/null)" && ln -sf "$p" "$EMPTY_PATH_DIR/$tool"
done
HOME="$TEST_DIR/nohome" PATH="$EMPTY_PATH_DIR" TMPDIR="$TEST_DIR/tmp" HUMANIZE_POLISH_AGY_BIN="" \
    "$RUNNER" --input "$DOC" > "$OUT" 2> "$ERR"
RC=$?
assert_outcome "no agy on PATH or in ~/.local/bin is skipped with agy_not_found" skipped agy_not_found yes 0
assert_err_has "the missing agy message says how to fix it" "the agy command (Antigravity CLI) was not found"

check_error() {
    local name="$1" scenario="$2" reason="$3" hint="$4"
    set_agy "$scenario"
    run_polish_key --input "$DOC"
    assert_outcome "$name" failed "$reason" yes 0
    assert_same_file "$name: the original is delivered" "$DOC" "$OUT"
    if [[ -n "$hint" ]]; then assert_err_has "$name: the error says what to do" "$hint"; fi
    if [[ "$(or_requests)" == "0" ]] && grep -Fq "not falling back to OpenRouter (gemini_polish_fallback_to_openrouter is false)" "$ERR"; then
        pass "$name: no OpenRouter request while the fallback is off"
    else
        fail "$name: no fallback" "0 requests and the fallback notice" "$(or_requests) requests; $(cat "$ERR")"
    fi
}

check_error "a signed-out agy fails with auth" \
    '{"status":"ERROR","error":"authentication failed or timed out","exit":1,"stderr":"Error: authentication required. Run agy to log in, then retry.","no_init":true}' \
    auth "agy is not signed in: run agy once in a terminal and sign in"
check_error "a used-up quota fails with quota_exhausted" \
    '{"status":"ERROR","error":"RESOURCE_EXHAUSTED: weekly quota exceeded for this model","exit":3}' \
    quota_exhausted "the Gemini subscription quota is used up"
check_error "a rate limit fails with rate_limited" \
    '{"status":"ERROR","error":"429 Too Many Requests","exit":3}' rate_limited ""
check_error "an unknown model fails with bad_model" \
    '{"status":"ERROR","error":"invalid model selection: model gemini-9 is not recognized as a known model","exit":1,"no_init":true}' \
    bad_model "run agy models to list the models agy offers"
check_error "an agy print timeout fails with timeout" \
    '{"finished_reason":"print_timeout","exit":0}' timeout "did not finish within"
check_error "another agy error fails with agy_error" \
    '{"status":"ERROR","error":"cascade crashed","exit":3}' agy_error "cascade crashed"
check_error "a crash without a result event is reported" \
    '{"raw_stdout":"","exit":2,"stderr":"panic: something broke"}' agy_error "panic: something broke"
check_error "output without a result event fails with bad_json" \
    '{"raw_stdout":"not json at all\n","exit":0}' bad_json "no result event"
check_error "an empty reply fails with empty_response" \
    '{"mode":"content","content":"   "}' empty_response "agy returned no text"
check_error "a run that did not confirm strict mode fails with agy_lockdown" \
    '{"permission_mode":"always-proceed"}' agy_lockdown "did not confirm the strict tool permission mode"
check_error "a run without an init event fails with agy_lockdown" \
    '{"no_init":true}' agy_lockdown "did not confirm the strict tool permission mode"

set_agy "{\"sleep\":30,\"pid_file\":\"$TEST_DIR/agy.pid\"}"
START=$(date +%s)
run_polish_key --input "$DOC" --timeout 1
ELAPSED=$(( $(date +%s) - START ))
assert_outcome "a hung agy is stopped at the deadline" failed timeout yes 0
if [[ "$ELAPSED" -lt 25 ]]; then pass "the deadline (timeout plus grace) is enforced (${ELAPSED}s)"; else fail "deadline" "under 25s" "${ELAPSED}s"; fi
if [[ -s "$TEST_DIR/agy.pid" ]] && ! kill -0 "$(cat "$TEST_DIR/agy.pid")" 2>/dev/null; then
    pass "the hung agy process is killed"
else
    fail "hung agy killed" "process gone" "pid $(cat "$TEST_DIR/agy.pid" 2>/dev/null) still running"
fi
if [[ -z "$(ls "$TEST_DIR/tmp" | grep humanize-polish-agy-)" ]]; then pass "the workspace is removed after a timeout"; else fail "workspace cleanup on timeout" "removed" "$(ls "$TEST_DIR/tmp")"; fi

echo ""
echo "--- Tool use is never accepted ---"

set_agy '{"tool_steps":["search_web"],"response":"I searched the web."}'
run_polish_key --input "$DOC"
assert_outcome "a run with a tool step is rejected" rejected tool_call yes 0
assert_err_has "the rejected tool is named" "agy tried to use tools (search_web)"
assert_same_file "a tool step delivers the original" "$DOC" "$OUT"
set_agy '{"denied_actions":["write_file"]}'
run_polish_key --input "$DOC"
assert_outcome "a run with a denied action is rejected" rejected tool_call yes 0
assert_err_has "the denied action is named" "write_file"

echo ""
echo "--- The guard still checks agy replies ---"

set_agy '{"replace":[["`humanize monitor rlcr`","`humanize monitor`"]]}'
run_polish --input "$DOC"
assert_outcome "a changed code span is rejected" rejected protected_token yes 0
set_agy '{"mode":"content","content":"Sure! Here is the text:\n{BEGIN}\n{DOC}\n{END}\n"}'
run_polish --input "$DOC"
assert_outcome "text outside the output block is rejected" rejected envelope yes 0

echo ""
echo "--- OpenRouter fallback ---"

set_agy '{"status":"ERROR","error":"authentication failed or timed out","exit":1,"no_init":true}' '[{"replace":[["leverages","uses"]]}]'
write_project_config '{"gemini_polish_fallback_to_openrouter": true}'
run_polish_key --input "$DOC"
assert_outcome "with the fallback on, a failed agy run falls back to OpenRouter" polished ok yes 0
assert_err_has "the fallback is announced" "agy failed (reason=auth); falling back to OpenRouter"
if [[ "$(or_requests)" == "1" ]]; then pass "one OpenRouter request after the agy failure"; else fail "fallback request" "1" "$(or_requests)"; fi
META="$(ls -t "$PROJ"/.humanize/skill/*/metadata.md | head -1)"
if grep -qx "backend: openrouter" "$META" && grep -qx "fallback_from: agy:auth" "$META" && \
   grep -qx "model: google/gemini-4-neon" "$META"; then
    pass "the record names OpenRouter and the agy failure it replaced"
else
    fail "fallback record" "backend openrouter, fallback_from agy:auth" "$(cat "$META")"
fi

set_agy '{"status":"ERROR","error":"quota exceeded","exit":3}'
run_polish --input "$DOC"
assert_outcome "with the fallback on but no key, the agy reason is reported" failed quota_exhausted yes 0
assert_err_has "the missing key is explained" "gemini_polish_fallback_to_openrouter is true, but no OpenRouter API key is set"

set_agy '{"tool_steps":["run_command"]}'
run_polish_key --input "$DOC"
assert_outcome "a rejected agy reply never falls back" rejected tool_call yes 0
if [[ "$(or_requests)" == "0" ]]; then pass "no OpenRouter request after a rejection"; else fail "no fallback after rejection" "0" "$(or_requests)"; fi

HUMANIZE_POLISH_AGY_BIN="$TEST_DIR/bin/no-such-agy" OPENROUTER_API_KEY="$TEST_KEY" TMPDIR="$TEST_DIR/tmp" \
    "$RUNNER" --input "$DOC" > "$OUT" 2> "$ERR"
RC=$?
if [[ "$(or_requests)" == "1" ]] && [[ "$(outcome_line)" == *"delivered=yes" ]]; then
    pass "with the fallback on, a missing agy falls back to OpenRouter"
else
    fail "fallback on missing agy" "1 request" "$(or_requests); $(outcome_line)"
fi
write_project_config '{"gemini_polish_fallback_to_openrouter": "yes"}'
set_agy '{"status":"ERROR","error":"quota exceeded","exit":3}'
run_polish_key --input "$DOC"
if [[ "$(or_requests)" == "0" ]] && grep -Fq "ignoring invalid gemini_polish_fallback_to_openrouter in config: yes" "$ERR"; then
    pass "an invalid fallback value is reported and treated as off"
else
    fail "invalid fallback value" "diag, no request" "$(or_requests); $(cat "$ERR")"
fi
clear_project_config

echo ""
echo "--- Records ---"

rm -rf "$PROJ/.humanize/skill"
set_agy '{"replace":[["leverages","uses"]]}'
run_polish --input "$DOC"
META="$(ls "$PROJ"/.humanize/skill/*/metadata.md 2>/dev/null | head -1)"
for kv in "backend: agy" "model: gemini-4-neon" "model_label: Mock gemini-4-neon (Medium)" "effort_used: medium" \
          "prompt_tokens: 11000" "completion_tokens: 900" "reasoning_tokens: 700" "cost: subscription" "outcome: polished"; do
    if [[ -n "$META" ]] && grep -qx -- "$kv" "$META"; then pass "metadata has '$kv'"; else fail "metadata '$kv'" "$kv" "$(cat "$META" 2>/dev/null)"; fi
done
SKILL_DIR="$(dirname "$META")"
if grep -qx -- "- Backend: agy" "$SKILL_DIR/input.md" && grep -qx -- "- Model: gemini-4-neon" "$SKILL_DIR/input.md"; then
    pass "input.md names the agy backend and model"
else
    fail "input.md backend" "agy" "$(cat "$SKILL_DIR/input.md")"
fi
CACHE_DIR="$(ls -d "$TEST_DIR"/cache/humanize/*/skill-* | head -1)"
if [[ -s "$CACHE_DIR/agy-run.log" && -s "$CACHE_DIR/gemini-run.cmd" && -s "$CACHE_DIR/gemini-run.out" ]] && \
   grep -Fq -- "--settings" "$CACHE_DIR/gemini-run.cmd" && grep -Fq '"permission_mode": "strict"' "$CACHE_DIR/gemini-run.out"; then
    pass "the cache keeps the agy command, its events and its log"
else
    fail "agy cache files" "agy-run.log, gemini-run.cmd, gemini-run.out" "$(ls "$CACHE_DIR")"
fi

echo ""
echo "--- Interruption ---"

set_agy "{\"sleep\":30,\"pid_file\":\"$TEST_DIR/agy-int.pid\"}"
rm -f "$TEST_DIR/agy-int.pid"
cp "$DOC" "$TEST_DIR/inplace.md"
TMPDIR="$TEST_DIR/tmp" "$RUNNER" --input "$TEST_DIR/inplace.md" --output "$TEST_DIR/inplace.md" > "$OUT" 2> "$ERR" &
RUN_PID=$!
for _ in $(seq 1 100); do
    [[ -s "$TEST_DIR/agy-int.pid" ]] && break
    sleep 0.1
done
kill -TERM "$RUN_PID" 2>/dev/null
wait "$RUN_PID"
RC=$?
assert_outcome "SIGTERM while agy runs ends the run with nothing delivered" failed interrupted no 143
assert_same_file "the output file is untouched after the interruption" "$DOC" "$TEST_DIR/inplace.md"
sleep 0.5
if [[ -s "$TEST_DIR/agy-int.pid" ]] && ! kill -0 "$(cat "$TEST_DIR/agy-int.pid")" 2>/dev/null; then
    pass "the interrupted agy process is killed"
else
    fail "interrupted agy killed" "process gone" "pid $(cat "$TEST_DIR/agy-int.pid" 2>/dev/null)"
fi
if [[ -z "$(ls "$TEST_DIR/tmp" | grep humanize-polish-agy-)" ]]; then pass "the workspace is removed after an interruption"; else fail "workspace cleanup on interrupt" "removed" "$(ls "$TEST_DIR/tmp")"; fi

if bash -n "$0"; then pass "bash -n test-polish-gemini-agy.sh"; else fail "bash -n" "ok" "syntax error"; fi

print_test_summary "Polish Gemini agy Backend Test Summary"
