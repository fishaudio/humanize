#!/usr/bin/env bash
#
# polish-gemini.sh - Readability-only polish of human-facing text with Gemini
#
# Sends a document to a Gemini model with a fixed copy-editing contract, checks
# the reply with a deterministic fidelity guard, and delivers either the
# polished text or the exact original bytes. The default backend is agy (the
# Antigravity CLI on the signed-in Gemini subscription, run with every tool
# refused); OpenRouter (pay per call, no tools) is the other backend.
#
# Usage:
#   polish-gemini.sh --input <file|-> [--output <file>]
#                    [--format markdown|text|segments|html] [--auto]
#                    [--backend agy|openrouter]
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
# to scripts/lib/polish_gemini.py (Python 3 standard library). The OpenRouter
# API key is read inside Python from OPENROUTER_API_KEY or the configured key
# file; it is never passed on a command line and never reaches agy.
#

# No "set -e": every failure path must still print the outcome line.
set -uo pipefail

# Every line this script writes to stderr goes through diag or emit_outcome,
# which write to file descriptor 9, a copy of the caller's stderr. Anything
# else on stderr (a utility's error message, a job status line from bash) goes
# to /dev/null, so it can neither break the one-line format nor fake an
# outcome line. The Python helper gets the caller's stderr back before exec.
if ! exec 9>&2; then
    exec 9>/dev/null
fi
exec 2>/dev/null
OUT_FD=9
# The caller's umask, read once, for files created later.
ORIG_UMASK="$(umask)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DEFAULT_BACKEND="agy"
DEFAULT_AGY_MODEL="gemini-4-neon"
DEFAULT_MODEL="google/gemini-4-neon"
DEFAULT_EFFORT="medium"
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
    printf 'polish-gemini: %s\n' "$msg" >&"$OUT_FD"
}

OUTCOME_EMITTED=false

# emit_outcome OUTCOME REASON DELIVERED: print the one outcome line.
# From here on the run is ending, so a signal is only recorded (see on_signal)
# and can neither print a second outcome line nor cut the exit short; callers
# exit with "${PENDING_SIGNAL:-CODE}".
emit_outcome() {
    IN_DELIVERY=true
    if [[ "$OUTCOME_EMITTED" == "true" ]]; then
        return 0
    fi
    printf 'polish-gemini: outcome=%s reason=%s delivered=%s\n' "$1" "$2" "$3" >&"$OUT_FD"
    OUTCOME_EMITTED=true
}

# cleanup_temps: remove the registered temporary files. Signals are recorded
# while it runs and each removal runs to completion (see shielded); a removal
# that fails is tried again, and a path that still exists afterwards stays
# registered and is reported on stderr (before the outcome line, which always
# comes after cleanup). A signal recorded here is honored right after, unless
# delivery is already under way.
cleanup_temps() {
    local f attempt deferred="$IN_DELIVERY"
    local left=()
    IN_DELIVERY=true
    for f in ${TEMP_FILES[@]+"${TEMP_FILES[@]}"}; do
        for attempt in 1 2 3; do
            shielded rm -f "$f"
            if [[ ! -e "$f" && ! -L "$f" ]]; then
                break
            fi
        done
        if [[ -e "$f" || -L "$f" ]]; then
            left+=("$f")
            diag "could not remove the temporary file $f"
        fi
    done
    TEMP_FILES=(${left[@]+"${left[@]}"})
    resume_signals "$deferred"
}

# resume_signals SAVED: end a stretch in which signals were only recorded by
# restoring IN_DELIVERY to SAVED. A signal recorded meanwhile is honored now,
# unless delivery was already under way.
resume_signals() {
    IN_DELIVERY="$1"
    if [[ "$1" != "true" && -n "$PENDING_SIGNAL" ]]; then
        on_signal "$PENDING_SIGNAL"
    fi
}

# While the fallback copy is being delivered, and once the outcome line is
# being printed, a signal is recorded and handled at exit: the outcome line
# reports what was delivered and the exit code (130 or 143) reports the
# interruption.
IN_DELIVERY=false
PENDING_SIGNAL=""

SIGNALS_SEEN=0

on_signal() {
    if [[ "$IN_DELIVERY" == "true" ]]; then
        PENDING_SIGNAL="$1"
        SIGNALS_SEEN=$((SIGNALS_SEEN + 1))
        return 0
    fi
    # A second signal from here on is only recorded, so the outcome line below
    # is always printed.
    IN_DELIVERY=true
    cleanup_temps
    emit_outcome failed interrupted no
    exit "$1"
}

# finish_delivery OUTCOME REASON DELIVERED EXIT_CODE
# Signals stay deferred until the process exits, so a signal at any point in
# here still yields exactly one outcome line and exit code 130 or 143. The
# outcome describes what was delivered; the exit code reports the interruption.
# Early exits before delivery use it too; no signal can be pending there,
# because cleanup_temps honors any recorded signal first.
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
# survived.
#
# wait returns 130 or 143 when a trapped signal interrupts it; waiting again
# then gives the step's own status (or 127 once that status was collected).
# The step reports a command's own exit status 130 or 143 as 1, so a step
# that ends with 130 or 143 was signalled in the moment before it could ignore
# the signal: it had not started the command yet and is run again. A command
# that ran is never run twice.
shielded() {
    local pid status again seen attempt=0
    while :; do
        ( trap '' INT TERM
          "$@"
          rc=$?
          if (( rc == 130 || rc == 143 )); then
              rc=1
          fi
          exit "$rc" ) &
        pid=$!
        seen="$SIGNALS_SEEN"
        wait "$pid"
        status=$?
        while [[ "$SIGNALS_SEEN" != "$seen" ]] && (( status == 130 || status == 143 )); do
            seen="$SIGNALS_SEEN"
            wait "$pid" 2>/dev/null
            again=$?
            if (( again == 127 )); then
                break
            fi
            status=$again
        done
        if (( (status == 130 || status == 143) && attempt < 3 )); then
            attempt=$((attempt + 1))
            continue
        fi
        return "$status"
    done
}

# make_temp DIR PREFIX: create a new empty file, readable only by the user,
# with a unique name in DIR, register it for cleanup, and set TEMP_PATH.
# The shell creates the file itself (noclobber, so an existing name is never
# reused), with no child process that a signal could stop between creating
# the file and reporting its name. Signals are only recorded until the path
# is registered, so an interruption cannot leave the file behind; a signal
# recorded here is honored right after, unless delivery is already under way.
# Returns 1 when no file can be created in DIR.
make_temp() {
    local dir="$1" prefix="$2" name attempt rc deferred="$IN_DELIVERY"
    TEMP_PATH=""
    IN_DELIVERY=true
    for attempt in 1 2 3 4 5 6 7 8; do
        name="$dir/$prefix$$.$RANDOM$RANDOM"
        if [[ -e "$name" || -L "$name" ]]; then
            continue
        fi
        umask 077
        set -C
        { : > "$name"; } 2>/dev/null
        rc=$?
        set +C
        umask "$ORIG_UMASK"
        if (( rc == 0 )) && [[ -f "$name" && ! -L "$name" ]]; then
            TEMP_FILES+=("$name")
            TEMP_PATH="$name"
            break
        fi
        if [[ ! -e "$name" && ! -L "$name" ]]; then
            break
        fi
    done
    resume_signals "$deferred"
    [[ -n "$TEMP_PATH" ]]
}

usage_error() {
    diag "$1"
    diag "Use --help for usage information"
    cleanup_temps
    emit_outcome failed usage_error no
    exit "${PENDING_SIGNAL:-1}"
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
  --backend <name>     agy (default: the Antigravity CLI on your signed-in Gemini
                       subscription) or openrouter (pay per call, needs an API key)
  --model <id>         Model of the selected backend: an agy model name
                       (default: gemini-4-neon) or an OpenRouter model ID
                       (default: google/gemini-4-neon)
  --effort <level>     Reasoning effort: xhigh, high, medium or low (default: medium)
  --timeout <seconds>  Overall deadline for the request (default: 900)
  --max-tokens <n>     OpenRouter completion budget, reasoning included (default: 131072)
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

BACKENDS:
  agy needs the agy command (found on PATH or in ~/.local/bin, or set
  gemini_polish_agy_bin) signed in with the account that has your Gemini
  subscription. It runs from an empty temporary folder with every tool refused,
  and gets the document on standard input. When agy is missing, signed out, out
  of quota or fails, the original is kept; set
  gemini_polish_fallback_to_openrouter to true to try OpenRouter instead.

  openrouter needs OPENROUTER_API_KEY, or the file named by the
  gemini_polish_api_key_file config key (a raw key or one
  OPENROUTER_API_KEY=value line, mode 600).

CONFIG KEYS:
  gemini_polish_enabled, gemini_polish_backend, gemini_polish_agy_model,
  gemini_polish_agy_bin, gemini_polish_fallback_to_openrouter,
  gemini_polish_model, gemini_polish_reasoning_effort, gemini_polish_max_tokens,
  gemini_polish_timeout, gemini_polish_max_bytes, gemini_polish_api_key_file,
  gemini_polish_base_url
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

is_backend() {
    case "$1" in
        agy|openrouter) return 0 ;;
    esac
    return 1
}

# ========================================
# Parse Arguments
# ========================================

INPUT=""
OUTPUT=""
FORMAT=""
AUTO=false
STRICT=false
CLI_BACKEND=""
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
        --backend)
            require_value "$1" "$#"
            CLI_BACKEND="$2"
            shift 2
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

if [[ -z "$INPUT" ]]; then
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
if [[ -n "$CLI_BACKEND" ]] && ! is_backend "$CLI_BACKEND"; then
    usage_error "--backend must be agy or openrouter, got: $CLI_BACKEND"
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
CONFIG_ERR_FILE=""
if make_temp "${TMPDIR:-/tmp}" "polish-gemini-config."; then
    CONFIG_ERR_FILE="$TEMP_PATH"
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
CFG_BACKEND="$(config_value gemini_polish_backend)"
CFG_AGY_MODEL="$(config_value gemini_polish_agy_model)"
CFG_AGY_BIN="$(config_value gemini_polish_agy_bin)"
CFG_FALLBACK="$(config_value gemini_polish_fallback_to_openrouter)"

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

# Backend: --backend, then HUMANIZE_POLISH_BACKEND, then a valid config value.
if [[ -n "$CLI_BACKEND" ]]; then
    BACKEND="$CLI_BACKEND"
elif [[ -n "${HUMANIZE_POLISH_BACKEND:-}" ]]; then
    if is_backend "$HUMANIZE_POLISH_BACKEND"; then
        BACKEND="$HUMANIZE_POLISH_BACKEND"
    else
        diag "ignoring invalid HUMANIZE_POLISH_BACKEND: $HUMANIZE_POLISH_BACKEND"
        BACKEND="$DEFAULT_BACKEND"
    fi
elif [[ -n "$CFG_BACKEND" ]]; then
    if is_backend "$CFG_BACKEND"; then
        BACKEND="$CFG_BACKEND"
    else
        diag "ignoring invalid gemini_polish_backend in config: $CFG_BACKEND"
        BACKEND="$DEFAULT_BACKEND"
    fi
else
    BACKEND="$DEFAULT_BACKEND"
fi

# --model names the model of the selected backend.
OR_CLI_MODEL=""
AGY_CLI_MODEL=""
if [[ "$BACKEND" == "agy" ]]; then
    AGY_CLI_MODEL="$CLI_MODEL"
else
    OR_CLI_MODEL="$CLI_MODEL"
fi

if [[ -n "$AGY_CLI_MODEL" ]]; then
    if [[ ! "$AGY_CLI_MODEL" =~ ^[A-Za-z0-9._-]+$ ]]; then
        usage_error "agy model names use letters, digits, dot, underscore and hyphen, got: $AGY_CLI_MODEL"
    fi
    AGY_MODEL="$AGY_CLI_MODEL"
elif [[ -n "$CFG_AGY_MODEL" ]]; then
    if [[ "$CFG_AGY_MODEL" =~ ^[A-Za-z0-9._-]+$ ]]; then
        AGY_MODEL="$CFG_AGY_MODEL"
    else
        diag "ignoring invalid gemini_polish_agy_model in config: $CFG_AGY_MODEL"
        AGY_MODEL="$DEFAULT_AGY_MODEL"
    fi
else
    AGY_MODEL="$DEFAULT_AGY_MODEL"
fi

AGY_BIN="${HUMANIZE_POLISH_AGY_BIN:-$CFG_AGY_BIN}"

case "$CFG_FALLBACK" in
    ""|false) FALLBACK=false ;;
    true) FALLBACK=true ;;
    *)
        diag "ignoring invalid gemini_polish_fallback_to_openrouter in config: $CFG_FALLBACK"
        FALLBACK=false
        ;;
esac

MODEL="${OR_CLI_MODEL:-${CFG_MODEL:-$DEFAULT_MODEL}}"
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
    local tmp_out="" mode="" same_file=false out_dir

    if [[ "$INPUT" == "-" ]]; then
        if ! make_temp "${TMPDIR:-/tmp}" "polish-gemini-in."; then
            diag "could not create a temporary file for standard input"
            finish_delivery failed delivery_error no 4
        fi
        src="$TEMP_PATH"
        if ! cat > "$src"; then
            diag "could not copy standard input to a temporary file"
            finish_delivery failed delivery_error no 4
        fi
    fi

    # The mode of the result is settled before delivery starts. A signal that
    # cuts this lookup short ends the run here, with nothing delivered, so a
    # partial lookup is never used.
    if [[ -n "$OUTPUT" ]]; then
        if [[ "$INPUT" != "-" && -e "$OUTPUT" && "$OUTPUT" -ef "$INPUT" ]]; then
            same_file=true
        elif [[ -e "$OUTPUT" ]]; then
            mode="$(file_mode "$OUTPUT")"
        else
            mode="$(printf '%o' $(( 0666 & ~0$ORIG_UMASK )))"
        fi
        if [[ "$same_file" != "true" ]] && ! [[ "$mode" =~ ^[0-7]{3,4}$ ]]; then
            diag "could not read the file mode for $OUTPUT"
            finish_delivery failed delivery_error no 4
        fi
    fi

    # A signal that arrived before this point has already ended the run with
    # nothing delivered. From here on, signals wait until delivery is done.
    IN_DELIVERY=true
    if [[ -n "$OUTPUT" && "$same_file" != "true" ]]; then
        out_dir="${OUTPUT%/*}"
        if [[ "$out_dir" == "$OUTPUT" ]]; then
            out_dir="."
        elif [[ -z "$out_dir" ]]; then
            out_dir="/"
        fi
        if [[ -d "$OUTPUT" ]] || ! make_temp "$out_dir" ".polish-gemini-"; then
            diag "could not write $OUTPUT"
            finish_delivery failed delivery_error no 4
        fi
        tmp_out="$TEMP_PATH"
        if ! shielded cat "$src" > "$tmp_out" || ! shielded chmod "$mode" "$tmp_out"; then
            diag "could not write $OUTPUT"
            finish_delivery failed delivery_error no 4
        fi
        if ! shielded mv -f "$tmp_out" "$OUTPUT"; then
            # mv can fail after the rename itself succeeded (for example when
            # it is killed right after). The temporary file is gone and the
            # destination holds the original only when the rename happened.
            if [[ -e "$tmp_out" ]] || ! shielded cmp -s "$src" "$OUTPUT"; then
                diag "could not write $OUTPUT"
                finish_delivery failed delivery_error no 4
            fi
        fi
    elif [[ -z "$OUTPUT" ]]; then
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
    --backend "$BACKEND"
    --agy-model "$AGY_MODEL"
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
[[ -n "$AGY_BIN" ]] && PY_ARGS+=(--agy-bin "$AGY_BIN")
[[ "$FALLBACK" == "true" ]] && PY_ARGS+=(--fallback-openrouter)

cleanup_temps
if [[ ! -r "$SCRIPT_DIR/lib/polish_gemini.py" || ! -r "$SCRIPT_DIR/lib/polish_guard.py" ]]; then
    diag "the polish helper is missing; delivering the original"
    deliver_original "${SKIP_REASON:-missing_dependency}"
fi
# The signals this shell handles; a signal ignored when the run started has
# no trap and stays ignored.
HANDOFF_SIGNALS=""
[[ -n "$(trap -p INT)" ]] && HANDOFF_SIGNALS="INT"
[[ -n "$(trap -p TERM)" ]] && HANDOFF_SIGNALS="${HANDOFF_SIGNALS:+$HANDOFF_SIGNALS,}TERM"

# ----------------------------------------
# Supervised start
# ----------------------------------------
# This shell stays the runner's process and keeps handling SIGINT and SIGTERM
# while the helper starts. The helper installs its own handlers, reports that
# it is ready by writing one byte to a pipe, and waits for SIGUSR1 (the
# release) before it reads any input. A signal that reaches this shell before
# then is recorded; at readiness it is passed on to the helper, which ends the
# run as interrupted with nothing delivered. After the release, signals are
# passed on and the helper owns the one outcome line; this shell exits with
# its status. When the helper ends before it is ready (the pipe reaches end
# of file), this shell finishes the run: as interrupted when a signal came, or
# by delivering the original when the helper could not start.
#
# Readiness comes through a pipe rather than a signal: in bash 3.2 a trapped
# signal other than SIGINT that interrupts the wait builtin leaves SIGINT
# handled only inside wait, so a SIGINT that came while this shell acted on a
# readiness signal was lost. The read builtin runs the traps as signals
# arrive and goes on reading (newer bash versions end the read with a status
# above 128 instead; it is then read again).
HELPER_PID=""
HELPER_READY=false
HELPER_PENDING=""
HELPER_PENDING_NAME=""
HELPER_FORWARDED=""
HELPER_TRAPS=0
HELPER_STATUS=0
HELPER_TOKEN=""

# helper_signal CODE NAME: a SIGINT or SIGTERM while the helper runs.
helper_signal() {
    HELPER_TRAPS=$((HELPER_TRAPS + 1))
    if [[ "$HELPER_READY" == "true" ]]; then
        HELPER_FORWARDED="${HELPER_FORWARDED:-$1}"
        kill -"$2" "$HELPER_PID" 2>/dev/null
    elif [[ -z "$HELPER_PENDING" ]]; then
        HELPER_PENDING="$1"
        HELPER_PENDING_NAME="$2"
    fi
}

# wait_helper: wait until the helper ends and set HELPER_STATUS. A trap that
# runs while this shell waits makes wait return early with a status above
# 128; waiting again gives the helper's own status, or 127 when the first
# wait had already collected it.
wait_helper() {
    local seen again
    seen="$HELPER_TRAPS"
    wait "$HELPER_PID"
    HELPER_STATUS=$?
    while [[ "$HELPER_TRAPS" != "$seen" ]]; do
        seen="$HELPER_TRAPS"
        wait "$HELPER_PID"
        again=$?
        if (( again == 127 )); then
            break
        fi
        HELPER_STATUS=$again
    done
}

# open_ready_pipe: make a named pipe, open it on fd 6 (read only) and fd 7
# (read and write, so neither open waits for the other side), and remove the
# name again; the open descriptors keep the pipe. As in make_temp, signals
# are only recorded while the name exists, so an interruption cannot leave it
# behind; a signal recorded here is honored right after. Returns 1 when no
# pipe can be made.
open_ready_pipe() {
    local dir name attempt deferred="$IN_DELIVERY" opened=1
    IN_DELIVERY=true
    for dir in "${TMPDIR:-}" /tmp; do
        if [[ -z "$dir" || ! -d "$dir" ]]; then
            continue
        fi
        for attempt in 1 2 3 4; do
            name="${dir%/}/polish-gemini-ready.$$.$RANDOM$RANDOM"
            if [[ -e "$name" || -L "$name" ]]; then
                continue
            fi
            if ! shielded mkfifo -m 600 "$name"; then
                # mkfifo creates nothing when it fails; a name that exists now
                # belongs to someone else.
                continue
            fi
            TEMP_FILES+=("$name")
            # The name can be replaced between any check and an open (in a
            # directory others may write to), so the open descriptors are
            # checked instead: both must be the same named pipe, owned by
            # this user. Nothing is ever written through fd 7 by this shell,
            # and the helper writes to it only after these checks passed.
            if [[ -p "$name" && ! -L "$name" ]] && { exec 7<>"$name"; } 2>/dev/null; then
                if [[ -p /dev/fd/7 && -O /dev/fd/7 ]] && { exec 6<"$name"; } 2>/dev/null; then
                    if [[ /dev/fd/6 -ef /dev/fd/7 ]]; then
                        opened=0
                    else
                        exec 6<&-
                    fi
                fi
                if (( opened != 0 )); then
                    exec 7>&-
                fi
            fi
            cleanup_temps
            if (( opened == 0 )); then
                break 2
            fi
        done
    done
    resume_signals "$deferred"
    return "$opened"
}

# Standard error stays on /dev/null for the helper until it is released, so
# a failed start prints nothing raw; it then takes the caller's stderr from
# fd 9 (HUMANIZE_POLISH_STDERR_FD). Standard input is passed on explicitly,
# as an asynchronous command would otherwise read /dev/null.
export HUMANIZE_POLISH_STDERR_FD="$OUT_FD"
export HUMANIZE_POLISH_SIGNALS="$HANDOFF_SIGNALS"
if open_ready_pipe; then
    trap 'helper_signal 130 INT' INT
    trap 'helper_signal 143 TERM' TERM
    export HUMANIZE_POLISH_SUPERVISOR="$$:7:USR1"
    "$PYTHON_BIN" -I -B "$SCRIPT_DIR/lib/polish_gemini.py" "${PY_ARGS[@]}" 6<&- <&0 &
    HELPER_PID=$!
    # Only the helper holds the write end now, so the pipe reaches end of
    # file when the helper ends.
    exec 7>&-
    unset HUMANIZE_POLISH_STDERR_FD HUMANIZE_POLISH_SIGNALS HUMANIZE_POLISH_SUPERVISOR
    while :; do
        HELPER_TOKEN=""
        read -r -n 1 HELPER_TOKEN <&6
        if (( $? <= 128 )); then
            break
        fi
    done
    exec 6<&-
    if [[ "$HELPER_TOKEN" == "R" ]]; then
        # A signal from here on is passed on at once; one recorded before is
        # passed on now. The release comes after it, so the helper has
        # recorded that signal before it goes on.
        HELPER_READY=true
        if [[ -n "$HELPER_PENDING_NAME" ]]; then
            kill -"$HELPER_PENDING_NAME" "$HELPER_PID" 2>/dev/null
        fi
        kill -USR1 "$HELPER_PID" 2>/dev/null
    fi
    wait_helper
    if [[ "$HELPER_READY" == "true" ]]; then
        # A signal passed on after the helper had already finished still
        # marks the run as interrupted.
        if [[ -n "$HELPER_FORWARDED" ]] && (( HELPER_STATUS == 0 || HELPER_STATUS == 3 || HELPER_STATUS == 4 )); then
            exit "$HELPER_FORWARDED"
        fi
        exit "$HELPER_STATUS"
    fi
    trap 'on_signal 130' INT
    trap 'on_signal 143' TERM
    if [[ -n "$HELPER_PENDING" ]] || (( HELPER_STATUS == 130 || HELPER_STATUS == 143 )); then
        IN_DELIVERY=true
        emit_outcome failed interrupted no
        exit "${HELPER_PENDING:-$HELPER_STATUS}"
    fi
else
    # No pipe could be made (no usable temporary directory), so the start
    # could not be supervised. The helper is not started: this shell keeps
    # its INT and TERM traps and delivers the original below.
    unset HUMANIZE_POLISH_STDERR_FD HUMANIZE_POLISH_SIGNALS
    START_FAILURE="could not create the readiness pipe"
fi
diag "${START_FAILURE:-could not start $PYTHON_BIN}; delivering the original"
deliver_original "${SKIP_REASON:-missing_dependency}"
