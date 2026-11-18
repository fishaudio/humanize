#!/usr/bin/env python3
"""Loopback mock of the OpenRouter chat completions endpoint for offline tests.

Usage:
    openrouter-mock.py --port-file PATH --scenario PATH

The server binds 127.0.0.1 on a free port and writes the port number to
--port-file. On every request it re-reads the scenario JSON file:

    {
      "id": "unique-per-test",          # request counters reset when the id changes
      "log": "/path/requests.jsonl",    # one JSON line per request is appended here
      "responses": [ {...}, {...} ]     # served in order; the last one repeats
    }

Response fields (all optional):
    status          HTTP status (default 200)
    headers         extra response headers
    hang            seconds to sleep before answering
    raw             exact response body (string)
    json            exact JSON response body (object)
    mode            "echo" (default) returns the document in a valid envelope;
                    "content" returns the "content" string with {BEGIN}, {END}
                    and {DOC} placeholders filled in
    replace         list of [old, new] pairs applied to the document
    content         literal content for mode "content"
    finish_reason   default "stop"
    tool_calls      list placed in the message
    function_call   object placed in the message
    error           object placed at the top level of a 200 response
    reasoning       string placed in message.reasoning
    usage           usage object (a default with tokens and cost is used otherwise)

Standard library only; never contacts any other host.
"""

import argparse
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

DOC_RE = re.compile(
    r"@@HUMANIZE-POLISH-DOCUMENT-BEGIN-([0-9A-F]+)@@\n(.*)\n@@HUMANIZE-POLISH-DOCUMENT-END-\1@@",
    re.S)
DEFAULT_USAGE = {
    "prompt_tokens": 1200,
    "completion_tokens": 900,
    "total_tokens": 2100,
    "completion_tokens_details": {"reasoning_tokens": 700},
    "cost": 0.00855,
}

STATE = {"id": None, "count": 0}
LOCK = threading.Lock()


class ThreadingServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def load_scenario(path):
    with open(path, "r") as fh:
        return json.load(fh)


class Handler(BaseHTTPRequestHandler):
    scenario_path = None

    def log_message(self, fmt, *args):  # keep test output quiet
        pass

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            body = raw.decode("utf-8", "replace")
        scenario = load_scenario(self.scenario_path)
        with LOCK:
            if STATE["id"] != scenario.get("id"):
                STATE["id"] = scenario.get("id")
                STATE["count"] = 0
            index = STATE["count"]
            STATE["count"] += 1
        log_path = scenario.get("log")
        if log_path:
            entry = {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
            with LOCK:
                with open(log_path, "a") as fh:
                    fh.write(json.dumps(entry) + "\n")
        responses = scenario.get("responses") or [{}]
        spec = responses[min(index, len(responses) - 1)]
        if spec.get("hang"):
            time.sleep(float(spec["hang"]))
        status = int(spec.get("status", 200))
        if "raw" in spec:
            payload = spec["raw"].encode("utf-8")
        elif "json" in spec:
            payload = json.dumps(spec["json"]).encode("utf-8")
        else:
            payload = json.dumps(build_completion(spec, body)).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for key, value in (spec.get("headers") or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass


def build_completion(spec, body):
    user = ""
    if isinstance(body, dict):
        for msg in body.get("messages") or []:
            if msg.get("role") == "user":
                user = msg.get("content") or ""
    m = DOC_RE.search(user)
    nonce = m.group(1) if m else "MISSING"
    doc = m.group(2) if m else ""
    for old, new in spec.get("replace") or []:
        doc = doc.replace(old, new)
    begin = "@@HUMANIZE-POLISH-OUTPUT-BEGIN-%s@@" % nonce
    end = "@@HUMANIZE-POLISH-OUTPUT-END-%s@@" % nonce
    if spec.get("mode") == "content":
        content = spec.get("content", "")
        content = content.replace("{BEGIN}", begin).replace("{END}", end).replace("{DOC}", doc)
    else:
        content = "%s\n%s\n%s" % (begin, doc, end)
    message = {"role": "assistant", "content": content}
    if "tool_calls" in spec:
        message["tool_calls"] = spec["tool_calls"]
    if "function_call" in spec:
        message["function_call"] = spec["function_call"]
    if "reasoning" in spec:
        message["reasoning"] = spec["reasoning"]
    if spec.get("null_content"):
        message["content"] = None
    result = {
        "id": "gen-mock",
        "object": "chat.completion",
        "model": body.get("model") if isinstance(body, dict) else "unknown",
        "choices": [{
            "index": 0,
            "finish_reason": spec.get("finish_reason", "stop"),
            "message": message,
        }],
        "usage": spec.get("usage", DEFAULT_USAGE),
    }
    if "error" in spec:
        result["error"] = spec["error"]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port-file", required=True)
    parser.add_argument("--scenario", required=True)
    args = parser.parse_args()
    Handler.scenario_path = args.scenario
    server = ThreadingServer(("127.0.0.1", 0), Handler)
    with open(args.port_file + ".tmp", "w") as fh:
        fh.write(str(server.server_address[1]))
    import os
    os.replace(args.port_file + ".tmp", args.port_file)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
