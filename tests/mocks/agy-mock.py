#!/usr/bin/env python3
"""Stand-in for the agy (Antigravity CLI) headless run, for offline tests.

polish-gemini.sh runs it in place of agy through HUMANIZE_POLISH_AGY_BIN. It
reads the prompt from standard input, prints an agy-style stream-json event
stream on standard output, and never contacts any host.

Environment:
    AGY_MOCK_SCENARIO   path of a JSON scenario (optional; an empty one echoes)
    AGY_MOCK_LOG        path of a JSONL file; one line per run is appended with
                        argv, cwd, the files in cwd, the hook file, stdin, and
                        which credential variables were set

Scenario fields (all optional):
    mode             "echo" (default) returns the document in a valid output
                     block; "content" returns "content" with {BEGIN}, {END}
                     and {DOC} filled in
    replace          list of [old, new] pairs applied to the document
    content          literal response for mode "content"
    status           result status (default "SUCCESS")
    error            result error message
    finished_reason  result finished_reason
    exit             exit status (default 0)
    stderr           text written to standard error
    permission_mode  init permission_mode (default: toolPermission from --settings)
    no_init          true: print no init event
    no_result        true: print no result event
    raw_stdout       exact standard output instead of an event stream
    tool_steps       list of tool names reported as tool steps
    denied_actions   list of action names reported in the result
    sleep            seconds to sleep before printing anything
    label            model label written to --log-file (default: built from
                     --model and --effort)
    usage            result usage object
    pid_file         path where the mock writes its process ID
"""

import json
import os
import re
import sys
import time

# The contract shown before the document names the markers too, so the
# document starts at the last begin marker.
BEGIN_RE = re.compile(r"@@HUMANIZE-POLISH-DOCUMENT-BEGIN-([0-9A-F]+)@@\n")
DEFAULT_USAGE = {"input_tokens": 11000, "output_tokens": 900, "thinking_tokens": 700,
                 "cache_read_tokens": 0, "total_tokens": 11900}


def flag(argv, name):
    for i, arg in enumerate(argv):
        if arg == name and i + 1 < len(argv):
            return argv[i + 1]
    return None


def main():
    argv = sys.argv[1:]
    stdin = sys.stdin.read()
    scenario = {}
    path = os.environ.get("AGY_MOCK_SCENARIO")
    if path and os.path.exists(path):
        with open(path) as fh:
            scenario = json.load(fh)
    if scenario.get("pid_file"):
        with open(scenario["pid_file"], "w") as fh:
            fh.write(str(os.getpid()))

    log = os.environ.get("AGY_MOCK_LOG")
    if log:
        hooks = None
        hook_path = os.path.join(os.getcwd(), ".agents", "hooks.json")
        if os.path.exists(hook_path):
            with open(hook_path) as fh:
                hooks = fh.read()
        files = []
        for root, dirs, names in os.walk(os.getcwd()):
            for name in names:
                files.append(os.path.relpath(os.path.join(root, name), os.getcwd()))
        entry = {
            "argv": argv,
            "cwd": os.getcwd(),
            "files": sorted(files),
            "hooks": hooks,
            "stdin": stdin,
            "env": {k: (k in os.environ) for k in ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                                                   "GOOGLE_APPLICATION_CREDENTIALS", "AGY_ADC_AUTH")},
        }
        with open(log, "a") as fh:
            fh.write(json.dumps(entry) + "\n")

    model = flag(argv, "--model") or "default"
    effort = flag(argv, "--effort") or "default"
    log_file = flag(argv, "--log-file")
    if log_file:
        label = scenario.get("label", "Mock %s (%s)" % (model, effort.capitalize()))
        with open(log_file, "w") as fh:
            fh.write('I0000 resolver.go:85] Resolving model %s-%s\n' % (model, effort))
            fh.write('I0000 model_config_manager.go:375] Propagating selected model override to backend: '
                     'label="%s"\n' % label)

    if scenario.get("sleep"):
        time.sleep(float(scenario["sleep"]))
    if scenario.get("stderr"):
        sys.stderr.write(scenario["stderr"] + "\n")
    if "raw_stdout" in scenario:
        sys.stdout.write(scenario["raw_stdout"])
        sys.stdout.flush()
        return int(scenario.get("exit", 0))

    try:
        settings = json.loads(flag(argv, "--settings") or "{}")
    except ValueError:
        settings = {}
    conv = "mock-conversation"
    events = []
    if not scenario.get("no_init"):
        events.append({"event": "init", "conversation_id": conv, "init": {
            "model": model, "cwd": os.getcwd(), "tools": ["view_file", "run_command"],
            "permission_mode": scenario.get("permission_mode", settings.get("toolPermission", "default"))}})
    events.append({"event": "step_update", "step_update": {
        "conversation_id": conv, "step_index": 0, "state": "DONE", "step_type": "user_input"}})
    for n, name in enumerate(scenario.get("tool_steps") or []):
        events.append({"event": "step_update", "step_update": {
            "conversation_id": conv, "step_index": n + 1, "state": "ERROR", "step_type": "tool",
            "tool_name": name, "tool_info": {"name": name, "error": {
                "type": "TOOL_ERROR", "message": "tool call denied by pre-tool hook"}}}})

    starts = list(BEGIN_RE.finditer(stdin))
    nonce = starts[-1].group(1) if starts else "MISSING"
    doc = ""
    if starts:
        stop = stdin.find("\n@@HUMANIZE-POLISH-DOCUMENT-END-%s@@" % nonce, starts[-1].end())
        doc = stdin[starts[-1].end():stop] if stop >= 0 else ""
    for old, new in scenario.get("replace") or []:
        doc = doc.replace(old, new)
    begin = "@@HUMANIZE-POLISH-OUTPUT-BEGIN-%s@@" % nonce
    end = "@@HUMANIZE-POLISH-OUTPUT-END-%s@@" % nonce
    if scenario.get("mode") == "content":
        response = (scenario.get("content") or "").replace("{BEGIN}", begin).replace(
            "{END}", end).replace("{DOC}", doc)
    else:
        response = "%s\n%s\n%s\n" % (begin, doc, end)
    status = scenario.get("status", "SUCCESS")
    if status != "SUCCESS" or scenario.get("tool_steps") or scenario.get("denied_actions"):
        response = scenario.get("response", "")
    events.append({"event": "step_update", "step_update": {
        "conversation_id": conv, "step_index": 9, "state": "DONE", "step_type": "agent_response",
        "text_delta": response}})
    result = {"conversation_id": conv, "status": status, "response": response,
              "duration_seconds": 1.5, "num_turns": 1, "usage": scenario.get("usage", DEFAULT_USAGE)}
    if scenario.get("error"):
        result["error"] = scenario["error"]
    if scenario.get("finished_reason"):
        result["finished_reason"] = scenario["finished_reason"]
    if scenario.get("denied_actions"):
        result["denied_actions"] = [{"action": a, "display_name": a} for a in scenario["denied_actions"]]
    if not scenario.get("no_result"):
        events.append({"event": "result", "result": result})
    for event in events:
        sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()
    return int(scenario.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main())
