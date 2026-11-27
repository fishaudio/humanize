#!/bin/sh
#
# agy (Antigravity CLI) hook entry point for the Humanize plugin.
#
# agy runs every hook command for every conversation once the plugin is
# installed, and a failing PreToolUse hook blocks the tool. So this wrapper
# stays silent (no decision, agy's own permission rules apply) whenever the
# adapter cannot run, and otherwise hands the event to agy-hook-adapter.py.
#
# Usage: agy-hook.sh pre-tool|post-tool|stop   (agy JSON payload on stdin)
#
if ! command -v python3 >/dev/null 2>&1; then
    cat >/dev/null
    echo "humanize: python3 not found; RLCR hooks are inactive" >&2
    exit 0
fi
exec python3 -I "$(dirname "$0")/agy-hook-adapter.py" "$@"
