#!/usr/bin/env bash
#
# Read-only Claude reviewer for the RLCR loop.
#
# Sourced by loop-codex-stop-hook.sh when rlcr_verifier or rlcr_reviewer is
# "claude". The nested `claude -p` run can read files and run read-only git
# commands, and nothing else:
#   - built-in tools limited to Read, Grep, Glob and Bash;
#   - Bash limited to read-only git subcommands through --allowedTools (any
#     other command is denied, because print mode cannot prompt);
#   - Write, Edit, NotebookEdit, WebFetch and WebSearch explicitly denied;
#   - hooks disabled, so the nested run cannot re-enter Humanize hooks;
#   - MCP servers, skills and slash commands disabled;
#   - no session saved to disk.
#
# Required globals: PROJECT_ROOT. Optional: CLAUDE_REVIEW_MODEL.
#

# Bash patterns the reviewer may run without a prompt.
CLAUDE_REVIEW_ALLOWED_TOOLS=(
    "Read"
    "Grep"
    "Glob"
    "Bash(git diff:*)"
    "Bash(git log:*)"
    "Bash(git show:*)"
    "Bash(git status:*)"
    "Bash(git rev-parse:*)"
    "Bash(git merge-base:*)"
    "Bash(git ls-files:*)"
    "Bash(git blame:*)"
)

CLAUDE_REVIEW_DISALLOWED_TOOLS=(
    "Write"
    "Edit"
    "NotebookEdit"
    "WebFetch"
    "WebSearch"
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
        --tools "Read,Grep,Glob,Bash"
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
    # host and must not leak into the reviewer.
    # The subshell keeps the unset local to this call.
    (
        unset CLAUDECODE CLAUDE_PROJECT_DIR CLAUDE_CODE_ENTRYPOINT
        cd "$PROJECT_ROOT" && run_with_timeout "$timeout_secs" claude "${CLAUDE_REVIEW_ARGS[@]}"
    ) > "$stdout_file" 2> "$stderr_file"
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
