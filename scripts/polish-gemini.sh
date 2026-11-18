#!/usr/bin/env bash
#
# polish-gemini.sh - Readability-only polish of human-facing text with Gemini
#
# Sends a document to a Gemini model on OpenRouter with a fixed copy-editing
# contract and no tools, checks the reply with a deterministic fidelity guard,
# and delivers either the polished text or the exact original bytes.
#
# Usage:
#   polish-gemini.sh --input <file|-> [--output <file>]
#                    [--format markdown|text|segments|html] [--auto]
#                    [--model MODEL] [--effort xhigh|high|medium|low]
#                    [--timeout SECONDS] [--max-tokens N] [--max-bytes N]
#                    [--strict]
#
# Output:
#   stdout, or the --output file: the polished text or the original bytes
#   stderr: diagnostics prefixed "polish-gemini:", then exactly one final line
#     polish-gemini: outcome=<polished|unchanged|skipped|rejected|failed> reason=<code> delivered=<yes|no>
#
# Exit codes:
#   0    content delivered (polished text or original bytes)
#   3    original delivered because polishing was skipped, rejected or failed (--strict only)
#   1    usage error; nothing delivered
#   4    delivery failed; the destination is unchanged
#   130  interrupted by SIGINT
#   143  interrupted by SIGTERM
#
# This wrapper parses arguments and the merged humanize config, then hands off
# to scripts/lib/polish_gemini.py (Python 3 standard library). The API key is
# read inside Python from OPENROUTER_API_KEY or the configured key file; it is
# never passed on a command line.
#

# No "set -e": every failure path must still print the outcome line.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DEFAULT_MODEL="google/gemini-4-hydrogen"
DEFAULT_EFFORT="xhigh"
DEFAULT_TIMEOUT=900
DEFAULT_MAX_TOKENS=131072
DEFAULT_MAX_BYTES=262144
DEFAULT_BASE_URL="https://openrouter.ai/api/v1"

TEMP_FILES=()

# Diagnostics are always one line, and never look like the outcome line,
# whatever text (file names, config values, loader warnings) they carry.
diag() {
    local msg="$*"
    # Control characters, and the Unicode line separators U+0085, U+2028 and
    # U+2029 (as UTF-8 bytes), become spaces.
    msg="$(printf '%s' "$msg" | LC_ALL=C tr '\000-\037\177' ' ' |
        LC_ALL=C sed $'s/\xe2\x80[\xa8\xa9]/ /g; s/\xc2\x85/ /g')"
    if [[ "${#msg}" -gt 1000 ]]; then
        msg="${msg:0:1000}..."
    fi
    case "$msg" in
        outcome=*) msg="note: $msg" ;;
    esac
    printf 'polish-gemini: %s\n' "$msg" >&2
}

emit_outcome() {
    printf 'polish-gemini: outcome=%s reason=%s delivered=%s\n' "$1" "$2" "$3" >&2
}

cleanup_temps() {
    local f
    for f in ${TEMP_FILES[@]+"${TEMP_FILES[@]}"}; do
        rm -f "$f" 2>/dev/null
    done
    TEMP_FILES=()
}

# While the fallback copy is being delivered, a signal is recorded and handled
# once delivery has finished: the outcome line reports what was delivered and
# the exit code (130 or 143) reports the interruption.
IN_DELIVERY=false
PENDING_SIGNAL=""

SIGNALS_SEEN=0

on_signal() {
    if [[ "$IN_DELIVERY" == "true" ]]; then
        PENDING_SIGNAL="$1"
        SIGNALS_SEEN=$((SIGNALS_SEEN + 1))
        return 0
    fi
    trap - INT TERM
    cleanup_temps
    emit_outcome failed interrupted no
    exit "$1"
}

# finish_delivery OUTCOME REASON DELIVERED EXIT_CODE
# Signals stay deferred until the process exits, so a signal at any point in
# here still yields exactly one outcome line and exit code 130 or 143. The
# outcome describes what was delivered; the exit code reports the interruption.
finish_delivery() {
    cleanup_temps
    if [[ -n "$PENDING_SIGNAL" ]]; then
        diag "interrupted during delivery; delivery finished first"
    fi
    emit_outcome "$1" "$2" "$3"
    exit "${PENDING_SIGNAL:-$4}"
}
trap 'on_signal 130' INT
trap 'on_signal 143' TERM

# shielded CMD [ARGS...]: run one delivery step to completion.
# The step runs in the background with SIGINT and SIGTERM ignored, so a signal
# sent to the whole process group (for example Ctrl-C) cannot cut it short.
# Waiting with the wait builtin lets the trap record a signal sent to this
# shell alone; in the foreground, bash would drop a SIGINT that the child
# survived. wait returns 130 or 143 when a trapped signal interrupts it; the
# step itself cannot end that way because it ignores both signals.
shielded() {
    local pid status seen
    ( trap '' INT TERM; exec "$@" ) &
    pid=$!
    while :; do
        seen="$SIGNALS_SEEN"
        wait "$pid"
        status=$?
        if [[ "$SIGNALS_SEEN" != "$seen" ]] && (( status == 130 || status == 143 )); then
            continue
        fi
        return "$status"
    done
}

usage_error() {
    diag "$1"
    diag "Use --help for usage information"
    cleanup_temps
    emit_outcome failed usage_error no
    exit 1
}

show_help() {
    cat << 'HELP_EOF'
polish-gemini - Readability-only polish of human-facing text with Gemini

USAGE:
  polish-gemini.sh --input <file|-> [OPTIONS]

OPTIONS:
  --input <file|->     Source document, or - for stdin (required)
  --output <file>      Write the result to this file atomically (may equal --input).
                       Without it, the result goes to stdout.
  --format <name>      markdown, text, segments or html. Default: from the file
                       extension (.html/.htm -> html, .md -> markdown, else text).
  --auto               Automatic call site: skip when gemini_polish_enabled is false
                       or the config cannot be loaded.
  --model <id>         OpenRouter model ID (default: google/gemini-4-hydrogen)
  --effort <level>     Reasoning effort: xhigh, high, medium or low (default: xhigh)
  --timeout <seconds>  Overall deadline for the request (default: 900)
  --max-tokens <n>     Completion budget, reasoning included (default: 131072)
  --max-bytes <n>      Largest input to send (default: 262144)
  --strict             Exit 3 instead of 0 when the original had to be delivered
  -h, --help           Show this help

OUTPUT:
  The polished text, or the exact original bytes when polishing is skipped,
  rejected or fails. stderr ends with one line:
    polish-gemini: outcome=<polished|unchanged|skipped|rejected|failed> reason=<code> delivered=<yes|no>

EXIT CODES:
  0 delivered, 3 original delivered under --strict, 1 usage error,
  4 delivery failed, 130/143 interrupted.

API KEY:
  OPENROUTER_API_KEY, or the file named by the gemini_polish_api_key_file
  config key (a raw key or one OPENROUTER_API_KEY=value line, mode 600).

CONFIG KEYS:
  gemini_polish_enabled, gemini_polish_model, gemini_polish_reasoning_effort,
  gemini_polish_max_tokens, gemini_polish_timeout, gemini_polish_max_bytes,
  gemini_polish_api_key_file, gemini_polish_base_url
HELP_EOF
}

is_positive_int() {
    [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

is_effort() {
    case "$1" in
        xhigh|high|medium|low) return 0 ;;
    esac
    return 1
}

# ========================================
# Parse Arguments
# ========================================

INPUT=""
INPUT_SET=false
OUTPUT=""
FORMAT=""
AUTO=false
STRICT=false
CLI_MODEL=""
CLI_EFFORT=""
CLI_TIMEOUT=""
CLI_MAX_TOKENS=""
CLI_MAX_BYTES=""

require_value() {
    if [[ $2 -lt 2 ]]; then
        usage_error "$1 requires a value"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        --input)
            require_value "$1" "$#"
            INPUT="$2"
            INPUT_SET=true
            shift 2
            ;;
        --output)
            require_value "$1" "$#"
            [[ -n "$2" ]] || usage_error "--output requires a file path"
            OUTPUT="$2"
            shift 2
            ;;
        --format)
            require_value "$1" "$#"
            FORMAT="$2"
            shift 2
            ;;
        --auto)
            AUTO=true
            shift
            ;;
        --strict)
            STRICT=true
            shift
            ;;
        --model)
            require_value "$1" "$#"
            CLI_MODEL="$2"
            shift 2
            ;;
        --effort)
            require_value "$1" "$#"
            CLI_EFFORT="$2"
            shift 2
            ;;
        --timeout)
            require_value "$1" "$#"
            CLI_TIMEOUT="$2"
            shift 2
            ;;
        --max-tokens)
            require_value "$1" "$#"
            CLI_MAX_TOKENS="$2"
            shift 2
            ;;
        --max-bytes)
            require_value "$1" "$#"
            CLI_MAX_BYTES="$2"
            shift 2
            ;;
        *)
            usage_error "Unknown option: $1"
            ;;
    esac
done

if [[ "$INPUT_SET" != "true" || -z "$INPUT" ]]; then
    usage_error "--input is required (a file path, or - for stdin)"
fi
if [[ "$INPUT" != "-" ]]; then
    if [[ ! -f "$INPUT" ]]; then
        usage_error "Input file not found: $INPUT"
    fi
    if [[ ! -r "$INPUT" ]]; then
        usage_error "Input file is not readable: $INPUT"
    fi
fi
if [[ -n "$FORMAT" ]]; then
    case "$FORMAT" in
        markdown|text|segments|html) ;;
        *) usage_error "--format must be markdown, text, segments or html, got: $FORMAT" ;;
    esac
fi
if [[ -n "$CLI_EFFORT" ]] && ! is_effort "$CLI_EFFORT"; then
    usage_error "--effort must be xhigh, high, medium or low, got: $CLI_EFFORT"
fi
if [[ -n "$CLI_TIMEOUT" ]] && ! is_positive_int "$CLI_TIMEOUT"; then
    usage_error "--timeout must be a positive integer (seconds), got: $CLI_TIMEOUT"
fi
if [[ -n "$CLI_MAX_TOKENS" ]] && ! is_positive_int "$CLI_MAX_TOKENS"; then
    usage_error "--max-tokens must be a positive integer, got: $CLI_MAX_TOKENS"
fi
if [[ -n "$CLI_MAX_BYTES" ]] && ! is_positive_int "$CLI_MAX_BYTES"; then
    usage_error "--max-bytes must be a positive integer, got: $CLI_MAX_BYTES"
fi

# ========================================
# Project Root and Merged Config
# ========================================

# shellcheck source=../hooks/lib/project-root.sh
source "$PLUGIN_ROOT/hooks/lib/project-root.sh"
PROJECT_ROOT="$(resolve_project_root 2>/dev/null)" || PROJECT_ROOT=""

CONFIG_OK=false
MERGED_CONFIG=""
CONFIG_ERR_FILE="$(mktemp "${TMPDIR:-/tmp}/polish-gemini-config.XXXXXX" 2>/dev/null)" || CONFIG_ERR_FILE=""
if [[ -n "$CONFIG_ERR_FILE" ]]; then
    TEMP_FILES+=("$CONFIG_ERR_FILE")
fi
CONFIG_ERR_SINK="${CONFIG_ERR_FILE:-/dev/null}"

# config-loader.sh enables "set -e" when sourced; restore this script's mode after.
if source "$PLUGIN_ROOT/scripts/lib/config-loader.sh" 2>>"$CONFIG_ERR_SINK"; then
    set +e
    if MERGED_CONFIG="$(load_merged_config "$PLUGIN_ROOT" "${PROJECT_ROOT:-$PWD}" 2>>"$CONFIG_ERR_SINK")"; then
        CONFIG_OK=true
    fi
fi
set +e

if [[ -n "$CONFIG_ERR_FILE" && -s "$CONFIG_ERR_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -n "$line" ]] && diag "config: $line"
    done < "$CONFIG_ERR_FILE"
fi

config_value() {
    if [[ "$CONFIG_OK" != "true" ]]; then
        return 0
    fi
    get_config_value "$MERGED_CONFIG" "$1" 2>/dev/null || true
}

CFG_ENABLED="$(config_value gemini_polish_enabled)"
CFG_MODEL="$(config_value gemini_polish_model)"
CFG_EFFORT="$(config_value gemini_polish_reasoning_effort)"
CFG_MAX_TOKENS="$(config_value gemini_polish_max_tokens)"
CFG_TIMEOUT="$(config_value gemini_polish_timeout)"
CFG_MAX_BYTES="$(config_value gemini_polish_max_bytes)"
CFG_KEY_FILE="$(config_value gemini_polish_api_key_file)"
CFG_BASE_URL="$(config_value gemini_polish_base_url)"

if [[ "$CONFIG_OK" != "true" && "$AUTO" != "true" ]]; then
    diag "config could not be loaded; using built-in defaults"
fi

# Resolve one numeric setting: CLI value, then a valid config value, then default.
resolve_int() {
    local cli="$1" cfg="$2" default="$3" key="$4"
    if [[ -n "$cli" ]]; then
        printf '%s' "$cli"
    elif [[ -n "$cfg" ]]; then
        if is_positive_int "$cfg"; then
            printf '%s' "$cfg"
        else
            diag "ignoring invalid $key value in config: $cfg"
            printf '%s' "$default"
        fi
    else
        printf '%s' "$default"
    fi
}

MODEL="${CLI_MODEL:-${CFG_MODEL:-$DEFAULT_MODEL}}"
if [[ ! "$MODEL" =~ ^[A-Za-z0-9._:/-]+$ ]]; then
    usage_error "model ID contains invalid characters: $MODEL"
fi
if [[ "$MODEL" == *":online" ]]; then
    usage_error "web-search models (IDs ending in :online) are not allowed for polishing: $MODEL"
fi

if [[ -n "$CLI_EFFORT" ]]; then
    EFFORT="$CLI_EFFORT"
elif [[ -n "$CFG_EFFORT" ]]; then
    if is_effort "$CFG_EFFORT"; then
        EFFORT="$CFG_EFFORT"
    else
        diag "ignoring invalid gemini_polish_reasoning_effort in config: $CFG_EFFORT"
        EFFORT="$DEFAULT_EFFORT"
    fi
else
    EFFORT="$DEFAULT_EFFORT"
fi

TIMEOUT="$(resolve_int "$CLI_TIMEOUT" "$CFG_TIMEOUT" "$DEFAULT_TIMEOUT" gemini_polish_timeout)"
MAX_TOKENS="$(resolve_int "$CLI_MAX_TOKENS" "$CFG_MAX_TOKENS" "$DEFAULT_MAX_TOKENS" gemini_polish_max_tokens)"
MAX_BYTES="$(resolve_int "$CLI_MAX_BYTES" "$CFG_MAX_BYTES" "$DEFAULT_MAX_BYTES" gemini_polish_max_bytes)"

BASE_URL="${HUMANIZE_POLISH_BASE_URL:-${CFG_BASE_URL:-$DEFAULT_BASE_URL}}"
KEY_FILE="$CFG_KEY_FILE"

ENABLED=true
case "$CFG_ENABLED" in
    ""|true) ENABLED=true ;;
    false) ENABLED=false ;;
    *)
        diag "ignoring invalid gemini_polish_enabled in config: $CFG_ENABLED"
        ENABLED=true
        ;;
esac

SKIP_REASON=""
if [[ "$AUTO" == "true" ]]; then
    if [[ "$CONFIG_OK" != "true" ]]; then
        SKIP_REASON="config_error"
    elif [[ "$ENABLED" != "true" ]]; then
        SKIP_REASON="disabled"
    fi
fi

# ========================================
# Fallback Delivery (no usable Python)
# ========================================

file_mode() {
    stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1" 2>/dev/null
}

deliver_original() {
    local reason="$1"
    local src="$INPUT"
    local tmp_out="" mode=""

    if [[ "$INPUT" == "-" ]]; then
        src="$(mktemp "${TMPDIR:-/tmp}/polish-gemini-in.XXXXXX")" || {
            cleanup_temps
            emit_outcome failed delivery_error no
            exit 4
        }
        TEMP_FILES+=("$src")
        cat > "$src"
    fi

    # A signal that arrived before this point has already ended the run with
    # nothing delivered. From here on, signals wait until delivery is done.
    IN_DELIVERY=true
    if [[ -n "$OUTPUT" ]]; then
        if [[ "$INPUT" != "-" && -e "$OUTPUT" && "$OUTPUT" -ef "$INPUT" ]]; then
            :
        else
            if [[ -d "$OUTPUT" ]] || ! tmp_out="$(mktemp "$(dirname "$OUTPUT")/.polish-gemini-XXXXXX" 2>/dev/null)"; then
                diag "could not write $OUTPUT"
                finish_delivery failed delivery_error no 4
            fi
            TEMP_FILES+=("$tmp_out")
            if [[ -e "$OUTPUT" ]]; then
                mode="$(file_mode "$OUTPUT")"
            else
                mode="$(printf '%o' $(( 0666 & ~0$(umask) )))"
            fi
            if ! shielded cat "$src" > "$tmp_out" || ! shielded chmod "${mode:-644}" "$tmp_out" \
                || ! shielded mv -f "$tmp_out" "$OUTPUT"; then
                diag "could not write $OUTPUT"
                finish_delivery failed delivery_error no 4
            fi
        fi
    else
        if ! shielded cat "$src"; then
            finish_delivery failed delivery_error no 4
        fi
    fi

    if [[ "$STRICT" == "true" ]]; then
        finish_delivery skipped "$reason" yes 3
    fi
    finish_delivery skipped "$reason" yes 0
}

PYTHON_BIN="${HUMANIZE_POLISH_PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 || \
   ! "$PYTHON_BIN" -I -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' >/dev/null 2>&1; then
    if [[ -z "$SKIP_REASON" ]]; then
        diag "python3 (3.7 or newer) is required for polishing; delivering the original"
    fi
    deliver_original "${SKIP_REASON:-missing_dependency}"
fi

# ========================================
# Hand Off to the Python Helper
# ========================================

PY_ARGS=(
    --input "$INPUT"
    --model "$MODEL"
    --effort "$EFFORT"
    --timeout "$TIMEOUT"
    --max-tokens "$MAX_TOKENS"
    --max-bytes "$MAX_BYTES"
    --base-url "$BASE_URL"
    --template-dir "$PLUGIN_ROOT/prompt-template/gemini"
)
[[ -n "$OUTPUT" ]] && PY_ARGS+=(--output "$OUTPUT")
[[ -n "$FORMAT" ]] && PY_ARGS+=(--format "$FORMAT")
[[ -n "$KEY_FILE" ]] && PY_ARGS+=(--api-key-file "$KEY_FILE")
[[ -n "$PROJECT_ROOT" ]] && PY_ARGS+=(--project-root "$PROJECT_ROOT")
[[ -n "$SKIP_REASON" ]] && PY_ARGS+=(--skip-reason "$SKIP_REASON")
[[ -n "${HUMANIZE_POLISH_BLOCK_RATIO:-}" ]] && PY_ARGS+=(--block-ratio "$HUMANIZE_POLISH_BLOCK_RATIO")
[[ -n "${HUMANIZE_POLISH_DOC_RATIO:-}" ]] && PY_ARGS+=(--doc-ratio "$HUMANIZE_POLISH_DOC_RATIO")
[[ "$STRICT" == "true" ]] && PY_ARGS+=(--strict)

cleanup_temps
trap - INT TERM
exec "$PYTHON_BIN" -I -B "$SCRIPT_DIR/lib/polish_gemini.py" "${PY_ARGS[@]}"
