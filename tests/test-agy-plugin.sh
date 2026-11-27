#!/usr/bin/env bash
#
# Tests for the Humanize agy (Antigravity CLI) plugin:
# - hooks/agy-hook-adapter.py payload and reply translation (stub hooks)
# - the adapter with the real validators and stop hook
# - the read-only Claude reviewer (rlcr_verifier / rlcr_reviewer = claude)
# - finalize prompts on agy (no Gemini polish step)
# - scripts/install-agy-plugin.sh layout
# - the unattended-run checks (HUMANIZE_AGY_UNATTENDED)
# - scripts/agy-rlcr-run.sh, the unattended driver, against a mock agy
#

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/test-helpers.sh"

ADAPTER="$REPO_ROOT/hooks/agy-hook-adapter.py"
WRAPPER="$REPO_ROOT/hooks/agy-hook.sh"

echo "=========================================="
echo "agy Plugin Tests"
echo "=========================================="
echo ""

setup_test_dir
export XDG_CACHE_HOME="$TEST_DIR/.cache"
export XDG_CONFIG_HOME="$TEST_DIR/.config"
mkdir -p "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME"
unset HUMANIZE_RLCR_VERIFIER HUMANIZE_RLCR_REVIEWER HUMANIZE_CLAUDE_REVIEW_MODEL HUMANIZE_AGY_CONTINUATION_LIMIT CLAUDE_PROJECT_DIR HUMANIZE_AGY_UNATTENDED

assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        pass "$name"
    else
        fail "$name" "$expected" "$actual"
    fi
}

assert_contains() {
    local name="$1" needle="$2" haystack="$3"
    if [[ "$haystack" == *"$needle"* ]]; then
        pass "$name"
    else
        fail "$name" "contains: $needle" "$(printf '%s' "$haystack" | head -c 600)"
    fi
}

assert_not_contains() {
    local name="$1" needle="$2" haystack="$3"
    if [[ "$haystack" != *"$needle"* ]]; then
        pass "$name"
    else
        fail "$name" "does not contain: $needle" "$(printf '%s' "$haystack" | head -c 600)"
    fi
}

# agy payload builder: payload EVENT CWD [extra-json-object]
payload() {
    local event="$1" cwd="$2" extra="${3:-}"
    [[ -n "$extra" ]] || extra='{}'
    jq -nc --arg event "$event" --arg cwd "$cwd" --argjson extra "$extra" '{
        conversationId: "conv-1",
        transcriptPath: "/tmp/agy-transcript.jsonl",
        artifactDirectoryPath: "/tmp/agy-artifacts",
        workspacePaths: [$cwd],
        cwd: $cwd,
        modelName: "gemini-test",
        lastUserInput: "start the loop",
        hookEventName: $event
    } + $extra'
}

tool_payload() {
    local cwd="$1" name="$2" args="$3"
    payload "PreToolUse" "$cwd" "$(jq -nc --arg name "$name" --argjson args "$args" '{toolCall: {id: "t1", name: $name, args: $args}, stepIdx: 3}')"
}

# ========================================
# Part A: translation with stub hooks
# ========================================

echo "--- Part A: payload translation (stub hooks) ---"

STUB_PLUGIN="$TEST_DIR/stub-plugin"
STUB_LOG="$TEST_DIR/stub-log"
mkdir -p "$STUB_PLUGIN/hooks" "$STUB_LOG"
cp "$ADAPTER" "$WRAPPER" "$STUB_PLUGIN/hooks/"

# Each stub appends its stdin and key env vars as one JSON line, then replies
# with STUB_<NAME>_EXIT / STUB_<NAME>_STDOUT / STUB_<NAME>_STDERR.
for name in loop-write-validator loop-edit-validator loop-read-validator loop-bash-validator loop-post-bash-hook loop-codex-stop-hook; do
    var="$(printf '%s' "$name" | tr 'a-z-' 'A-Z_')"
    cat > "$STUB_PLUGIN/hooks/$name.sh" <<EOF
#!/usr/bin/env bash
input="\$(cat)"
jq -nc --argjson input "\$input" --arg pd "\${CLAUDE_PROJECT_DIR:-}" --arg host "\${HUMANIZE_HOST:-}" --arg pwd "\$(pwd -P)" \
    '{input: \$input, project_dir: \$pd, host: \$host, pwd: \$pwd}' >> "$STUB_LOG/$name.jsonl"
[[ -n "\${STUB_${var}_STDERR:-}" ]] && printf '%s\n' "\$STUB_${var}_STDERR" >&2
[[ -n "\${STUB_${var}_STDOUT:-}" ]] && printf '%s\n' "\$STUB_${var}_STDOUT"
exit "\${STUB_${var}_EXIT:-0}"
EOF
    chmod +x "$STUB_PLUGIN/hooks/$name.sh"
done
STUB_ADAPTER="$STUB_PLUGIN/hooks/agy-hook-adapter.py"

PROJ_A="$TEST_DIR/proj-a"
init_test_git_repo "$PROJ_A"
PROJ_A_REAL="$(cd "$PROJ_A" && pwd -P)"

run_stub() {
    # run_stub EVENT PAYLOAD -> sets OUT and RC
    OUT="$(printf '%s' "$2" | python3 "$STUB_ADAPTER" "$1" 2>"$TEST_DIR/stub-stderr")"
    RC=$?
}

# JSON arguments are passed at top level: bash 3.2 brace-expands "{a,b}"
# when it appears inside a double-quoted command substitution.
run_stub_pre() {
    local payload_json
    payload_json="$(tool_payload "$2" "$1" "$3")"
    run_stub pre-tool "$payload_json"
}

stub_calls() {
    local name="$1"
    if [[ -f "$STUB_LOG/$name.jsonl" ]]; then
        wc -l < "$STUB_LOG/$name.jsonl" | tr -d ' '
    else
        echo 0
    fi
}

last_stub() {
    tail -n 1 "$STUB_LOG/$1.jsonl"
}

reset_stubs() {
    rm -f "$STUB_LOG"/*.jsonl
    unset STUB_LOOP_WRITE_VALIDATOR_EXIT STUB_LOOP_WRITE_VALIDATOR_STDERR STUB_LOOP_WRITE_VALIDATOR_STDOUT
    unset STUB_LOOP_EDIT_VALIDATOR_EXIT STUB_LOOP_EDIT_VALIDATOR_STDERR STUB_LOOP_EDIT_VALIDATOR_STDOUT
    unset STUB_LOOP_READ_VALIDATOR_EXIT STUB_LOOP_BASH_VALIDATOR_EXIT STUB_LOOP_BASH_VALIDATOR_STDERR
    unset STUB_LOOP_CODEX_STOP_HOOK_EXIT STUB_LOOP_CODEX_STOP_HOOK_STDOUT STUB_LOOP_CODEX_STOP_HOOK_STDERR
}

# A1: no active loop -> silent, no hook runs
reset_stubs
run_stub_pre write_file "$PROJ_A" '{"Path":"/x/a.txt","Content":"hi"}'
assert_eq "A1 no loop: exit 0" "0" "$RC"
assert_eq "A1 no loop: no reply" "" "$OUT"
assert_eq "A1 no loop: validator not run" "0" "$(stub_calls loop-write-validator)"

# A finished loop (no active state file) also stays silent.
mkdir -p "$PROJ_A/.humanize/rlcr/2026-01-01_00-00-00"
echo "---" > "$PROJ_A/.humanize/rlcr/2026-01-01_00-00-00/complete-state.md"
run_stub_pre write_file "$PROJ_A" '{"Path":"/x/a.txt","Content":"hi"}'
assert_eq "A1 finished loop: validator not run" "0" "$(stub_calls loop-write-validator)"

# Not a git repository (for example the polish runner's empty workspace) -> silent.
mkdir -p "$TEST_DIR/not-a-repo"
run_stub stop "$(payload Stop "$TEST_DIR/not-a-repo" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL"}')"
assert_eq "A1 non-repo workspace: no reply" "" "$OUT"

# Activate the loop for the rest of Part A.
mkdir -p "$PROJ_A/.humanize/rlcr/2026-02-02_00-00-00"
echo "---" > "$PROJ_A/.humanize/rlcr/2026-02-02_00-00-00/state.md"

# A2: write_file -> Write
reset_stubs
run_stub_pre write_file "$PROJ_A" "{\"Path\":\"$PROJ_A/a.txt\",\"Content\":\"hello\",\"Overwrite\":true}"
assert_eq "A2 write_file allowed: no reply" "" "$OUT"
assert_eq "A2 write validator ran once" "1" "$(stub_calls loop-write-validator)"
CALL="$(last_stub loop-write-validator)"
assert_eq "A2 tool_name Write" "Write" "$(jq -r '.input.tool_name' <<<"$CALL")"
assert_eq "A2 file_path" "$PROJ_A/a.txt" "$(jq -r '.input.tool_input.file_path' <<<"$CALL")"
assert_eq "A2 content" "hello" "$(jq -r '.input.tool_input.content' <<<"$CALL")"
assert_eq "A2 session_id from conversationId" "conv-1" "$(jq -r '.input.session_id' <<<"$CALL")"
assert_eq "A2 transcript_path" "/tmp/agy-transcript.jsonl" "$(jq -r '.input.transcript_path' <<<"$CALL")"
assert_eq "A2 hook_event_name" "PreToolUse" "$(jq -r '.input.hook_event_name' <<<"$CALL")"
assert_eq "A2 CLAUDE_PROJECT_DIR is the repo" "$PROJ_A_REAL" "$(jq -r '.project_dir' <<<"$CALL")"
assert_eq "A2 hook runs in the repo" "$PROJ_A_REAL" "$(jq -r '.pwd' <<<"$CALL")"
assert_eq "A2 HUMANIZE_HOST=agy" "agy" "$(jq -r '.host' <<<"$CALL")"

# Older tool names and argument names map the same way.
reset_stubs
run_stub_pre write_to_file "$PROJ_A" "{\"TargetFile\":\"$PROJ_A/b.txt\",\"CodeContent\":\"x\"}"
CALL="$(last_stub loop-write-validator)"
assert_eq "A2 write_to_file TargetFile" "$PROJ_A/b.txt" "$(jq -r '.input.tool_input.file_path' <<<"$CALL")"
assert_eq "A2 write_to_file CodeContent" "x" "$(jq -r '.input.tool_input.content' <<<"$CALL")"

# A3: validator exit 2 -> deny with its message
reset_stubs
export STUB_LOOP_WRITE_VALIDATOR_EXIT=2 STUB_LOOP_WRITE_VALIDATOR_STDERR="Writing state.md is not allowed."
run_stub_pre write_file "$PROJ_A" '{"Path":"/x/state.md","Content":"x"}'
assert_eq "A3 exit 2 -> deny" "deny" "$(jq -r '.decision' <<<"$OUT")"
assert_eq "A3 deny reason is the validator message" "Writing state.md is not allowed." "$(jq -r '.reason' <<<"$OUT")"
assert_eq "A3 adapter itself exits 0" "0" "$RC"

# A4: validator exit 1 (input or state could not be checked) -> deny
reset_stubs
export STUB_LOOP_WRITE_VALIDATOR_EXIT=1 STUB_LOOP_WRITE_VALIDATOR_STDERR="Error: Malformed state file"
run_stub_pre write_file "$PROJ_A" '{"Path":"/x/a","Content":"x"}'
assert_eq "A4 exit 1 -> deny" "deny" "$(jq -r '.decision' <<<"$OUT")"

# A5: Claude-style JSON denial on stdout -> deny
reset_stubs
export STUB_LOOP_WRITE_VALIDATOR_STDOUT='{"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"json deny"}}'
run_stub_pre write_file "$PROJ_A" '{"Path":"/x/a","Content":"x"}'
assert_eq "A5 JSON deny -> deny" "json deny" "$(jq -r '.reason' <<<"$OUT")"

# A6: edit_file and replace_file_content -> Edit with old/new text
reset_stubs
run_stub_pre edit_file "$PROJ_A" "{\"Path\":\"$PROJ_A/a.txt\",\"Target\":\"old\",\"Replacement\":\"new\"}"
CALL="$(last_stub loop-edit-validator)"
assert_eq "A6 edit_file tool_name Edit" "Edit" "$(jq -r '.input.tool_name' <<<"$CALL")"
assert_eq "A6 edit_file old_string" "old" "$(jq -r '.input.tool_input.old_string' <<<"$CALL")"
assert_eq "A6 edit_file new_string" "new" "$(jq -r '.input.tool_input.new_string' <<<"$CALL")"
assert_eq "A6 edit_file replace_all default" "false" "$(jq -r '.input.tool_input.replace_all' <<<"$CALL")"
run_stub_pre replace_file_content "$PROJ_A" "{\"TargetFile\":\"$PROJ_A/a.txt\",\"TargetContent\":\"o2\",\"ReplacementContent\":\"n2\",\"AllowMultiple\":true}"
CALL="$(last_stub loop-edit-validator)"
assert_eq "A6 replace_file_content old_string" "o2" "$(jq -r '.input.tool_input.old_string' <<<"$CALL")"
assert_eq "A6 replace_file_content replace_all" "true" "$(jq -r '.input.tool_input.replace_all' <<<"$CALL")"

# A7: multi_replace_file_content -> one Edit check per chunk; any block denies
reset_stubs
run_stub_pre multi_replace_file_content "$PROJ_A" "{\"TargetFile\":\"$PROJ_A/a.txt\",\"ReplacementChunks\":[{\"TargetContent\":\"a\",\"ReplacementContent\":\"A\"},{\"TargetContent\":\"b\",\"ReplacementContent\":\"B\"}]}"
assert_eq "A7 two chunks -> two edit checks" "2" "$(stub_calls loop-edit-validator)"
assert_eq "A7 second chunk old_string" "b" "$(jq -r '.input.tool_input.old_string' <<<"$(last_stub loop-edit-validator)")"
reset_stubs
export STUB_LOOP_EDIT_VALIDATOR_EXIT=2 STUB_LOOP_EDIT_VALIDATOR_STDERR="goal tracker immutable"
run_stub_pre multi_replace_file_content "$PROJ_A" '{"TargetFile":"/x/goal-tracker.md","ReplacementChunks":[{"TargetContent":"a","ReplacementContent":"A"}]}'
assert_eq "A7 blocked chunk -> deny" "deny" "$(jq -r '.decision' <<<"$OUT")"

# A8: sed_file and notebook_edit -> Edit with no old/new text (path-only check)
reset_stubs
run_stub_pre sed_file "$PROJ_A" "{\"TargetFile\":\"$PROJ_A/a.txt\",\"Expression\":\"s/a/b/\"}"
CALL="$(last_stub loop-edit-validator)"
assert_eq "A8 sed_file file_path" "$PROJ_A/a.txt" "$(jq -r '.input.tool_input.file_path' <<<"$CALL")"
assert_eq "A8 sed_file old_string empty" "" "$(jq -r '.input.tool_input.old_string' <<<"$CALL")"
run_stub_pre notebook_edit "$PROJ_A" "{\"NotebookPath\":\"$PROJ_A/n.ipynb\"}"
assert_eq "A8 notebook_edit path" "$PROJ_A/n.ipynb" "$(jq -r '.input.tool_input.file_path' <<<"$(last_stub loop-edit-validator)")"

# Unknown argument names: a string argument named like a path is used.
run_stub_pre sed_file "$PROJ_A" "{\"SomeFileName\":\"$PROJ_A/c.txt\"}"
assert_eq "A8 unknown path key fallback" "$PROJ_A/c.txt" "$(jq -r '.input.tool_input.file_path' <<<"$(last_stub loop-edit-validator)")"

# A9: read_file/view_file -> Read; run_command -> Bash
reset_stubs
run_stub_pre read_file "$PROJ_A" "{\"Path\":\"$PROJ_A/a.txt\",\"StartLine\":1}"
assert_eq "A9 read_file -> Read" "Read" "$(jq -r '.input.tool_name' <<<"$(last_stub loop-read-validator)")"
run_stub_pre view_file "$PROJ_A" "{\"AbsolutePath\":\"$PROJ_A/a.txt\"}"
assert_eq "A9 view_file AbsolutePath" "$PROJ_A/a.txt" "$(jq -r '.input.tool_input.file_path' <<<"$(last_stub loop-read-validator)")"
run_stub_pre run_command "$PROJ_A" '{"CommandLine":"git status","WaitMsBeforeAsync":5000}'
CALL="$(last_stub loop-bash-validator)"
assert_eq "A9 run_command -> Bash" "Bash" "$(jq -r '.input.tool_name' <<<"$CALL")"
assert_eq "A9 run_command command" "git status" "$(jq -r '.input.tool_input.command' <<<"$CALL")"
export STUB_LOOP_BASH_VALIDATOR_EXIT=2 STUB_LOOP_BASH_VALIDATOR_STDERR="git push is blocked"
run_stub_pre run_command "$PROJ_A" '{"CommandLine":"git push"}'
assert_eq "A9 blocked command -> deny" "git push is blocked" "$(jq -r '.reason' <<<"$OUT")"

# A10: tools Humanize does not check -> silent, nothing run
reset_stubs
run_stub_pre search_web "$PROJ_A" '{"query":"x"}'
assert_eq "A10 unchecked tool: no reply" "" "$OUT"
assert_eq "A10 unchecked tool: no validator" "0" "$(( $(stub_calls loop-write-validator) + $(stub_calls loop-edit-validator) + $(stub_calls loop-read-validator) + $(stub_calls loop-bash-validator) ))"

# A11: agent cwd in a subdirectory -> hooks run at the repo root
reset_stubs
mkdir -p "$PROJ_A/sub/dir"
run_stub_pre write_file "$PROJ_A/sub/dir" '{"Path":"/x/a","Content":"x"}'
assert_eq "A11 subdirectory cwd -> repo root" "$PROJ_A_REAL" "$(jq -r '.project_dir' <<<"$(last_stub loop-write-validator)")"

# A12: post-tool run_command -> post-bash hook (session binding); failures skipped
reset_stubs
run_stub post-tool "$(payload PostToolUse "$PROJ_A" '{"toolCall":{"id":"t1","name":"run_command","args":{"CommandLine":"\"/rt/scripts/setup-rlcr-loop.sh\" plan.md"}},"error":""}')"
assert_eq "A12 post-tool: no reply" "" "$OUT"
CALL="$(last_stub loop-post-bash-hook)"
assert_eq "A12 post-tool command" "\"/rt/scripts/setup-rlcr-loop.sh\" plan.md" "$(jq -r '.input.tool_input.command' <<<"$CALL")"
assert_eq "A12 post-tool session_id" "conv-1" "$(jq -r '.input.session_id' <<<"$CALL")"
run_stub post-tool "$(payload PostToolUse "$PROJ_A" '{"toolCall":{"id":"t1","name":"run_command","args":{"CommandLine":"false"}},"error":"exit status 1"}')"
assert_eq "A12 failed command: hook not run" "1" "$(stub_calls loop-post-bash-hook)"
run_stub post-tool "$(payload PostToolUse "$PROJ_A" '{"toolCall":{"id":"t1","name":"write_file","args":{}}}')"
assert_eq "A12 non-command tool: hook not run" "1" "$(stub_calls loop-post-bash-hook)"

# A13: stop -> continue with the block reason, behind the agent preamble
reset_stubs
export STUB_LOOP_CODEX_STOP_HOOK_STDOUT='{"decision":"block","reason":"Round 2 feedback: fix the parser.","systemMessage":"Loop: round 2"}'
run_stub stop "$(payload Stop "$PROJ_A" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL","fullyIdle":true,"continuationActive":false}')"
assert_eq "A13 block -> continue" "continue" "$(jq -r '.decision' <<<"$OUT")"
REASON="$(jq -r '.reason' <<<"$OUT")"
assert_contains "A13 reason keeps the hook reason" "Round 2 feedback: fix the parser." "$REASON"
assert_contains "A13 reason starts with the agy preamble" "[Humanize RLCR loop on agy]" "$REASON"
assert_contains "A13 preamble keeps reviewer text away from the user" "Never paste it to the user" "$REASON"
assert_not_contains "A13 no last-continuation note at 0" "last automatic continuation" "$REASON"
CALL="$(last_stub loop-codex-stop-hook)"
assert_eq "A13 stop payload event" "Stop" "$(jq -r '.input.hook_event_name' <<<"$CALL")"
assert_eq "A13 stop_hook_active from continuationActive" "false" "$(jq -r '.input.stop_hook_active' <<<"$CALL")"
assert_eq "A13 stop session_id" "conv-1" "$(jq -r '.input.session_id' <<<"$CALL")"

run_stub stop "$(payload Stop "$PROJ_A" '{"executionNum":3,"terminationReason":"NO_TOOL_CALL","continuationActive":true}')"
assert_eq "A13 continuationActive true -> stop_hook_active" "true" "$(jq -r '.input.stop_hook_active' <<<"$(last_stub loop-codex-stop-hook)")"

# A14: the last allowed continuation tells the agent to explain the pause
run_stub stop "$(payload Stop "$PROJ_A" '{"executionNum":9,"terminationReason":"NO_TOOL_CALL"}')"
assert_contains "A14 executionNum 9 adds the pause note" "last automatic continuation" "$(jq -r '.reason' <<<"$OUT")"
assert_contains "A14 pause note tells the user how to resume" "replying \"continue\" resumes it" "$(jq -r '.reason' <<<"$OUT")"

# A15: at the limit agy ignores continuations, so no review runs
CALLS_BEFORE="$(stub_calls loop-codex-stop-hook)"
run_stub stop "$(payload Stop "$PROJ_A" '{"executionNum":10,"terminationReason":"NO_TOOL_CALL"}')"
assert_eq "A15 executionNum 10: no reply" "" "$OUT"
assert_eq "A15 executionNum 10: stop hook not run" "$CALLS_BEFORE" "$(stub_calls loop-codex-stop-hook)"
HUMANIZE_AGY_CONTINUATION_LIMIT=4 run_stub stop "$(payload Stop "$PROJ_A" '{"executionNum":3,"terminationReason":"NO_TOOL_CALL"}')"
assert_contains "A15 limit override moves the pause note" "only 4 automatic continuations" "$(jq -r '.reason' <<<"$OUT")"

# A16: abnormal stops never start a review
for reason in USER_CANCELED ERROR MAX_INVOCATIONS MAX_FORCED_INVOCATIONS MAX_TOKEN_BUDGET_EXCEEDED; do
    CALLS_BEFORE="$(stub_calls loop-codex-stop-hook)"
    extra="{\"executionNum\":0,\"terminationReason\":\"$reason\"}"
    run_stub stop "$(payload Stop "$PROJ_A" "$extra")"
    assert_eq "A16 $reason: stop hook not run" "$CALLS_BEFORE" "$(stub_calls loop-codex-stop-hook)"
done

# Background work still running -> no review yet; a missing flag still reviews.
CALLS_BEFORE="$(stub_calls loop-codex-stop-hook)"
run_stub stop "$(payload Stop "$PROJ_A" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL","fullyIdle":false}')"
assert_eq "A16 fullyIdle false: stop hook not run" "$CALLS_BEFORE" "$(stub_calls loop-codex-stop-hook)"
assert_eq "A16 fullyIdle false: no reply" "" "$OUT"
run_stub stop "$(payload Stop "$PROJ_A" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL"}')"
assert_eq "A16 fullyIdle missing: stop hook runs" "$((CALLS_BEFORE + 1))" "$(stub_calls loop-codex-stop-hook)"

# A17: allow, exit 2, and broken hook replies
reset_stubs
run_stub stop "$(payload Stop "$PROJ_A" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL"}')"
assert_eq "A17 allow (empty stdout) -> no reply" "" "$OUT"
export STUB_LOOP_CODEX_STOP_HOOK_STDOUT='{"systemMessage":"background tasks running"}'
run_stub stop "$(payload Stop "$PROJ_A" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL"}')"
assert_eq "A17 systemMessage only -> no reply" "" "$OUT"
unset STUB_LOOP_CODEX_STOP_HOOK_STDOUT
export STUB_LOOP_CODEX_STOP_HOOK_EXIT=2 STUB_LOOP_CODEX_STOP_HOOK_STDERR="summary missing"
run_stub stop "$(payload Stop "$PROJ_A" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL"}')"
assert_contains "A17 exit 2 -> continue with stderr" "summary missing" "$(jq -r '.reason' <<<"$OUT")"
export STUB_LOOP_CODEX_STOP_HOOK_EXIT=1
run_stub stop "$(payload Stop "$PROJ_A" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL"}')"
assert_eq "A17 hook crash -> allow stop" "" "$OUT"
unset STUB_LOOP_CODEX_STOP_HOOK_EXIT STUB_LOOP_CODEX_STOP_HOOK_STDERR

# A18: bad input never crashes the adapter
OUT="$(printf 'not json' | python3 "$STUB_ADAPTER" pre-tool 2>/dev/null)"; RC=$?
assert_eq "A18 non-JSON input: exit 0" "0" "$RC"
assert_eq "A18 non-JSON input: no reply" "" "$OUT"
OUT="$(printf '' | python3 "$STUB_ADAPTER" stop 2>/dev/null)"; RC=$?
assert_eq "A18 empty input: exit 0" "0" "$RC"
OUT="$(printf '{}' | python3 "$STUB_ADAPTER" bogus 2>/dev/null)"; RC=$?
assert_eq "A18 unknown event: exit 0" "0" "$RC"
reset_stubs
STRING_ARGS_EXTRA='{"toolCall":{"name":"write_file","args":"{\"Path\":\"/x/s\",\"Content\":\"c\"}"}}'
STRING_ARGS_PAYLOAD="$(payload PreToolUse "$PROJ_A" "$STRING_ARGS_EXTRA")"
run_stub pre-tool "$STRING_ARGS_PAYLOAD"
assert_eq "A18 args given as a JSON string are parsed" "/x/s" "$(jq -r '.input.tool_input.file_path' <<<"$(last_stub loop-write-validator)")"

# A19: the shell wrapper stays silent without python3
NOPY_BIN="$TEST_DIR/nopy-bin"
mkdir -p "$NOPY_BIN"
for tool in cat dirname; do ln -s "$(command -v "$tool")" "$NOPY_BIN/$tool"; done
OUT="$(printf '%s' "$(tool_payload "$PROJ_A" write_file '{"Path":"/x/a","Content":"x"}')" | PATH="$NOPY_BIN" /bin/sh "$STUB_PLUGIN/hooks/agy-hook.sh" pre-tool 2>/dev/null)"; RC=$?
assert_eq "A19 no python3: exit 0" "0" "$RC"
assert_eq "A19 no python3: no reply" "" "$OUT"

# A20: hooks.json covers every tool the adapter checks
MATCHER="$(jq -r '.["humanize-rlcr"].PreToolUse[0].matcher' "$REPO_ROOT/agy/hooks.json")"
ADAPTER_TOOLS="$(python3 -I - "$ADAPTER" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("adapter", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
names = mod.WRITE_TOOLS | mod.EDIT_TOOLS | mod.MULTI_EDIT_TOOLS | mod.OPAQUE_EDIT_TOOLS | mod.READ_TOOLS | mod.BASH_TOOLS
print(" ".join(sorted(names)))
PY
)"
MISSING_TOOLS=""
for tool in $ADAPTER_TOOLS; do
    [[ "|$MATCHER|" == *"|$tool|"* ]] || MISSING_TOOLS="$MISSING_TOOLS $tool"
done
assert_eq "A20 PreToolUse matcher lists every checked tool" "" "$MISSING_TOOLS"
assert_eq "A20 PostToolUse matcher" "run_command" "$(jq -r '.["humanize-rlcr"].PostToolUse[0].matcher' "$REPO_ROOT/agy/hooks.json")"
assert_eq "A20 Stop timeout allows long reviews" "7200" "$(jq -r '.["humanize-rlcr"].Stop[0].timeout' "$REPO_ROOT/agy/hooks.json")"
for event in PreToolUse PostToolUse; do
    assert_eq "A20 $event command uses the wrapper" "./runtime/hooks/agy-hook.sh" "$(jq -r ".[\"humanize-rlcr\"].$event[0].hooks[0].command" "$REPO_ROOT/agy/hooks.json" | cut -d' ' -f1)"
done

echo ""

# ========================================
# Part B: adapter with the real hooks
# ========================================

echo "--- Part B: adapter with the real validators and stop hook ---"

PROJ_B="$TEST_DIR/proj-b"
init_test_git_repo "$PROJ_B"
BRANCH_B="$(git -C "$PROJ_B" rev-parse --abbrev-ref HEAD)"
printf '.humanize/\n' > "$PROJ_B/.gitignore"
git -C "$PROJ_B" add .gitignore && git -C "$PROJ_B" commit -q -m "ignore loop files"
LOOP_B="$PROJ_B/.humanize/rlcr/2026-03-01_00-00-00"
mkdir -p "$LOOP_B"
printf '# Plan\n\nLine 1\nLine 2\nLine 3\nLine 4\n' > "$PROJ_B/.humanize/plan.md"
cp "$PROJ_B/.humanize/plan.md" "$LOOP_B/plan.md"
cat > "$LOOP_B/state.md" <<EOF_STATE
---
current_round: 0
max_iterations: 42
codex_model: gpt-5.5
codex_effort: high
codex_timeout: 60
push_every_round: false
full_review_round: 5
plan_file: .humanize/plan.md
plan_tracked: false
start_branch: $BRANCH_B
base_branch: $BRANCH_B
base_commit: deadbeef
review_started: false
ask_codex_question: true
session_id: conv-1
agent_teams: false
---
EOF_STATE

run_real() {
    OUT="$(printf '%s' "$2" | python3 "$ADAPTER" "$1" 2>"$TEST_DIR/real-stderr")"
    RC=$?
}

run_real_pre() {
    local payload_json
    payload_json="$(tool_payload "$2" "$1" "$3")"
    run_real pre-tool "$payload_json"
}

run_real_pre write_file "$PROJ_B" "{\"Path\":\"$LOOP_B/state.md\",\"Content\":\"hacked\"}"
assert_eq "B1 writing state.md is denied" "deny" "$(jq -r '.decision // empty' <<<"$OUT")"
run_real_pre edit_file "$PROJ_B" "{\"Path\":\"$LOOP_B/state.md\",\"Target\":\"current_round: 0\",\"Replacement\":\"current_round: 9\"}"
assert_eq "B1 editing state.md is denied" "deny" "$(jq -r '.decision // empty' <<<"$OUT")"
run_real_pre write_file "$PROJ_B" "{\"Path\":\"$PROJ_B/feature.py\",\"Content\":\"print(1)\\n\"}"
assert_eq "B2 writing a project file is left to agy" "" "$OUT"
run_real_pre run_command "$PROJ_B" '{"CommandLine":"git status"}'
assert_eq "B2 git status is left to agy" "" "$OUT"

# Another agy conversation in the same repository is not this loop's session.
STATE_WRITE_ARGS="{\"Path\":\"$LOOP_B/state.md\",\"Content\":\"x\"}"
OTHER_SESSION="$(tool_payload "$PROJ_B" write_file "$STATE_WRITE_ARGS" | jq -c '.conversationId = "someone-else"')"
run_real pre-tool "$OTHER_SESSION"
assert_eq "B3 other conversations are not restricted" "" "$OUT"

# Stop with no round summary -> continue with the summary instructions.
run_real stop "$(payload Stop "$PROJ_B" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL","fullyIdle":true}')"
assert_eq "B4 missing summary -> continue" "continue" "$(jq -r '.decision // empty' <<<"$OUT")"
assert_contains "B4 reason names the summary file" "round-0-summary.md" "$(jq -r '.reason // empty' <<<"$OUT")"

# Session binding: setup leaves session_id empty and a pending signal; the
# PostToolUse hook fills it in from the agy conversation id.
PROJ_S="$TEST_DIR/proj-s"
init_test_git_repo "$PROJ_S"
mkdir -p "$PROJ_S/.humanize" "$PROJ_S/.humanize/rlcr/2026-04-01_00-00-00"
sed -e 's/^session_id: conv-1$/session_id:/' "$LOOP_B/state.md" > "$PROJ_S/.humanize/rlcr/2026-04-01_00-00-00/state.md"
SETUP_SIG="/opt/humanize/runtime/scripts/setup-rlcr-loop.sh"
printf '%s\n%s\n' "$PROJ_S/.humanize/rlcr/2026-04-01_00-00-00/state.md" "$SETUP_SIG" > "$PROJ_S/.humanize/.pending-session-id"
run_real post-tool "$(payload PostToolUse "$PROJ_S" "$(jq -nc --arg cmd "\"$SETUP_SIG\" plan.md" '{toolCall: {id: "t1", name: "run_command", args: {CommandLine: $cmd}}, error: ""}')")"
assert_eq "B5 session bound to the agy conversation" "session_id: conv-1" "$(grep '^session_id:' "$PROJ_S/.humanize/rlcr/2026-04-01_00-00-00/state.md")"

# B6: run_command returned before setup finished. The PostToolUse event came
# too early; the next event from the same conversation binds the loop.
PROJ_ASYNC="$TEST_DIR/proj-async"
init_test_git_repo "$PROJ_ASYNC"
SETUP_CMD_ARGS="$(jq -nc --arg cmd "bash \"$SETUP_SIG\" plan.md --skip-quiz" '{CommandLine: $cmd, WaitMsBeforeAsync: 500}')"
run_real_pre run_command "$PROJ_ASYNC" "$SETUP_CMD_ARGS"
assert_eq "B6 setup command recorded before the loop exists" "conv-1" "$(cat "$PROJ_ASYNC/.humanize/.agy-setup-conversation" 2>/dev/null)"
run_real post-tool "$(payload PostToolUse "$PROJ_ASYNC" "$(jq -nc --argjson args "$SETUP_CMD_ARGS" '{toolCall: {id: "t1", name: "run_command", args: $args}, error: ""}')")"
# Now setup finishes in the background: state.md and the pending signal appear.
ASYNC_LOOP="$PROJ_ASYNC/.humanize/rlcr/2026-04-02_00-00-00"
mkdir -p "$ASYNC_LOOP"
sed -e 's/^session_id: conv-1$/session_id:/' "$LOOP_B/state.md" > "$ASYNC_LOOP/state.md"
printf '%s\n%s\n' "$ASYNC_LOOP/state.md" "$SETUP_SIG" > "$PROJ_ASYNC/.humanize/.pending-session-id"
# Another conversation's event must not take the loop.
OTHER_READ="$(tool_payload "$PROJ_ASYNC" read_file "{\"Path\":\"$PROJ_ASYNC/file.txt\"}" | jq -c '.conversationId = "someone-else"')"
run_real pre-tool "$OTHER_READ"
assert_eq "B6 other conversation does not bind the loop" "session_id:" "$(grep '^session_id:' "$ASYNC_LOOP/state.md")"
run_real_pre read_file "$PROJ_ASYNC" "{\"Path\":\"$PROJ_ASYNC/file.txt\"}"
assert_eq "B6 next event from the setup conversation binds the loop" "session_id: conv-1" "$(grep '^session_id:' "$ASYNC_LOOP/state.md")"
assert_eq "B6 pending signal consumed" "no" "$([[ -e "$PROJ_ASYNC/.humanize/.pending-session-id" ]] && echo yes || echo no)"
assert_eq "B6 setup record removed" "no" "$([[ -e "$PROJ_ASYNC/.humanize/.agy-setup-conversation" ]] && echo yes || echo no)"

# B7: only real setup invocations are recorded.
SETUP_CHECK="$(python3 -I - "$ADAPTER" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("adapter", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
cases = [
    '"/rt/scripts/setup-rlcr-loop.sh" plan.md',
    "bash /rt/scripts/setup-rlcr-loop.sh plan.md",
    "echo setup-rlcr-loop.sh",
    "cat /rt/scripts/setup-rlcr-loop.sh",
    'unbalanced "quote',
    '"/rt/scripts/setup-rlcr-loop.sh" --help',
    '"/rt/scripts/setup-rlcr-loop.sh" --skip-impl # see --help for options',
    '"/rt/scripts/setup-rlcr-loop.sh" plan.md && echo --help',
    '"/rt/scripts/setup-rlcr-loop.sh" plan.md; echo -h',
    'bash /rt/scripts/setup-rlcr-loop.sh >help.txt --help',
    'bash /opt/humanize#dev/scripts/setup-rlcr-loop.sh --skip-impl',
    '"/rt/scripts/setup-rlcr-loop.sh" plan.md 2>&1 >log.txt',
]
print(" ".join("1" if mod.is_setup_command(c) else "0" for c in cases))
PY
)"
assert_eq "B7 setup command detection (help does not count; comments and later commands ignored)" "1 1 0 0 0 0 1 1 1 0 1 1" "$SETUP_CHECK"

# B9: conversation A's setup is still waiting to be bound when conversation B
# runs setup. B must not take A's loop; A's next event still binds it.
PROJ_RACE="$TEST_DIR/proj-race"
init_test_git_repo "$PROJ_RACE"
run_real_pre run_command "$PROJ_RACE" "$SETUP_CMD_ARGS"
RACE_LOOP="$PROJ_RACE/.humanize/rlcr/2026-04-03_00-00-00"
mkdir -p "$RACE_LOOP"
sed -e 's/^session_id: conv-1$/session_id:/' "$LOOP_B/state.md" > "$RACE_LOOP/state.md"
printf '%s\n%s\n' "$RACE_LOOP/state.md" "$SETUP_SIG" > "$PROJ_RACE/.humanize/.pending-session-id"
B_SETUP="$(tool_payload "$PROJ_RACE" run_command "$SETUP_CMD_ARGS" | jq -c '.conversationId = "conv-b"')"
run_real pre-tool "$B_SETUP"
assert_eq "B9 second setup does not take the pending loop" "session_id:" "$(grep '^session_id:' "$RACE_LOOP/state.md")"
assert_eq "B9 setup record still names the first conversation" "conv-1" "$(cat "$PROJ_RACE/.humanize/.agy-setup-conversation" 2>/dev/null)"
run_real_pre read_file "$PROJ_RACE" "{\"Path\":\"$PROJ_RACE/file.txt\"}"
assert_eq "B9 first conversation still binds its loop" "session_id: conv-1" "$(grep '^session_id:' "$RACE_LOOP/state.md")"

# B10: a leftover signal from a loop that has ended does not block a new setup.
PROJ_STALE="$TEST_DIR/proj-stale"
init_test_git_repo "$PROJ_STALE"
mkdir -p "$PROJ_STALE/.humanize"
printf '%s\n%s\n' "$PROJ_STALE/.humanize/rlcr/old-loop/state.md" "$SETUP_SIG" > "$PROJ_STALE/.humanize/.pending-session-id"
NEW_SETUP="$(tool_payload "$PROJ_STALE" run_command "$SETUP_CMD_ARGS" | jq -c '.conversationId = "conv-new"')"
run_real pre-tool "$NEW_SETUP"
assert_eq "B10 stale signal: new setup is recorded" "conv-new" "$(cat "$PROJ_STALE/.humanize/.agy-setup-conversation" 2>/dev/null)"
STALE_LOOP="$PROJ_STALE/.humanize/rlcr/2026-04-04_00-00-00"
mkdir -p "$STALE_LOOP"
sed -e 's/^session_id: conv-1$/session_id:/' "$LOOP_B/state.md" > "$STALE_LOOP/state.md"
printf '%s\n%s\n' "$STALE_LOOP/state.md" "$SETUP_SIG" > "$PROJ_STALE/.humanize/.pending-session-id"
NEW_READ="$(tool_payload "$PROJ_STALE" read_file "{\"Path\":\"$PROJ_STALE/file.txt\"}" | jq -c '.conversationId = "conv-new"')"
run_real pre-tool "$NEW_READ"
assert_eq "B10 stale signal: new loop binds to the new conversation" "session_id: conv-new" "$(grep '^session_id:' "$STALE_LOOP/state.md")"

# B8: background work still running -> the real stop hook does not run
PROJ_IDLE="$TEST_DIR/proj-idle"
init_test_git_repo "$PROJ_IDLE"
mkdir -p "$PROJ_IDLE/.humanize/rlcr/2026-03-01_00-00-00"
cp "$LOOP_B/state.md" "$PROJ_IDLE/.humanize/rlcr/2026-03-01_00-00-00/state.md"
run_real stop "$(payload Stop "$PROJ_IDLE" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL","fullyIdle":false}')"
assert_eq "B8 busy agent: no review, no reply" "" "$OUT"

echo ""

# ========================================
# Part C: read-only Claude reviewer
# ========================================

echo "--- Part C: Claude as verifier and code reviewer ---"

MOCK_BIN="$TEST_DIR/mock-bin"
mkdir -p "$MOCK_BIN"
# Mock claude: records argv (one per line), stdin, and selected env; prints $MOCK_CLAUDE_OUTPUT.
cat > "$MOCK_BIN/claude" <<EOF
#!/usr/bin/env bash
n=\$(( \$(ls "$TEST_DIR"/claude-call-*.args 2>/dev/null | wc -l) + 1 ))
printf '%s\n' "\$@" > "$TEST_DIR/claude-call-\$n.args"
cat > "$TEST_DIR/claude-call-\$n.stdin"
printf 'CLAUDECODE=%s\nCLAUDE_PROJECT_DIR=%s\nPWD=%s\n' "\${CLAUDECODE:-}" "\${CLAUDE_PROJECT_DIR:-}" "\$(pwd -P)" > "$TEST_DIR/claude-call-\$n.env"
printf '%s\n' "\${MOCK_CLAUDE_OUTPUT:-No issues found.}"
EOF
chmod +x "$MOCK_BIN/claude"
# Mock codex: must not be called when Claude has both roles.
cat > "$MOCK_BIN/codex" <<EOF
#!/usr/bin/env bash
case " \$* " in
    *" --help "*) exit 0 ;;
esac
echo called >> "$TEST_DIR/codex-called"
echo "No issues found."
EOF
chmod +x "$MOCK_BIN/codex"

make_loop_c() {
    PROJ_C="$TEST_DIR/proj-c-$1"
    init_test_git_repo "$PROJ_C"
    printf '.humanize/\n' > "$PROJ_C/.gitignore"
    git -C "$PROJ_C" add .gitignore && git -C "$PROJ_C" commit -q -m "ignore loop files"
    BASE_C="$(git -C "$PROJ_C" rev-parse HEAD)"
    BRANCH_C="$(git -C "$PROJ_C" rev-parse --abbrev-ref HEAD)"
    echo "feature" > "$PROJ_C/feature.txt"
    git -C "$PROJ_C" add feature.txt && git -C "$PROJ_C" commit -q -m "add feature"
    LOOP_C="$PROJ_C/.humanize/rlcr/2026-05-01_00-00-00"
    mkdir -p "$LOOP_C"
    printf '# Plan\n\nAdd feature.txt.\nLine 2\nLine 3\nLine 4\n' > "$PROJ_C/.humanize/plan.md"
    cp "$PROJ_C/.humanize/plan.md" "$LOOP_C/plan.md"
    cat > "$LOOP_C/state.md" <<EOF_STATE
---
current_round: 1
max_iterations: 42
codex_model: gpt-5.5
codex_effort: high
codex_timeout: 60
push_every_round: false
full_review_round: 5
plan_file: .humanize/plan.md
plan_tracked: false
start_branch: $BRANCH_C
base_branch: $BRANCH_C
base_commit: $BASE_C
review_started: $2
ask_codex_question: false
session_id: conv-1
agent_teams: false
mainline_stall_count: 0
last_mainline_verdict: unknown
drift_status: normal
---
EOF_STATE
    if [[ "$2" == "true" ]]; then
        echo "build_finish_round=1" > "$LOOP_C/.review-phase-started"
    fi
    cat > "$LOOP_C/goal-tracker.md" <<'EOF_GT'
# Goal Tracker
## IMMUTABLE SECTION
### Ultimate Goal
Add feature.txt
### Acceptance Criteria
| ID | Criterion |
|----|-----------|
| AC-1 | feature.txt exists |
---
## MUTABLE SECTION
#### Active Tasks
| Task | Target AC | Status |
|------|-----------|--------|
| Add file | AC-1 | completed |
EOF_GT
    printf '# Round 1 Contract\n\n- Mainline Objective: add feature.txt\n- Target ACs: AC-1\n- Blocking Side Issues In Scope: none\n- Queued Side Issues Out of Scope: none\n- Success Criteria: file exists\n' > "$LOOP_C/round-1-contract.md"
    printf '# Round 1 Summary\n\nAdded feature.txt.\n\n## BitLesson Delta\n\nAction: none\n' > "$LOOP_C/round-1-summary.md"
    rm -f "$TEST_DIR"/claude-call-* "$TEST_DIR/codex-called"
}

run_stop_c() {
    OUT="$(printf '%s' "$(payload Stop "$PROJ_C" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL"}')" \
        | PATH="$MOCK_BIN:$PATH" CLAUDECODE=1 python3 "$ADAPTER" stop 2>"$TEST_DIR/c-stderr")"
}

# C1: Claude verifier, work not done -> feedback goes back to the agent
make_loop_c verify false
export HUMANIZE_RLCR_VERIFIER=claude HUMANIZE_RLCR_REVIEWER=claude
export MOCK_CLAUDE_OUTPUT="The parser is still missing.

Mainline Progress Verdict: STALLED"
run_stop_c
assert_eq "C1 not done -> continue" "continue" "$(jq -r '.decision // empty' <<<"$OUT")"
assert_contains "C1 Claude review text reaches the agent" "The parser is still missing." "$(jq -r '.reason // empty' <<<"$OUT")"
assert_eq "C1 codex not called" "no" "$([[ -f "$TEST_DIR/codex-called" ]] && echo yes || echo no)"
if [[ -f "$TEST_DIR/claude-call-1.args" ]]; then
    ARGS="$(cat "$TEST_DIR/claude-call-1.args")"
    assert_contains "C1 print mode" "-p" "$ARGS"
    assert_contains "C1 hooks disabled" '{"disableAllHooks":true}' "$ARGS"
    assert_contains "C1 only Read, Grep and Glob are loaded" "$(printf -- '--tools\nRead,Grep,Glob\n')" "$ARGS"
    assert_not_contains "C1 no shell patterns are allowed" "Bash(" "$ARGS"
    assert_contains "C1 Bash denied" "$(printf -- '--disallowedTools\nBash')" "$ARGS"
    assert_contains "C1 Write denied" "$(printf 'Bash\nWrite')" "$ARGS"
    assert_contains "C1 MCP servers off" "--strict-mcp-config" "$ARGS"
    assert_contains "C1 no session saved" "--no-session-persistence" "$ARGS"
    assert_not_contains "C1 no API-key-only bare mode" "--bare" "$ARGS"
    STDIN="$(cat "$TEST_DIR/claude-call-1.stdin")"
    assert_contains "C1 prompt has the read-only note" "Reviewer Mode: Read-Only" "$STDIN"
    assert_contains "C1 prompt asks for tracker corrections, not edits" "Goal Tracker Corrections" "$STDIN"
    assert_not_contains "C1 prompt does not ask the reviewer to edit the tracker" "Update @$LOOP_C/goal-tracker.md yourself" "$STDIN"
    ENV_C="$(cat "$TEST_DIR/claude-call-1.env")"
    assert_contains "C1 CLAUDECODE unset for the nested run" "CLAUDECODE=
" "$ENV_C"
    assert_contains "C1 CLAUDE_PROJECT_DIR unset for the nested run" "CLAUDE_PROJECT_DIR=
" "$ENV_C"
    assert_contains "C1 runs in the project" "PWD=$(cd "$PROJ_C" && pwd -P)" "$ENV_C"
else
    fail "C1 claude was called" "claude-call-1.args" "missing; stderr: $(tail -5 "$TEST_DIR/c-stderr")"
fi
assert_contains "C1 result file holds the Claude review" "The parser is still missing." "$(cat "$LOOP_C/round-1-review-result.md" 2>/dev/null)"

# C2: Claude verifier says COMPLETE -> Claude code review finds an issue
make_loop_c review-issue false
export MOCK_CLAUDE_OUTPUT="All done.

Mainline Progress Verdict: ADVANCED

COMPLETE"
# The mock prints the same text for every call; the second call is the code
# review, so switch the output between calls with a counter file.
cat > "$MOCK_BIN/claude-review-output" <<'EOF'
Checked the diff.

[P1] feature.txt:1 - the file has no trailing context
EOF
cat > "$MOCK_BIN/claude" <<EOF
#!/usr/bin/env bash
n=\$(( \$(ls "$TEST_DIR"/claude-call-*.args 2>/dev/null | wc -l) + 1 ))
printf '%s\n' "\$@" > "$TEST_DIR/claude-call-\$n.args"
cat > "$TEST_DIR/claude-call-\$n.stdin"
if [[ "\$n" -ge 2 ]]; then cat "$MOCK_BIN/claude-review-output"; else printf '%s\n' "\$MOCK_CLAUDE_OUTPUT"; fi
EOF
chmod +x "$MOCK_BIN/claude"
run_stop_c
assert_eq "C2 two Claude calls (verify + code review)" "2" "$(ls "$TEST_DIR"/claude-call-*.args 2>/dev/null | wc -l | tr -d ' ')"
assert_eq "C2 code review finding -> continue" "continue" "$(jq -r '.decision // empty' <<<"$OUT")"
assert_contains "C2 finding reaches the agent" "[P1] feature.txt:1" "$(jq -r '.reason // empty' <<<"$OUT")"
DIFF_FILE_C="$LOOP_C/round-2-review-diff.md"
assert_contains "C2 review prompt points at the diff file" "$DIFF_FILE_C" "$(cat "$TEST_DIR/claude-call-2.stdin" 2>/dev/null)"
assert_not_contains "C2 review prompt asks for no shell commands" "Run \`git diff" "$(cat "$TEST_DIR/claude-call-2.stdin" 2>/dev/null)"
assert_contains "C2 diff file holds the branch diff" "+feature" "$(cat "$DIFF_FILE_C" 2>/dev/null)"
assert_contains "C2 diff file lists the commits" "add feature" "$(cat "$DIFF_FILE_C" 2>/dev/null)"
assert_eq "C2 codex not called" "no" "$([[ -f "$TEST_DIR/codex-called" ]] && echo yes || echo no)"

# C3: review phase, Claude finds nothing -> finalize, without the polish step on agy
make_loop_c review-clean true
printf 'Checked the diff.\n\nNo issues found.\n' > "$MOCK_BIN/claude-review-output"
rm -f "$TEST_DIR"/claude-call-*
# In the review phase the first call is already the code review.
cat > "$MOCK_BIN/claude" <<EOF
#!/usr/bin/env bash
n=\$(( \$(ls "$TEST_DIR"/claude-call-*.args 2>/dev/null | wc -l) + 1 ))
printf '%s\n' "\$@" > "$TEST_DIR/claude-call-\$n.args"
cat > "$TEST_DIR/claude-call-\$n.stdin"
cat "$MOCK_BIN/claude-review-output"
EOF
chmod +x "$MOCK_BIN/claude"
run_stop_c
REASON="$(jq -r '.reason // empty' <<<"$OUT")"
assert_eq "C3 clean review -> finalize-state.md" "yes" "$([[ -f "$LOOP_C/finalize-state.md" ]] && echo yes || echo no)"
assert_contains "C3 finalize prompt reaches the agent" "finalize-summary.md" "$REASON"
assert_not_contains "C3 no polish section on agy" "Polish the Finalize Summary" "$REASON"
assert_not_contains "C3 no polish command on agy" "polish-gemini.sh\" --auto" "$REASON"
assert_contains "C3 plain-language instruction instead" "Write the Finalize Summary for People" "$REASON"

# C3b: a reply that is neither findings nor "No issues found." is a failed review
make_loop_c review-unfinished true
printf 'I could not open the diff file, so I cannot review these changes.\n' > "$MOCK_BIN/claude-review-output"
rm -f "$TEST_DIR"/claude-call-*
run_stop_c
assert_eq "C3b unfinished review does not finalize" "no" "$([[ -f "$LOOP_C/finalize-state.md" ]] && echo yes || echo no)"
assert_eq "C3b unfinished review blocks" "continue" "$(jq -r '.decision // empty' <<<"$OUT")"
assert_contains "C3b agent is told the review failed" "review" "$(jq -r '.reason // empty' <<<"$OUT" | tr 'A-Z' 'a-z')"

# C3c: the review base no longer resolves -> fail before calling Claude
make_loop_c review-bad-base true
sed -i.bak -e 's/^base_commit: .*/base_commit: 0123456789abcdef0123456789abcdef01234567/' "$LOOP_C/state.md" && rm -f "$LOOP_C/state.md.bak"
printf 'Checked.\n\nNo issues found.\n' > "$MOCK_BIN/claude-review-output"
rm -f "$TEST_DIR"/claude-call-*
run_stop_c
assert_eq "C3c bad base does not finalize" "no" "$([[ -f "$LOOP_C/finalize-state.md" ]] && echo yes || echo no)"
assert_eq "C3c bad base blocks" "continue" "$(jq -r '.decision // empty' <<<"$OUT")"
assert_eq "C3c Claude not called without a diff" "0" "$(ls "$TEST_DIR"/claude-call-*.args 2>/dev/null | wc -l | tr -d ' ')"

# C4: the same finalize on Claude Code (no HUMANIZE_HOST) keeps the polish step
make_loop_c review-clean-claude true
OUT="$(printf '%s' '{"hook_event_name":"Stop","session_id":"conv-1","stop_hook_active":false}' \
    | (cd "$PROJ_C" && PATH="$MOCK_BIN:$PATH" CLAUDE_PROJECT_DIR="$PROJ_C" "$REPO_ROOT/hooks/loop-codex-stop-hook.sh" 2>/dev/null))"
assert_contains "C4 Claude Code finalize keeps the polish step" "Polish the Finalize Summary" "$(jq -r '.reason // empty' <<<"$OUT")"

# C5: missing claude CLI blocks with a clear message
make_loop_c missing-claude false
EMPTY_BIN="$TEST_DIR/no-claude-bin"
mkdir -p "$EMPTY_BIN"
# Every command on PATH except claude (first match wins, like PATH lookup).
IFS=: read -r -a PATH_DIRS <<<"$PATH"
for dir in "${PATH_DIRS[@]}"; do
    [[ -d "$dir" ]] || continue
    for exe in "$dir"/*; do
        tool="$(basename "$exe")"
        [[ "$tool" == "claude" || -e "$EMPTY_BIN/$tool" || ! -x "$exe" || -d "$exe" ]] && continue
        ln -s "$exe" "$EMPTY_BIN/$tool" 2>/dev/null || true
    done
done
OUT="$(printf '%s' "$(payload Stop "$PROJ_C" '{"executionNum":0,"terminationReason":"NO_TOOL_CALL"}')" \
    | PATH="$EMPTY_BIN" python3 "$ADAPTER" stop 2>/dev/null)"
assert_contains "C5 missing claude CLI is reported" "Claude CLI Not Found" "$(jq -r '.reason // empty' <<<"$OUT")"

unset HUMANIZE_RLCR_VERIFIER HUMANIZE_RLCR_REVIEWER MOCK_CLAUDE_OUTPUT

# C6: config keys select the reviewer; bad values fall back to codex
mkdir -p "$TEST_DIR/cfg-proj/.humanize"
init_test_git_repo "$TEST_DIR/cfg-proj"
printf '{"rlcr_verifier":"claude","rlcr_reviewer":"bogus"}\n' > "$TEST_DIR/cfg-proj/.humanize/config.json"
CFG="$(cd "$TEST_DIR/cfg-proj" && CLAUDE_PROJECT_DIR="$TEST_DIR/cfg-proj" bash -c 'source "$1/hooks/lib/loop-common.sh" 2>/dev/null; printf "%s %s" "$RLCR_VERIFIER" "$RLCR_REVIEWER"' _ "$REPO_ROOT")"
assert_eq "C6 config rlcr_verifier=claude, invalid reviewer -> codex" "claude codex" "$CFG"
CFG="$(cd "$TEST_DIR/cfg-proj" && CLAUDE_PROJECT_DIR="$TEST_DIR/cfg-proj" HUMANIZE_RLCR_VERIFIER=codex bash -c 'source "$1/hooks/lib/loop-common.sh" 2>/dev/null; printf "%s" "$RLCR_VERIFIER"' _ "$REPO_ROOT")"
assert_eq "C6 environment overrides config" "codex" "$CFG"
assert_eq "C6 default config: verifier" "codex" "$(jq -r '.rlcr_verifier' "$REPO_ROOT/config/default_config.json")"
assert_eq "C6 default config: reviewer" "codex" "$(jq -r '.rlcr_reviewer' "$REPO_ROOT/config/default_config.json")"

echo ""

# ========================================
# Part D: installer
# ========================================

echo "--- Part D: install-agy-plugin.sh ---"

PLUGINS="$TEST_DIR/agy-plugins"
INSTALL_OUT="$(PATH="$MOCK_BIN:$PATH" "$REPO_ROOT/scripts/install-agy-plugin.sh" --plugins-dir "$PLUGINS" --no-validate 2>&1)"; RC=$?
assert_eq "D1 installer exits 0" "0" "$RC"
TARGET="$PLUGINS/humanize"
PLUGINS_ABS="$(cd "$PLUGINS" && pwd)"
for path in plugin.json hooks.json skills/humanize-start-rlcr-loop/SKILL.md skills/humanize-cancel-rlcr-loop/SKILL.md skills/humanize-gen-plan/SKILL.md runtime/commands/gen-plan.md runtime/agents/draft-relevance-checker.md runtime/scripts/agy-rlcr-run.sh runtime/scripts/lib/agy_rlcr_run.py runtime/scripts/ask-codex.sh runtime/hooks/agy-hook.sh runtime/hooks/agy-hook-adapter.py runtime/hooks/loop-codex-stop-hook.sh runtime/scripts/setup-rlcr-loop.sh runtime/prompt-template/reviewer/claude-code-review.md runtime/config/default_config.json; do
    assert_eq "D1 installed $path" "yes" "$([[ -e "$TARGET/$path" ]] && echo yes || echo no)"
done
assert_eq "D1 wrapper is executable" "yes" "$([[ -x "$TARGET/runtime/hooks/agy-hook.sh" ]] && echo yes || echo no)"
assert_eq "D2 manifest name" "humanize" "$(jq -r '.name' "$TARGET/plugin.json")"
assert_eq "D2 manifest version matches the Claude plugin" "$(jq -r '.version' "$REPO_ROOT/.claude-plugin/plugin.json")" "$(jq -r '.version' "$TARGET/plugin.json")"
assert_eq "D2 hooks.json copied" "$(jq -S . "$REPO_ROOT/agy/hooks.json")" "$(jq -S . "$TARGET/hooks.json")"
START_SKILL="$(cat "$TARGET/skills/humanize-start-rlcr-loop/SKILL.md")"
assert_contains "D3 skill has the runtime path" "\"$PLUGINS_ABS/humanize/runtime/scripts/setup-rlcr-loop.sh\"" "$START_SKILL"
assert_not_contains "D3 no placeholder left" "{{" "$START_SKILL"
for word in 'CLAUDE_PLUGIN_ROOT' '$ARGUMENTS' 'AskUserQuestion tool'; do
    assert_not_contains "D3 no Claude-only reference: $word" "$word" "$START_SKILL"
done
GEN_PLAN_SKILL="$(cat "$TARGET/skills/humanize-gen-plan/SKILL.md")"
assert_contains "D3 gen-plan skill points at the installed procedure" "$PLUGINS_ABS/humanize/runtime/commands/gen-plan.md" "$GEN_PLAN_SKILL"
assert_contains "D3 gen-plan skill calls the installed ask-codex" "\"$PLUGINS_ABS/humanize/runtime/scripts/ask-codex.sh\"" "$GEN_PLAN_SKILL"
assert_not_contains "D3 gen-plan skill has no placeholder left" "{{" "$GEN_PLAN_SKILL"
assert_contains "D3 gen-plan skill keeps the parsed labels" "Claude Position" "$GEN_PLAN_SKILL"
assert_contains "D3 gen-plan skill forbids polish" "Do not run \`polish-gemini.sh\`" "$GEN_PLAN_SKILL"
GEN_PLAN_PROC="$(cat "$TARGET/runtime/commands/gen-plan.md")"
assert_not_contains "D3 installed gen-plan procedure has no plugin variable left" '${CLAUDE_PLUGIN_ROOT}' "$GEN_PLAN_PROC"
assert_contains "D3 installed gen-plan procedure uses the runtime scripts" "\"$PLUGINS_ABS/humanize/runtime/scripts/validate-gen-plan-io.sh\"" "$GEN_PLAN_PROC"
assert_contains "D3 repository gen-plan procedure is unchanged" '${CLAUDE_PLUGIN_ROOT}/scripts/validate-gen-plan-io.sh' "$(cat "$REPO_ROOT/commands/gen-plan.md")"
assert_contains "D3 start skill explains unattended runs" "\"$PLUGINS_ABS/humanize/runtime/scripts/agy-rlcr-run.sh\"" "$START_SKILL"
assert_eq "D3 driver is executable" "yes" "$([[ -x "$TARGET/runtime/scripts/agy-rlcr-run.sh" ]] && echo yes || echo no)"
assert_contains "D3 installer lists the gen-plan skill" "humanize-gen-plan" "$INSTALL_OUT"
assert_eq "D3 no __pycache__ copied" "" "$(find "$TARGET" -name __pycache__)"
assert_eq "D3 no top-level agents or rules folder" "no" "$([[ -e "$TARGET/agents" || -e "$TARGET/rules" ]] && echo yes || echo no)"

# Reinstall replaces the old copy and leaves no staging folders.
echo stale > "$TARGET/runtime/stale-file"
PATH="$MOCK_BIN:$PATH" "$REPO_ROOT/scripts/install-agy-plugin.sh" --plugins-dir "$PLUGINS" --no-validate >/dev/null 2>&1; RC=$?
assert_eq "D4 reinstall exits 0" "0" "$RC"
assert_eq "D4 reinstall removes stale files" "no" "$([[ -e "$TARGET/runtime/stale-file" ]] && echo yes || echo no)"
assert_eq "D4 no staging or backup folders left" "" "$(find "$PLUGINS" -maxdepth 1 -name '.humanize.*')"

DRY_OUT="$("$REPO_ROOT/scripts/install-agy-plugin.sh" --plugins-dir "$TEST_DIR/dry-plugins" --dry-run 2>&1)"
assert_eq "D5 dry run writes nothing" "no" "$([[ -e "$TEST_DIR/dry-plugins/humanize" ]] && echo yes || echo no)"
assert_contains "D5 dry run says what it would do" "DRY-RUN" "$DRY_OUT"

# The installed adapter works from the plugin folder (agy runs hooks there).
STATE_WRITE_PAYLOAD="$(tool_payload "$PROJ_B" write_file "$STATE_WRITE_ARGS")"
OUT="$(cd "$TARGET" && printf '%s' "$STATE_WRITE_PAYLOAD" | sh -c './runtime/hooks/agy-hook.sh pre-tool' 2>/dev/null)"
assert_eq "D6 installed hook denies a state.md write" "deny" "$(jq -r '.decision // empty' <<<"$OUT")"

if command -v agy >/dev/null 2>&1; then
    if agy plugin validate "$TARGET" >/dev/null 2>&1; then
        pass "D7 agy plugin validate passes"
    else
        fail "D7 agy plugin validate passes" "exit 0" "$(agy plugin validate "$TARGET" 2>&1 | tail -5)"
    fi
else
    skip "D7 agy plugin validate" "agy not installed"
fi

# ========================================
# Part E: unattended-run checks
# ========================================

echo "--- Part E: unattended-run checks ---"

PROJ_E="$TEST_DIR/proj-unattended"
init_test_git_repo "$PROJ_E"
OUTSIDE_E="$TEST_DIR/outside-e"
mkdir -p "$OUTSIDE_E"

run_unattended() {
    OUT="$(printf '%s' "$2" | HUMANIZE_AGY_UNATTENDED=1 python3 "$ADAPTER" "$1" 2>"$TEST_DIR/real-stderr")"
    RC=$?
}
run_unattended_pre() {
    local payload_json
    payload_json="$(tool_payload "$2" "$1" "$3")"
    run_unattended pre-tool "$payload_json"
}

# No loop yet: the checks apply from the first tool call.
run_unattended_pre write_file "$PROJ_E" "{\"Path\":\"$OUTSIDE_E/x.txt\",\"Content\":\"x\"}"
assert_eq "E1 write outside the project is denied" "deny" "$(jq -r '.decision // empty' <<<"$OUT")"
assert_contains "E1 reason names the project" "only files inside the project" "$(jq -r '.reason // empty' <<<"$OUT")"
run_unattended_pre write_file "$PROJ_E" "{\"Path\":\"$PROJ_E/../outside-e/y.txt\",\"Content\":\"x\"}"
assert_eq "E1 a .. path out of the project is denied" "deny" "$(jq -r '.decision // empty' <<<"$OUT")"
ln -s "$OUTSIDE_E" "$PROJ_E/link-out"
run_unattended_pre edit_file "$PROJ_E" "{\"Path\":\"$PROJ_E/link-out/z.txt\",\"Target\":\"a\",\"Replacement\":\"b\"}"
assert_eq "E1 a symlink out of the project is denied" "deny" "$(jq -r '.decision // empty' <<<"$OUT")"
ARTIFACTS_E="$TEST_DIR/agy-brain/conv-1"
mkdir -p "$ARTIFACTS_E"
ARTIFACT_PAYLOAD="$(tool_payload "$PROJ_E" write_to_file "{\"TargetFile\":\"$ARTIFACTS_E/task.md\",\"CodeContent\":\"x\"}" | jq -c --arg a "$ARTIFACTS_E" '.artifactDirectoryPath = $a')"
run_unattended pre-tool "$ARTIFACT_PAYLOAD"
assert_eq "E2 agy's own artifact folder is allowed" "" "$OUT"
RELATIVE_ESCAPE="$(tool_payload "$PROJ_E" write_file '{"Path":"link-out/rel.txt","Content":"x"}' | jq -c --arg a "$ARTIFACTS_E" '.artifactDirectoryPath = $a')"
run_unattended pre-tool "$RELATIVE_ESCAPE"
assert_eq "E1 a relative symlink out of the project is denied even with an artifact folder" "deny" "$(jq -r '.decision // empty' <<<"$OUT")"
run_unattended_pre write_file "$PROJ_E" "{\"Path\":\"$PROJ_E/src/new.txt\",\"Content\":\"x\"}"
assert_eq "E2 write inside the project is left to agy" "" "$OUT"
run_unattended_pre write_file "$PROJ_E" '{"Path":"src/relative.txt","Content":"x"}'
assert_eq "E2 relative path inside the project is left to agy" "" "$OUT"
run_unattended_pre read_file "$PROJ_E" "{\"Path\":\"$OUTSIDE_E/x.txt\"}"
assert_eq "E2 reading outside the project is allowed" "" "$OUT"
run_unattended_pre sed_file "$PROJ_E" '{"Expression":"s/a/b/"}'
assert_eq "E3 file tool without a path is denied" "deny" "$(jq -r '.decision // empty' <<<"$OUT")"

run_unattended_pre run_command "$PROJ_E" '{"CommandLine":"git add -A && git commit -m \"push the fix\""}'
assert_eq "E4 commit mentioning push is allowed" "" "$OUT"
for cmd in 'git push' 'git push origin HEAD' 'cd sub && git -C .. push' 'bash -c \"git push\"' 'echo $(git push)'; do
    run_unattended_pre run_command "$PROJ_E" "{\"CommandLine\":\"$cmd\"}"
    assert_eq "E4 denied: $cmd" "deny" "$(jq -r '.decision // empty' <<<"$OUT")"
done
assert_contains "E4 reason says how to allow pushes" "--push-every-round" "$(jq -r '.reason // empty' <<<"$OUT")"
for args in '{"CommandLine":"git 2>/dev/null push origin HEAD"}' '{"CommandLine":"git -C . \\\npush origin HEAD"}' '{"CommandLine":"git \\\n  push"}'; do
    run_unattended_pre run_command "$PROJ_E" "$args"
    assert_eq "E4 denied: $(jq -r .CommandLine <<<"$args" | tr '\n' ' ')" "deny" "$(jq -r '.decision // empty' <<<"$OUT")"
done
run_unattended_pre run_command "$PROJ_E" '{"CommandLine":"git status 2>/dev/null && git log --oneline \\\n  --grep push"}'
assert_eq "E4 a log search for push is allowed" "" "$OUT"

# Without the variable nothing changes.
OUT="$(tool_payload "$PROJ_E" write_file "{\"Path\":\"$OUTSIDE_E/x.txt\",\"Content\":\"x\"}" | python3 "$ADAPTER" pre-tool 2>/dev/null)"
assert_eq "E5 attended: write outside the project is left to agy" "" "$OUT"
OUT="$(tool_payload "$PROJ_E" run_command '{"CommandLine":"git push"}' | python3 "$ADAPTER" pre-tool 2>/dev/null)"
assert_eq "E5 attended: git push is left to agy" "" "$OUT"

# A loop started with --push-every-round may push; other conversations may not.
PROJ_EP="$TEST_DIR/proj-unattended-push"
init_test_git_repo "$PROJ_EP"
LOOP_EP="$PROJ_EP/.humanize/rlcr/2026-04-05_00-00-00"
mkdir -p "$LOOP_EP"
sed -e 's/^push_every_round: .*/push_every_round: true/' "$LOOP_B/state.md" > "$LOOP_EP/state.md"
cp "$LOOP_B/goal-tracker.md" "$LOOP_EP/" 2>/dev/null || true
run_unattended_pre run_command "$PROJ_EP" '{"CommandLine":"git push"}'
assert_eq "E6 push allowed with --push-every-round" "" "$(jq -r '.decision // empty' <<<"$OUT")"
OTHER_PUSH="$(tool_payload "$PROJ_EP" run_command '{"CommandLine":"git push"}' | jq -c '.conversationId = "conv-other"')"
run_unattended pre-tool "$OTHER_PUSH"
assert_eq "E6 push denied for another conversation" "deny" "$(jq -r '.decision // empty' <<<"$OUT")"

# ========================================
# Part F: agy-rlcr-run.sh with a mock agy
# ========================================

echo "--- Part F: agy-rlcr-run.sh ---"

DRIVER="$REPO_ROOT/scripts/agy-rlcr-run.sh"
MOCK_AGY="$TEST_DIR/mock-agy/agy"
mkdir -p "$(dirname "$MOCK_AGY")"
cat > "$MOCK_AGY" <<'MOCK'
#!/usr/bin/env bash
# Mock agy: records each call and moves a fake loop forward.
dir="${MOCK_AGY_DIR:?}"
n=$(( $(cat "$dir/count" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$dir/count"
conv="" prompt=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
    case "${args[$i]}" in
        --conversation) conv="${args[$((i + 1))]}" ;;
        -p) prompt="${args[$((i + 1))]}" ;;
    esac
done
printf '%s\n' "$@" > "$dir/call-$n.args"
printf '%s' "$prompt" > "$dir/call-$n.prompt"
printf 'unattended=%s cwd=%s\n' "${HUMANIZE_AGY_UNATTENDED:-}" "$PWD" > "$dir/call-$n.env"
env | grep '^GIT_CONFIG_' | sort > "$dir/call-$n.gitenv"
if [[ -n "${MOCK_AGY_TRY_PUSH:-}" ]]; then
    git push origin HEAD:refs/heads/probe-$n > "$dir/call-$n.push-out" 2>&1
    echo $? > "$dir/call-$n.push"
fi
[[ -n "$conv" ]] || conv="${MOCK_AGY_CONV:-mock-conv}"
loop=".humanize/rlcr/2026-05-01_00-00-00"
scenario="${MOCK_AGY_SCENARIO:-complete}"
if [[ "$scenario" == "noconv" ]]; then
    echo "agy: not signed in" >&2
    exit 1
fi
if [[ $n -eq 1 && "$scenario" != "nostart" && "$scenario" != "resume" ]]; then
    mkdir -p "$loop"
    printf -- '---\ncurrent_round: 0\nsession_id: %s\n---\n' "$conv" > "$loop/state.md"
elif [[ -f "$loop/state.md" ]]; then
    case "$scenario" in
        complete|resume)
            round=$(( n - 1 ))
            printf -- '---\ncurrent_round: %s\nsession_id: %s\n---\n' "$round" "$conv" > "$loop/state.md"
            if [[ $n -ge ${MOCK_AGY_FINISH_AT:-3} ]]; then
                mv "$loop/state.md" "$loop/complete-state.md"
                [[ "$scenario" == "complete" ]] && printf '# Finalize Summary\n\nWritten by Gemini.\n' > "$loop/finalize-summary.md"
            fi ;;
        forever)
            printf -- '---\ncurrent_round: %s\nsession_id: %s\n---\n' "$n" "$conv" > "$loop/state.md" ;;
        cancel)
            mv "$loop/state.md" "$loop/cancel-state.md" ;;
        dirty)
            echo "edit $n" >> README.md
            if [[ $n -ge ${MOCK_AGY_FINISH_AT:-3} ]]; then mv "$loop/state.md" "$loop/complete-state.md"; fi ;;
        stall) : ;;
    esac
fi
printf '{"event":"init","conversation_id":"%s","init":{"model":"mock"}}\n' "$conv"
if [[ "$scenario" == "slow" ]]; then
    trap 'echo interrupted > "$dir/call-$n.signal"; exit 130' INT TERM
    sleep 30 &
    wait $!
fi
printf '{"event":"step_update","step":{}}\n'
printf '{"event":"result","result":{"conversation_id":"%s","status":"SUCCESS","response":"Gemini reply %s"}}\n' "$conv" "$n"
MOCK
chmod +x "$MOCK_AGY"

new_driver_project() {
    PROJ_F="$TEST_DIR/proj-driver-$1"
    init_test_git_repo "$PROJ_F"
    export MOCK_AGY_DIR="$TEST_DIR/mock-agy-$1"
    mkdir -p "$MOCK_AGY_DIR"
}
run_driver() {
    DRIVER_OUT="$(cd "$PROJ_F" && "$DRIVER" --agy "$MOCK_AGY" "$@" 2>"$MOCK_AGY_DIR/driver.stderr")"
    RC=$?
    DRIVER_ERR="$(cat "$MOCK_AGY_DIR/driver.stderr")"
    CALLS="$(cat "$MOCK_AGY_DIR/count" 2>/dev/null || echo 0)"
}

new_driver_project complete
MOCK_AGY_SCENARIO=complete run_driver --model gemini-test --log-dir "$TEST_DIR/f1-logs" docs/plan.md --max 5
assert_eq "F1 finished loop exits 0" "0" "$RC"
assert_eq "F1 three agy turns (start + 2 resumes)" "3" "$CALLS"
assert_eq "F1 prints Gemini's finalize summary" "$(printf '# Finalize Summary\n\nWritten by Gemini.')" "$DRIVER_OUT"
assert_contains "F1 start prompt uses the start skill" "humanize-start-rlcr-loop" "$(cat "$MOCK_AGY_DIR/call-1.prompt")"
assert_contains "F1 start prompt passes the setup arguments and --skip-quiz" "docs/plan.md --max 5 --skip-quiz" "$(cat "$MOCK_AGY_DIR/call-1.prompt")"
assert_contains "F1 start prompt says nobody is watching" "Nobody is watching" "$(cat "$MOCK_AGY_DIR/call-1.prompt")"
assert_not_contains "F1 start turn is a new conversation" "--conversation" "$(cat "$MOCK_AGY_DIR/call-1.args")"
assert_eq "F1 resume says continue" "continue" "$(cat "$MOCK_AGY_DIR/call-2.prompt")"
assert_contains "F1 resume uses the same conversation" "$(printf -- '--conversation\nmock-conv')" "$(cat "$MOCK_AGY_DIR/call-2.args")"
F1_SETTINGS="$(sed -n '/^--settings$/{n;p;}' "$MOCK_AGY_DIR/call-3.args")"
assert_eq "F1 approves agy's prompts" "always-proceed" "$(jq -r '.toolPermission' <<<"$F1_SETTINGS")"
assert_eq "F1 keeps agy's file tools in the workspace" "false" "$(jq -r '.allowNonWorkspaceAccess' <<<"$F1_SETTINGS")"
assert_eq "F1 never switches to paid credits" "false" "$(jq -r '.useG1Credits' <<<"$F1_SETTINGS")"
assert_contains "F1 forwards --model" "$(printf -- '--model\ngemini-test')" "$(cat "$MOCK_AGY_DIR/call-3.args")"
assert_contains "F1 stream-json output" "stream-json" "$(cat "$MOCK_AGY_DIR/call-1.args")"
assert_eq "F1 agy runs unattended in the project root" "unattended=1 cwd=$(cd "$PROJ_F" && pwd -P)" "$(cat "$MOCK_AGY_DIR/call-2.env")"
assert_contains "F1 driver reports the conversation" "mock-conv" "$DRIVER_ERR"
assert_eq "F1 agy output kept per turn" "yes" "$([[ -s "$TEST_DIR/f1-logs/turn-001.jsonl" && -s "$TEST_DIR/f1-logs/turn-003.jsonl" ]] && echo yes || echo no)"

mkdir -p "$PROJ_F/sub/dir"
rm -f "$MOCK_AGY_DIR"/count "$MOCK_AGY_DIR"/call-*
rm -rf "$PROJ_F/.humanize/rlcr"
OUT="$(cd "$PROJ_F/sub/dir" && MOCK_AGY_SCENARIO=complete MOCK_AGY_FINISH_AT=2 "$DRIVER" --agy "$MOCK_AGY" docs/plan.md 2>/dev/null)"; RC=$?
assert_eq "F1 started from a subfolder: exits 0" "0" "$RC"
assert_eq "F1 started from a subfolder: agy still runs in the project root" "unattended=1 cwd=$(cd "$PROJ_F" && pwd -P)" "$(cat "$MOCK_AGY_DIR/call-1.env")"

new_driver_project yolo
MOCK_AGY_SCENARIO=complete MOCK_AGY_FINISH_AT=2 run_driver docs/plan.md --yolo
assert_eq "F2 finished loop exits 0" "0" "$RC"
assert_not_contains "F2 --skip-quiz not added after --yolo" "--skip-quiz" "$(cat "$MOCK_AGY_DIR/call-1.prompt")"
assert_eq "F2 default log folder under .humanize/agy-runs" "yes" "$(ls "$PROJ_F"/.humanize/agy-runs/*/turn-001.jsonl >/dev/null 2>&1 && echo yes || echo no)"

new_driver_project stall
MOCK_AGY_SCENARIO=stall run_driver --stall-limit 2 docs/plan.md
assert_eq "F3 stalled loop: driver gives up with 2" "2" "$RC"
assert_eq "F3 stalled loop: start + 2 resumes" "3" "$CALLS"
assert_contains "F3 says how to resume" "--resume mock-conv" "$DRIVER_ERR"

new_driver_project forever
MOCK_AGY_SCENARIO=forever run_driver --max-resumes 2 docs/plan.md
assert_eq "F4 resume cap: driver gives up with 2" "2" "$RC"
assert_eq "F4 resume cap: start + 2 resumes" "3" "$CALLS"

new_driver_project nostart
MOCK_AGY_SCENARIO=nostart run_driver docs/plan.md
assert_eq "F5 loop never started exits 1" "1" "$RC"
assert_eq "F5 one agy turn only" "1" "$CALLS"
assert_eq "F5 prints Gemini's reply" "Gemini reply 1" "$DRIVER_OUT"

new_driver_project cancel
MOCK_AGY_SCENARIO=cancel run_driver docs/plan.md
assert_eq "F6 cancelled loop exits 1" "1" "$RC"
assert_contains "F6 names the end state" "cancel-state.md" "$DRIVER_ERR"

new_driver_project noconv
MOCK_AGY_SCENARIO=noconv run_driver docs/plan.md
assert_eq "F7 agy failure before a conversation exits 2" "2" "$RC"

new_driver_project resume
mkdir -p "$PROJ_F/.humanize/rlcr/2026-05-01_00-00-00"
printf -- '---\ncurrent_round: 4\nsession_id: conv-r\n---\n' > "$PROJ_F/.humanize/rlcr/2026-05-01_00-00-00/state.md"
MOCK_AGY_SCENARIO=resume MOCK_AGY_FINISH_AT=2 run_driver --resume conv-r
assert_eq "F8 --resume drives the existing loop to the end" "0" "$RC"
assert_eq "F8 without a finalize summary, prints Gemini's last reply" "Gemini reply 2" "$DRIVER_OUT"
assert_eq "F8 --resume: no start turn" "continue" "$(cat "$MOCK_AGY_DIR/call-1.prompt")"
assert_contains "F8 --resume uses that conversation" "$(printf -- '--conversation\nconv-r')" "$(cat "$MOCK_AGY_DIR/call-1.args")"
MOCK_AGY_SCENARIO=resume run_driver --resume conv-unknown
assert_eq "F8 --resume with an unknown conversation exits 1" "1" "$RC"

# git itself refuses to push during an unattended run.
new_driver_project push
git init -q --bare "$TEST_DIR/push-remote.git"
git -C "$PROJ_F" remote add origin "$TEST_DIR/push-remote.git"
MOCK_AGY_SCENARIO=complete MOCK_AGY_FINISH_AT=2 MOCK_AGY_TRY_PUSH=1 GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.quotepath GIT_CONFIG_VALUE_0=false run_driver docs/plan.md
assert_eq "F10 push from inside agy fails" "yes" "$([[ "$(cat "$MOCK_AGY_DIR/call-1.push")" != 0 ]] && echo yes || echo no)"
assert_contains "F10 git names the block" "humanize-unattended-run-blocks-git-push" "$(cat "$MOCK_AGY_DIR/call-1.push-out")"
assert_eq "F10 nothing reached the remote" "0" "$(git --git-dir="$TEST_DIR/push-remote.git" show-ref | wc -l | tr -d ' ')"
assert_contains "F10 existing git config from the environment is kept" "GIT_CONFIG_KEY_0=core.quotepath" "$(cat "$MOCK_AGY_DIR/call-1.gitenv")"
assert_contains "F10 the block is added after it" "GIT_CONFIG_COUNT=2" "$(cat "$MOCK_AGY_DIR/call-1.gitenv")"
new_driver_project push-allowed
git -C "$PROJ_F" remote add origin "$TEST_DIR/push-remote.git"
MOCK_AGY_SCENARIO=complete MOCK_AGY_FINISH_AT=2 MOCK_AGY_TRY_PUSH=1 run_driver docs/plan.md --push-every-round
assert_eq "F10 --push-every-round: push works" "0" "$(cat "$MOCK_AGY_DIR/call-1.push")"
assert_eq "F10 --push-every-round: no git config block" "" "$(cat "$MOCK_AGY_DIR/call-1.gitenv")"

# Edits to an already-changed file count as progress.
new_driver_project dirty
MOCK_AGY_SCENARIO=dirty MOCK_AGY_FINISH_AT=4 run_driver --stall-limit 2 docs/plan.md
assert_eq "F11 edits to a dirty file are progress, not a stall" "0" "$RC"
assert_eq "F11 all four turns ran" "4" "$CALLS"

# Stopping the driver during the first turn stops agy and says how to resume.
new_driver_project slow
(cd "$PROJ_F" && MOCK_AGY_SCENARIO=slow exec "$DRIVER" --agy "$MOCK_AGY" docs/plan.md > /dev/null 2> "$MOCK_AGY_DIR/driver.stderr") &
DRIVER_PID=$!
for _ in $(seq 1 50); do
    grep -q 'agy conversation: mock-conv' "$MOCK_AGY_DIR/driver.stderr" 2>/dev/null && break
    sleep 0.2
done
kill -TERM "$DRIVER_PID" 2>/dev/null
wait "$DRIVER_PID"; RC=$?
assert_eq "F12 stopped driver exits 130" "130" "$RC"
assert_contains "F12 conversation reported during the first turn" "agy conversation: mock-conv" "$(cat "$MOCK_AGY_DIR/driver.stderr")"
assert_contains "F12 says how to resume" "--resume mock-conv" "$(cat "$MOCK_AGY_DIR/driver.stderr")"
for _ in $(seq 1 50); do [[ -f "$MOCK_AGY_DIR/call-1.signal" ]] && break; sleep 0.2; done
assert_eq "F12 agy was stopped too" "interrupted" "$(cat "$MOCK_AGY_DIR/call-1.signal" 2>/dev/null)"

new_driver_project usage
run_driver
assert_eq "F9 no plan exits 64" "64" "$RC"
run_driver --resume conv-r docs/plan.md
assert_eq "F9 --resume with a plan exits 64" "64" "$RC"
run_driver --stall-limit zero docs/plan.md
assert_eq "F9 bad number exits 64" "64" "$RC"
assert_eq "F9 usage errors start no agy" "0" "$CALLS"
mkdir -p "$TEST_DIR/not-a-repo-f"
OUT="$(cd "$TEST_DIR/not-a-repo-f" && "$DRIVER" --agy "$MOCK_AGY" docs/plan.md 2>&1)"; RC=$?
assert_eq "F9 outside a git repository exits 64" "64" "$RC"
OUT="$("$DRIVER" --help)"; RC=$?
assert_eq "F9 --help exits 0" "0" "$RC"
assert_contains "F9 --help explains the safety checks" "git push" "$OUT"

print_test_summary "agy Plugin Tests"
