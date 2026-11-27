#!/usr/bin/env bash
#
# Run a Humanize RLCR loop in agy with nobody at the keyboard.
# See scripts/lib/agy_rlcr_run.py or run with --help.
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
    echo "agy-rlcr-run: python3 is required" >&2
    exit 64
fi
exec python3 -I "$SCRIPT_DIR/lib/agy_rlcr_run.py" "$@"
