#!/usr/bin/env bash
#
# Tests for the polish fidelity guard and HTML adapter (scripts/lib/polish_guard.py)
#
# Runs tests/polish-guard-cases.py, which checks accepted rewrites, every
# rejected rewrite class (code, protected tokens, structure, inline markup,
# language, length, segments) and the HTML extract/splice/verify path.
#

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/test-helpers.sh"

echo "========================================"
echo "Polish Gemini Guard Tests"
echo "========================================"

if ! command -v python3 >/dev/null 2>&1; then
    skip "polish guard cases" "python3 is required"
    print_test_summary "Polish Gemini Guard Test Summary"
    exit 0
fi

CASES_OUTPUT="$(python3 -I -B "$SCRIPT_DIR/polish-guard-cases.py" 2>&1)"
CASES_RC=$?

while IFS= read -r line; do
    case "$line" in
        "PASS: "*) pass "${line#PASS: }" ;;
        "FAIL: "*) fail "${line#FAIL: }" ;;
        "") ;;
        *) echo "$line" ;;
    esac
done <<< "$CASES_OUTPUT"

if [[ "$CASES_RC" -ne 0 && "$TESTS_FAILED" -eq 0 ]]; then
    fail "guard case runner exits cleanly" "exit 0" "exit $CASES_RC"
fi

# Compile in memory only, so no __pycache__ directories are written.
if python3 -I -B -c 'import sys
for path in sys.argv[1:]:
    with open(path) as fh:
        compile(fh.read(), path, "exec")' \
    "$SCRIPT_DIR/../scripts/lib/polish_guard.py" "$SCRIPT_DIR/../scripts/lib/polish_gemini.py" \
    "$SCRIPT_DIR/mocks/openrouter-mock.py" "$SCRIPT_DIR/polish-guard-cases.py" "$SCRIPT_DIR/polish-runner-cases.py"; then
    pass "Python helpers and test files compile"
else
    fail "Python helpers and test files compile" "no syntax errors" "compile failed"
fi

print_test_summary "Polish Gemini Guard Test Summary"
