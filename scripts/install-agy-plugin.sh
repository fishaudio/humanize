#!/usr/bin/env bash
#
# Install or update Humanize as a native agy (Antigravity CLI) plugin.
#
# Layout written to <plugins-dir>/humanize/:
#   plugin.json            plugin manifest
#   hooks.json             agy hooks (PreToolUse, PostToolUse, Stop) -> runtime/hooks/agy-hook.sh
#   skills/<name>/SKILL.md agy skills, with the runtime path filled in
#   runtime/               Humanize scripts, hooks, templates, config and command procedures
#                          used by the hooks and skills
#
# The runtime sits in its own folder so agy only loads the plugin parts it
# knows (manifest, hooks, skills) and never mistakes runtime files for plugin
# content.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGINS_DIR="${HOME}/.gemini/config/plugins"
PLUGIN_NAME="humanize"
DRY_RUN="false"
VALIDATE="auto"

RUNTIME_DIRS=(scripts hooks prompt-template templates config agents commands)

usage() {
    cat <<'EOF'
Install or update Humanize as a native agy (Antigravity CLI) plugin.

Usage:
  scripts/install-agy-plugin.sh [options]

Options:
  --plugins-dir PATH  agy plugins folder (default: ~/.gemini/config/plugins)
  --no-validate       Skip `agy plugin validate` after installing
  --dry-run           Print actions without writing
  -h, --help          Show help
EOF
}

log() {
    printf '[install-agy-plugin] %s\n' "$*"
}

die() {
    printf '[install-agy-plugin] Error: %s\n' "$*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --plugins-dir)
            [[ -n "${2:-}" ]] || die "--plugins-dir requires a value"
            PLUGINS_DIR="$2"
            shift 2
            ;;
        --no-validate)
            VALIDATE="false"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

for dep in python3 jq git; do
    command -v "$dep" >/dev/null 2>&1 || die "$dep is required"
done
[[ -f "$REPO_ROOT/agy/hooks.json" ]] || die "agy/hooks.json not found under $REPO_ROOT"
[[ -d "$REPO_ROOT/agy/skills" ]] || die "agy/skills not found under $REPO_ROOT"
for dir in "${RUNTIME_DIRS[@]}"; do
    [[ -d "$REPO_ROOT/$dir" ]] || die "runtime folder not found: $REPO_ROOT/$dir"
done
if ! command -v agy >/dev/null 2>&1; then
    log "warning: agy is not on PATH; installing anyway"
fi

mkdir -p "$PLUGINS_DIR" 2>/dev/null || [[ "$DRY_RUN" == "true" ]] || die "cannot create $PLUGINS_DIR"
PLUGINS_DIR="$(cd "$PLUGINS_DIR" 2>/dev/null && pwd || printf '%s' "$PLUGINS_DIR")"
TARGET="$PLUGINS_DIR/$PLUGIN_NAME"
RUNTIME_ROOT="$TARGET/runtime"
VERSION="$(jq -r '.version // empty' "$REPO_ROOT/.claude-plugin/plugin.json" 2>/dev/null || true)"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "could not read the Humanize version from .claude-plugin/plugin.json"
SOURCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"

log "plugin folder: $TARGET"
log "runtime root:  $RUNTIME_ROOT"
log "version:       $VERSION ($SOURCE_COMMIT)"

if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN copy ${RUNTIME_DIRS[*]} -> $RUNTIME_ROOT"
    log "DRY-RUN write plugin.json, hooks.json and skills/ under $TARGET"
    exit 0
fi

STAGE="$(mktemp -d "$PLUGINS_DIR/.${PLUGIN_NAME}.install.XXXXXX")"
cleanup() {
    if [[ -n "${STAGE:-}" && -d "$STAGE" ]]; then
        rm -rf "${STAGE:?}"
    fi
}
trap cleanup EXIT

mkdir -p "$STAGE/runtime" "$STAGE/skills"
for dir in "${RUNTIME_DIRS[@]}"; do
    cp -R "$REPO_ROOT/$dir" "$STAGE/runtime/$dir"
done
find "$STAGE/runtime" -name '__pycache__' -type d -prune -exec rm -rf {} +

python3 - "$REPO_ROOT" "$STAGE" "$RUNTIME_ROOT" "$VERSION" "$SOURCE_COMMIT" <<'PY'
import json
import pathlib
import shutil
import sys

repo, stage, runtime_root, version, commit = sys.argv[1:6]
repo = pathlib.Path(repo)
stage = pathlib.Path(stage)

manifest = {
    "name": "humanize",
    "version": version,
    "description": "Humanize RLCR loop for agy: the agent implements a plan in rounds while Codex (or Claude) independently verifies each round and reviews the code.",
    "author": "PolyArch",
    "homepage": "https://github.com/PolyArch/humanize",
}
(stage / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

shutil.copyfile(repo / "agy" / "hooks.json", stage / "hooks.json")

for skill_dir in sorted((repo / "agy" / "skills").iterdir()):
    source = skill_dir / "SKILL.md"
    if not source.is_file():
        continue
    target_dir = stage / "skills" / skill_dir.name
    target_dir.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8").replace("{{HUMANIZE_RUNTIME_ROOT}}", runtime_root)
    if "{{" in text:
        raise SystemExit(f"unfilled placeholder left in {source}")
    (target_dir / "SKILL.md").write_text(text, encoding="utf-8")

# The command procedures (for example commands/gen-plan.md, which the
# humanize-gen-plan skill follows) refer to scripts through the Claude Code
# plugin variable; point them at this runtime instead.
for command in sorted((stage / "runtime" / "commands").glob("*.md")):
    text = command.read_text(encoding="utf-8")
    command.write_text(text.replace("${CLAUDE_PLUGIN_ROOT}", runtime_root), encoding="utf-8")

(stage / "runtime" / ".humanize-agy-install").write_text(
    json.dumps({"version": version, "source_commit": commit}) + "\n", encoding="utf-8"
)
PY

chmod +x "$STAGE/runtime/hooks/agy-hook.sh" "$STAGE/runtime/hooks/agy-hook-adapter.py" \
    "$STAGE/runtime/scripts/agy-rlcr-run.sh"

# Swap the new plugin in. A previous copy is moved aside first and removed
# only after the new one is in place.
BACKUP=""
if [[ -e "$TARGET" ]]; then
    BACKUP="$PLUGINS_DIR/.${PLUGIN_NAME}.previous.$$"
    mv "$TARGET" "$BACKUP"
fi
if ! mv "$STAGE" "$TARGET"; then
    [[ -n "$BACKUP" ]] && mv "$BACKUP" "$TARGET"
    die "could not move the new plugin into place"
fi
STAGE=""
[[ -n "$BACKUP" ]] && rm -rf "${BACKUP:?}"

if [[ "$VALIDATE" != "false" ]] && command -v agy >/dev/null 2>&1; then
    if agy plugin validate "$TARGET" >/dev/null 2>&1; then
        log "agy plugin validate: ok"
    else
        log "warning: agy plugin validate reported problems; run: agy plugin validate \"$TARGET\""
    fi
fi

cat <<EOF

Humanize agy plugin installed.
  plugin folder: $TARGET
  runtime root:  $RUNTIME_ROOT
  skills:        humanize-gen-plan, humanize-start-rlcr-loop, humanize-cancel-rlcr-loop
  unattended:    $RUNTIME_ROOT/scripts/agy-rlcr-run.sh <plan-file>

Reviewers default to Codex. To use Claude instead, set "rlcr_verifier" and/or
"rlcr_reviewer" to "claude" in ~/.config/humanize/config.json or the project's
.humanize/config.json.
EOF
