#!/usr/bin/env bash
#
# Read-only Claude reviewer for the RLCR loop.
#
# Sourced by loop-codex-stop-hook.sh when rlcr_verifier or rlcr_reviewer is
# "claude". The nested `claude -p` run can only read:
#   - the only built-in tools loaded are Read, Grep and Glob (--tools), so no
#     shell, no file writes, no web, no subagents. Permission rules the user
#     has granted elsewhere (for example "allow Bash") cannot add a tool that
#     is not loaded;
#   - hooks are disabled, so the nested run cannot re-enter Humanize hooks;
#   - MCP servers, skills and slash commands are disabled;
#   - no session is saved to disk.
# Anything the reviewer would otherwise get from git (the diff, the commit
# list) is written to a file by the stop hook for it to Read.
#
# Required globals: PROJECT_ROOT. Optional: CLAUDE_REVIEW_MODEL.
#

CLAUDE_REVIEW_TOOLS="Read,Grep,Glob"

CLAUDE_REVIEW_ALLOWED_TOOLS=(
    "Read"
    "Grep"
    "Glob"
)

# Also denied explicitly, in case a future CLI loads extra tools by default.
CLAUDE_REVIEW_DISALLOWED_TOOLS=(
    "Bash"
    "Write"
    "Edit"
    "MultiEdit"
    "NotebookEdit"
    "WebFetch"
    "WebSearch"
    "Task"
)

# Build CLAUDE_REVIEW_ARGS for a read-only `claude -p` run.
# The prompt is passed on stdin.
build_claude_review_args() {
    CLAUDE_REVIEW_ARGS=(
        -p
        --output-format text
        --no-session-persistence
        --strict-mcp-config
        --disable-slash-commands
        --permission-mode default
        --settings '{"disableAllHooks":true}'
        --tools "$CLAUDE_REVIEW_TOOLS"
        --allowedTools "${CLAUDE_REVIEW_ALLOWED_TOOLS[@]}"
        --disallowedTools "${CLAUDE_REVIEW_DISALLOWED_TOOLS[@]}"
    )
    if [[ -n "${CLAUDE_REVIEW_MODEL:-}" ]]; then
        CLAUDE_REVIEW_ARGS+=(--model "$CLAUDE_REVIEW_MODEL")
    fi
}

# Describe the command for the debug .cmd files.
describe_claude_review_command() {
    build_claude_review_args
    printf 'claude'
    printf ' %q' "${CLAUDE_REVIEW_ARGS[@]}"
    printf ' < <prompt>\n'
}

# Run the read-only reviewer.
# Arguments: $1=timeout seconds, $2=stdout file, $3=stderr file. Prompt on stdin.
# Returns the claude exit code (124 on timeout).
run_claude_reviewer() {
    local timeout_secs="$1"
    local stdout_file="$2"
    local stderr_file="$3"

    build_claude_review_args

    # CLAUDECODE marks a running Claude Code session; the CLI refuses to start
    # nested sessions while it is set. CLAUDE_PROJECT_DIR belongs to the outer
    # host and must not leak into the reviewer. The subshell keeps the unset
    # local to this call.
    (
        unset CLAUDECODE CLAUDE_PROJECT_DIR CLAUDE_CODE_ENTRYPOINT
        cd "$PROJECT_ROOT" && run_with_timeout "$timeout_secs" claude "${CLAUDE_REVIEW_ARGS[@]}"
    ) > "$stdout_file" 2> "$stderr_file"
}

# Write what the code reviewer needs from git into one file it can Read:
# the commit list, the uncommitted status, a file summary and the full diff.
# Arguments: $1=review base (commit or branch), $2=output file.
write_claude_review_diff() {
    local review_base="$1"
    local output_file="$2"
    {
        echo "# Changes Under Review"
        echo ""
        echo "Review base: $review_base"
        echo ""
        echo "## Commits (git log --oneline $review_base..HEAD)"
        echo ""
        echo '```text'
        git -C "$PROJECT_ROOT" log --oneline "$review_base..HEAD" 2>&1 || true
        echo '```'
        echo ""
        echo "## Uncommitted changes (git status --porcelain)"
        echo ""
        echo '```text'
        git -C "$PROJECT_ROOT" status --porcelain 2>&1 || true
        echo '```'
        echo ""
        echo "## Files changed (git diff --stat $review_base...HEAD)"
        echo ""
        echo '```text'
        git -C "$PROJECT_ROOT" diff --stat "$review_base...HEAD" 2>&1 || true
        echo '```'
        echo ""
        echo "## Full diff (git diff $review_base...HEAD)"
        echo ""
        echo '```diff'
        git -C "$PROJECT_ROOT" diff "$review_base...HEAD" 2>&1 || true
        echo '```'
    } > "$output_file"
}

# Fail fast when a configured reviewer CLI is missing.
# Arguments: provider names to check (codex and/or claude).
# Prints the missing binary name and returns 1 when one is missing.
find_missing_reviewer_cli() {
    local provider
    for provider in "$@"; do
        if ! command -v "$provider" >/dev/null 2>&1; then
            printf '%s' "$provider"
            return 1
        fi
    done
    return 0
}
