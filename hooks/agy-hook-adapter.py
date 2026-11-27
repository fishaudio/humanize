#!/usr/bin/env python3
"""Run Humanize's RLCR hooks from agy (Antigravity CLI) lifecycle hooks.

agy and Claude Code both run shell hooks with JSON on stdin, but the payloads
and replies differ. This adapter translates one agy hook event into the
Claude Code shape the Humanize hooks expect, runs the matching hook script
unchanged, and translates the result back.

Usage (from the plugin's hooks.json, through agy-hook.sh):
    agy-hook-adapter.py pre-tool | post-tool | stop

agy facts this relies on (agy 1.5.x, measured):
- Payload keys are camelCase: conversationId, transcriptPath, cwd,
  workspacePaths, toolCall {name, args}, executionNum, terminationReason.
- The hook process runs in the plugin folder, not the project, so the project
  is taken from the payload.
- PreToolUse: empty stdout leaves the decision to the user's own permission
  settings; {"decision": "deny", "reason": ...} blocks the tool. Any other
  reply, including {} or a non-zero exit, also blocks the tool, so this adapter
  prints either nothing or a deny.
- Stop: {"decision": "continue", "reason": ...} keeps the agent working and
  injects the reason as a system message. agy honors at most 10 such
  continuations per user message; executionNum counts the ones already used.

Output rules for people: the text this adapter injects is read by the coding
agent (Gemini). It tells the agent to explain things to the user in its own
plain words and never to paste reviewer output to the user.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent

# agy stops honoring Stop-hook continuations after this many per user message.
DEFAULT_CONTINUATION_LIMIT = 10

WRITE_TOOLS = {"write_file", "write_to_file"}
EDIT_TOOLS = {"edit_file", "replace_file_content"}
MULTI_EDIT_TOOLS = {"multi_replace_file_content"}
# File-changing tools whose arguments carry no plain old/new text pair.
OPAQUE_EDIT_TOOLS = {"sed_file", "notebook_edit"}
READ_TOOLS = {"read_file", "view_file"}
BASH_TOOLS = {"run_command"}

# Stop events that mean "the agent finished its turn normally". Others (user
# cancel, errors, invocation or token limits) must not trigger a review.
REVIEWABLE_TERMINATIONS = {"", "NO_TOOL_CALL", "TERMINAL_STEP_TYPE"}

PATH_KEYS = ("Path", "TargetFile", "AbsolutePath", "FilePath", "File", "NotebookPath", "file_path", "path")
CONTENT_KEYS = ("Content", "CodeContent", "content")
TARGET_KEYS = ("Target", "TargetContent", "old_string")
REPLACEMENT_KEYS = ("Replacement", "ReplacementContent", "new_string")
REPLACE_ALL_KEYS = ("AllowMultiple", "ReplaceAll", "replace_all")
COMMAND_KEYS = ("CommandLine", "Command", "command")
CHUNK_KEYS = ("ReplacementChunks", "Chunks", "Edits")

ACTIVE_STATE_FILES = ("state.md", "finalize-state.md", "methodology-analysis-state.md")

AGENT_PREAMBLE = """[Humanize RLCR loop on agy]
- The loop text below was written for Claude Code. "Claude" means you, the coding agent. Map tool names with the table in the humanize-start-rlcr-loop skill.
- Reviewer feedback below is for you only. Never paste it to the user. When you tell the user anything, explain it in your own plain, everyday words.
"""

LAST_CONTINUATION_NOTE = """
[Humanize note: last automatic continuation]
agy allows only {limit} automatic continuations per user message, and this is the last one in this message. Finish this round as usual: do the work, write the summary, commit, then stop. In your final reply, tell the user in plain words that the loop paused only because of this agy limit, and that replying "continue" resumes it. When the user replies "continue", end your turn right away without starting new work, so the review of this round can run.
"""


def first_value(args, keys, default=None):
    for key in keys:
        value = args.get(key)
        if value is not None:
            return value
    return default


def find_path(args):
    value = first_value(args, PATH_KEYS)
    if isinstance(value, str) and value:
        return value
    # Unknown schema: take the first string argument whose name mentions a path or file.
    for key, value in args.items():
        lowered = key.lower()
        if isinstance(value, str) and value and ("path" in lowered or "file" in lowered):
            return value
    return ""


def find_repo_root(start):
    """Return the nearest ancestor of start that holds .git, or None."""
    try:
        path = Path(start).resolve()
    except (OSError, RuntimeError):
        return None
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def project_root(payload):
    candidates = []
    if isinstance(payload.get("cwd"), str) and payload["cwd"]:
        candidates.append(payload["cwd"])
    workspaces = payload.get("workspacePaths")
    if isinstance(workspaces, list):
        candidates.extend(w for w in workspaces if isinstance(w, str) and w)
    for candidate in candidates:
        root = find_repo_root(candidate)
        if root is not None:
            return root
    return None


def has_active_loop(root):
    rlcr = root / ".humanize" / "rlcr"
    if not rlcr.is_dir():
        return False
    try:
        for loop_dir in rlcr.iterdir():
            if loop_dir.is_dir() and any((loop_dir / name).is_file() for name in ACTIVE_STATE_FILES):
                return True
    except OSError:
        return True  # Cannot tell: let the hook scripts decide.
    return False


def claude_payload(payload, root, event):
    return {
        "hook_event_name": event,
        "session_id": payload.get("conversationId") or None,
        "transcript_path": payload.get("transcriptPath") or None,
        "cwd": str(root),
        "permission_mode": "default",
    }


def run_hook(script, hook_input, root):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env["HUMANIZE_HOST"] = "agy"
    proc = subprocess.run(
        ["bash", str(HOOKS_DIR / script)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        cwd=str(root),
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def tool_args(payload):
    tool_call = payload.get("toolCall") or {}
    name = tool_call.get("name") or ""
    args = tool_call.get("args") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return name, args


def validator_calls(name, args):
    """Translate one agy tool call into (script, Claude tool name, tool_input) checks."""
    if name in WRITE_TOOLS:
        content = first_value(args, CONTENT_KEYS, "")
        return [("loop-write-validator.sh", "Write", {"file_path": find_path(args), "content": str(content)})]
    if name in EDIT_TOOLS:
        return [("loop-edit-validator.sh", "Edit", {
            "file_path": find_path(args),
            "old_string": str(first_value(args, TARGET_KEYS, "")),
            "new_string": str(first_value(args, REPLACEMENT_KEYS, "")),
            "replace_all": bool(first_value(args, REPLACE_ALL_KEYS, False)),
        })]
    if name in MULTI_EDIT_TOOLS:
        path = find_path(args)
        chunks = first_value(args, CHUNK_KEYS, [])
        if isinstance(chunks, str):
            try:
                chunks = json.loads(chunks)
            except ValueError:
                chunks = []
        calls = []
        for chunk in chunks if isinstance(chunks, list) else []:
            if not isinstance(chunk, dict):
                continue
            calls.append(("loop-edit-validator.sh", "Edit", {
                "file_path": path,
                "old_string": str(first_value(chunk, TARGET_KEYS, "")),
                "new_string": str(first_value(chunk, REPLACEMENT_KEYS, "")),
                "replace_all": bool(first_value(chunk, REPLACE_ALL_KEYS, False)),
            }))
        if not calls:
            calls.append(("loop-edit-validator.sh", "Edit", {"file_path": path, "old_string": "", "new_string": ""}))
        return calls
    if name in OPAQUE_EDIT_TOOLS:
        # No old/new text to check, so the edit validator fails closed on
        # protected files (goal tracker, state files) and allows the rest.
        return [("loop-edit-validator.sh", "Edit", {"file_path": find_path(args), "old_string": "", "new_string": ""})]
    if name in READ_TOOLS:
        return [("loop-read-validator.sh", "Read", {"file_path": find_path(args)})]
    if name in BASH_TOOLS:
        return [("loop-bash-validator.sh", "Bash", {"command": str(first_value(args, COMMAND_KEYS, ""))})]
    return []


def deny_reason_from_stdout(stdout):
    """Claude-style JSON denials printed on stdout (exit 0)."""
    text = stdout.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    specific = obj.get("hookSpecificOutput") or {}
    if isinstance(specific, dict) and specific.get("permissionDecision") == "deny":
        return specific.get("permissionDecisionReason") or obj.get("reason") or "Blocked by the Humanize RLCR loop."
    if obj.get("decision") in ("block", "deny"):
        return obj.get("reason") or "Blocked by the Humanize RLCR loop."
    return None


def handle_pre_tool(payload, root):
    name, args = tool_args(payload)
    for script, claude_tool, tool_input in validator_calls(name, args):
        hook_input = claude_payload(payload, root, "PreToolUse")
        hook_input["tool_name"] = claude_tool
        hook_input["tool_input"] = tool_input
        code, stdout, stderr = run_hook(script, hook_input, root)
        reason = None
        if code != 0:
            # Exit 2 is a block; other failures mean the input or loop state
            # could not be checked, which blocks too while a loop is active.
            reason = stderr.strip() or f"Blocked by the Humanize RLCR loop ({script} exit {code})."
        else:
            reason = deny_reason_from_stdout(stdout)
        if reason:
            return {"decision": "deny", "reason": reason}
    return None


def handle_post_tool(payload, root):
    name, args = tool_args(payload)
    if name not in BASH_TOOLS or payload.get("error"):
        return None
    hook_input = claude_payload(payload, root, "PostToolUse")
    hook_input["tool_name"] = "Bash"
    hook_input["tool_input"] = {"command": str(first_value(args, COMMAND_KEYS, ""))}
    code, _stdout, stderr = run_hook("loop-post-bash-hook.sh", hook_input, root)
    if code != 0 and stderr.strip():
        print(stderr.strip(), file=sys.stderr)
    return None


def continuation_limit():
    try:
        value = int(os.environ.get("HUMANIZE_AGY_CONTINUATION_LIMIT", DEFAULT_CONTINUATION_LIMIT))
    except ValueError:
        return DEFAULT_CONTINUATION_LIMIT
    return value if value > 0 else DEFAULT_CONTINUATION_LIMIT


def handle_stop(payload, root):
    termination = str(payload.get("terminationReason") or "")
    if termination not in REVIEWABLE_TERMINATIONS:
        return None
    limit = continuation_limit()
    try:
        used = int(payload.get("executionNum") or 0)
    except (TypeError, ValueError):
        used = 0
    if used >= limit:
        # agy would ignore a continuation now. Leave the round unreviewed; the
        # review runs on the next stop, after the user replies "continue".
        return None

    hook_input = claude_payload(payload, root, "Stop")
    hook_input["stop_hook_active"] = bool(payload.get("continuationActive"))
    hook_input["last_assistant_message"] = None
    code, stdout, stderr = run_hook("loop-codex-stop-hook.sh", hook_input, root)

    reason = None
    if code == 2:
        reason = stderr.strip()
    elif code == 0 and stdout.strip():
        try:
            obj = json.loads(stdout)
        except ValueError:
            obj = None
        if isinstance(obj, dict) and obj.get("decision") == "block":
            reason = str(obj.get("reason") or "")
    elif code != 0 and stderr.strip():
        print(stderr.strip(), file=sys.stderr)

    if reason is None:
        return None
    text = AGENT_PREAMBLE + "\n" + reason.strip() + "\n"
    if used == limit - 1:
        text += LAST_CONTINUATION_NOTE.format(limit=limit)
    return {"decision": "continue", "reason": text}


HANDLERS = {
    "pre-tool": handle_pre_tool,
    "post-tool": handle_post_tool,
    "stop": handle_stop,
}


def main(argv):
    if len(argv) != 2 or argv[1] not in HANDLERS:
        print("usage: agy-hook-adapter.py pre-tool|post-tool|stop", file=sys.stderr)
        return 0
    event = argv[1]
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        print("humanize agy adapter: hook input is not JSON; ignoring", file=sys.stderr)
        return 0
    if not isinstance(payload, dict):
        return 0
    root = project_root(payload)
    if root is None or not has_active_loop(root):
        return 0
    try:
        reply = HANDLERS[event](payload, root)
    except Exception as exc:  # Never crash: a non-zero exit blocks every tool.
        print(f"humanize agy adapter error ({event}): {exc}", file=sys.stderr)
        if event == "pre-tool":
            reply = {"decision": "deny", "reason": f"Humanize could not check this tool call during the RLCR loop: {exc}"}
        else:
            reply = None
    if reply is not None:
        sys.stdout.write(json.dumps(reply) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
