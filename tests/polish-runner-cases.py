#!/usr/bin/env python3
"""Subprocess cases for the polish runner that need exact timing or failures.

Run by tests/test-polish-gemini.sh. Prints one "PASS: name" or
"FAIL: name: detail" line per case and exits 1 if any case failed.

Covered here (the loopback mock cannot produce these reliably):
- the effort fallback when the retry with "high" times out, fails on the
  network, or is interrupted: metadata must say effort_used: high;
- SIGTERM at the start of file delivery and during the rename: the file is
  delivered, the exit code is 143, and the outcome line still describes what
  was delivered;
- SIGTERM right before and right after the outcome line (Python), and at each
  step of the shell fallback's finish (via a DEBUG trap): one outcome line,
  exit 143;
- SIGTERM and SIGINT, sent to the process alone and to its whole process
  group, while stdout delivery is blocked on a full pipe, through the Python
  helper and through the shell fallback without Python;
- SIGINT that was ignored when the run started stays ignored on both paths.

No network is used: the HTTP call is replaced in the child process.
"""

import itertools
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "scripts", "lib")
RUNNER = os.path.join(ROOT, "scripts", "polish-gemini.sh")
TEMPLATES = os.path.join(ROOT, "prompt-template", "gemini")
DUMMY_KEY = "sk-or-test-runner-cases-key"
OUTCOME_PREFIX = "polish-gemini: outcome="
FAILED = []


def report(name, ok, detail=""):
    if ok:
        print("PASS: %s" % name)
    else:
        print("FAIL: %s: %s" % (name, str(detail).replace("\n", " | ")[:400]))
        FAILED.append(name)


# ----------------------------------------------------------------------------
# Child process: the real runner with an injected transport
# ----------------------------------------------------------------------------


def child(mode, work):
    sys.path.insert(0, LIB)
    import polish_gemini as p
    import urllib.error

    os.environ["OPENROUTER_API_KEY"] = DUMMY_KEY
    os.environ["XDG_CACHE_HOME"] = os.path.join(work, "cache")
    source = os.path.join(work, "input.md")
    with open(source, "w") as fh:
        fh.write("Read this clear sentence about the setup steps.\n")
    efforts_log = os.path.join(work, "efforts")

    def transport(url, body, headers, timeout):
        data = json.loads(body)
        effort = data["reasoning"]["effort"]
        with open(efforts_log, "a") as fh:
            fh.write(effort + "\n")
        calls = len(open(efforts_log).read().split())
        if mode.startswith("fallback_") and calls == 1:
            return 400, {}, json.dumps({"error": {
                "message": "Invalid value for reasoning.effort: xhigh is not supported"}}).encode()
        if mode == "fallback_timeout":
            raise socket.timeout("simulated timeout")
        if mode == "fallback_network":
            raise urllib.error.URLError("simulated connection refused")
        if mode == "fallback_interrupt":
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(10)
            raise socket.timeout("unreachable")
        user = data["messages"][1]["content"]
        nonce = re.search(r"DOCUMENT-BEGIN-([A-Fa-f0-9]+)@@", user).group(1)
        content = ("@@HUMANIZE-POLISH-OUTPUT-BEGIN-%s@@\nRead this clear sentence about the setup.\n"
                   "@@HUMANIZE-POLISH-OUTPUT-END-%s@@" % (nonce, nonce))
        return 200, {}, json.dumps({"choices": [{"finish_reason": "stop",
                                                 "message": {"content": content}}]}).encode()

    p.http_post = transport
    args = ["--input", source, "--model", "google/gemini-4-hydrogen",
            "--base-url", "http://127.0.0.1:9/api/v1", "--template-dir", TEMPLATES,
            "--project-root", work, "--timeout", "30"]
    target = os.path.join(work, "output.md")
    if mode == "signal_at_file_delivery":
        original = p.Runner._atomic_write

        def signal_then_write(self, path, payload):
            os.kill(os.getpid(), signal.SIGTERM)
            return original(self, path, payload)

        p.Runner._atomic_write = signal_then_write
        args += ["--output", target]
    if mode in ("signal_before_emit", "signal_after_emit"):
        original_emit = p.Runner.emit

        def emit_with_signal(self, outcome, reason, delivered):
            if mode == "signal_before_emit":
                os.kill(os.getpid(), signal.SIGTERM)
            original_emit(self, outcome, reason, delivered)
            if mode == "signal_after_emit":
                os.kill(os.getpid(), signal.SIGTERM)

        p.Runner.emit = emit_with_signal
    if mode == "signal_during_rename":
        original_replace = os.replace

        def signal_then_replace(src, dst):
            if dst == target:
                os.kill(os.getpid(), signal.SIGTERM)
            return original_replace(src, dst)

        os.replace = signal_then_replace
        args += ["--output", target]
    sys.exit(p.main(args))


def run_child(mode):
    work = tempfile.mkdtemp(prefix="polish-runner-cases-")
    proc = subprocess.run([sys.executable, "-I", "-B", __file__, "--child", mode, work],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    err = proc.stderr.decode("utf-8", "replace")
    outcomes = [ln for ln in err.splitlines() if ln.startswith(OUTCOME_PREFIX)]
    meta = ""
    skill = os.path.join(work, ".humanize", "skill")
    if os.path.isdir(skill):
        for run_id in sorted(os.listdir(skill)):
            path = os.path.join(skill, run_id, "metadata.md")
            if os.path.exists(path):
                meta = open(path).read()
    efforts = []
    if os.path.exists(os.path.join(work, "efforts")):
        efforts = open(os.path.join(work, "efforts")).read().split()
    output = None
    if os.path.exists(os.path.join(work, "output.md")):
        output = open(os.path.join(work, "output.md")).read()
    leftovers = [f for f in os.listdir(work) if f.startswith(".polish-gemini-")]
    shutil.rmtree(work, ignore_errors=True)
    return {"rc": proc.returncode, "stdout": proc.stdout, "err": err, "outcomes": outcomes,
            "meta": meta, "efforts": efforts, "output": output, "leftovers": leftovers}


def meta_value(meta, key):
    for line in meta.splitlines():
        if line.startswith(key + ": "):
            return line[len(key) + 2:]
    return None


# ----------------------------------------------------------------------------
# Cases
# ----------------------------------------------------------------------------


def effort_cases():
    for mode, reason, rc, delivered in (("fallback_timeout", "timeout", 0, "yes"),
                                        ("fallback_network", "network", 0, "yes"),
                                        ("fallback_interrupt", "interrupted", 143, "no")):
        r = run_child(mode)
        expected = "%sfailed reason=%s delivered=%s" % (OUTCOME_PREFIX, reason, delivered)
        report("%s: one outcome line, exit %d" % (mode, rc),
               r["outcomes"] == [expected] and r["rc"] == rc, "%r rc=%s" % (r["outcomes"], r["rc"]))
        report("%s: requests sent with xhigh then high" % mode, r["efforts"] == ["xhigh", "high"],
               r["efforts"])
        report("%s: metadata records effort_used: high" % mode,
               meta_value(r["meta"], "effort_used") == "high", r["meta"])
        if delivered == "yes":
            report("%s: the original is delivered" % mode,
                   r["stdout"] == b"Read this clear sentence about the setup steps.\n", r["stdout"])
        else:
            report("%s: nothing is delivered" % mode, r["stdout"] == b"", r["stdout"])


def file_signal_cases():
    for mode in ("signal_at_file_delivery", "signal_during_rename"):
        r = run_child(mode)
        expected = OUTCOME_PREFIX + "polished reason=ok delivered=yes"
        report("%s: exit 143 and the outcome of what was delivered" % mode,
               r["outcomes"] == [expected] and r["rc"] == 143, "%r rc=%s" % (r["outcomes"], r["rc"]))
        report("%s: the file holds the delivered text" % mode,
               r["output"] == "Read this clear sentence about the setup.\n", r["output"])
        report("%s: no temp files remain" % mode, not r["leftovers"], r["leftovers"])
        report("%s: metadata records the delivered outcome" % mode,
               meta_value(r["meta"], "outcome") == "polished"
               and meta_value(r["meta"], "delivered") == "yes", r["meta"])
        report("%s: a diagnostic reports the interruption" % mode,
               "interrupted by SIGTERM during delivery" in r["err"], r["err"])


def late_signal_cases():
    for mode in ("signal_before_emit", "signal_after_emit"):
        r = run_child(mode)
        expected = OUTCOME_PREFIX + "polished reason=ok delivered=yes"
        report("%s: one outcome line and exit 143" % mode,
               r["outcomes"] == [expected] and r["rc"] == 143, "%r rc=%s" % (r["outcomes"], r["rc"]))
        report("%s: the polished text is delivered" % mode,
               r["stdout"] == b"Read this clear sentence about the setup.\n", r["stdout"])
        report("%s: the outcome line is the last stderr line" % mode,
               r["err"].splitlines()[-1:] == [expected], r["err"].splitlines()[-2:])


def shell_finish_race_cases():
    """Send SIGTERM from a DEBUG trap at each step of the shell's finish_delivery."""
    payload = b"Read the source text for the fallback path.\n"
    for step in ("cleanup_temps", "emit_outcome", "exit"):
        work = tempfile.mkdtemp(prefix="polish-runner-race-")
        source = os.path.join(work, "input.txt")
        with open(source, "wb") as fh:
            fh.write(payload)
        env_file = os.path.join(work, "bash-env.sh")
        with open(env_file, "w") as fh:
            fh.write("set -o functrace\n"
                     "__polish_sent=\"\"\n"
                     "trap 'if [[ -z \"$__polish_sent\" && \"${FUNCNAME[0]:-}\" == finish_delivery"
                     " && \"$BASH_COMMAND\" == %s* ]]; then __polish_sent=1; kill -TERM $$; fi' DEBUG\n"
                     % step)
        env = dict(os.environ)
        for key in ("HUMANIZE_CONFIG", "PYTHONPATH", "HUMANIZE_POLISH_BASE_URL"):
            env.pop(key, None)
        env.update(CLAUDE_PROJECT_DIR=work, XDG_CONFIG_HOME=work, XDG_CACHE_HOME=work,
                   OPENROUTER_API_KEY="", BASH_ENV=env_file,
                   HUMANIZE_POLISH_PYTHON=os.path.join(work, "no-such-python3"))
        proc = subprocess.run([RUNNER, "--input", source], env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=60)
        shutil.rmtree(work, ignore_errors=True)
        err = proc.stderr.decode("utf-8", "replace")
        outcomes = [ln for ln in err.splitlines() if ln.startswith(OUTCOME_PREFIX)]
        name = "SIGTERM before %s in the shell fallback finish" % step
        report("%s: one outcome line describing the delivery, exit 143" % name,
               proc.returncode == 143
               and outcomes == [OUTCOME_PREFIX + "skipped reason=missing_dependency delivered=yes"],
               "rc=%s %r" % (proc.returncode, outcomes))
        report("%s: every byte is delivered" % name, proc.stdout == payload, proc.stdout)


def blocked_stdout_cases():
    payload = b"Read the source text.\n" * 50000  # far more than a pipe buffer
    for path, target, (signame, signum, rc) in itertools.product(
            ("python", "no_python"), ("process", "group"),
            (("TERM", signal.SIGTERM, 143), ("INT", signal.SIGINT, 130))):
        work = tempfile.mkdtemp(prefix="polish-runner-pipe-")
        source = os.path.join(work, "input.txt")
        with open(source, "wb") as fh:
            fh.write(payload)
        env = dict(os.environ)
        for key in ("HUMANIZE_CONFIG", "HUMANIZE_POLISH_PYTHON", "PYTHONPATH",
                    "HUMANIZE_POLISH_BASE_URL"):
            env.pop(key, None)
        env.update(CLAUDE_PROJECT_DIR=work, XDG_CONFIG_HOME=work, XDG_CACHE_HOME=work,
                   OPENROUTER_API_KEY="")
        if path == "no_python":
            env["HUMANIZE_POLISH_PYTHON"] = os.path.join(work, "no-such-python3")
        proc = subprocess.Popen([RUNNER, "--input", source], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
        first = os.read(proc.stdout.fileno(), 1)
        if target == "group":
            os.killpg(proc.pid, signum)
        else:
            os.kill(proc.pid, signum)
        out, err = proc.communicate(timeout=30)
        err = err.decode("utf-8", "replace")
        shutil.rmtree(work, ignore_errors=True)
        outcomes = [ln for ln in err.splitlines() if ln.startswith(OUTCOME_PREFIX)]
        name = "SIG%s to the %s while stdout is blocked (%s)" % (
            signame, target, path.replace("_", " "))
        report("%s: every byte is delivered" % name, first + out == payload,
               "%d of %d bytes" % (len(first + out), len(payload)))
        reason = "too_large" if path == "python" else "missing_dependency"
        report("%s: exit %d with delivered=yes" % (name, rc),
               proc.returncode == rc
               and outcomes == [OUTCOME_PREFIX + "skipped reason=%s delivered=yes" % reason],
               "rc=%s %r" % (proc.returncode, outcomes))


def ignored_signal_cases():
    """SIGINT ignored when the run starts (a background job) stays ignored."""
    payload = b"Read the source text.\n" * 50000
    for path in ("python", "no_python"):
        work = tempfile.mkdtemp(prefix="polish-runner-ign-")
        source = os.path.join(work, "input.txt")
        with open(source, "wb") as fh:
            fh.write(payload)
        env = dict(os.environ)
        for key in ("HUMANIZE_CONFIG", "HUMANIZE_POLISH_PYTHON", "PYTHONPATH",
                    "HUMANIZE_POLISH_BASE_URL"):
            env.pop(key, None)
        env.update(CLAUDE_PROJECT_DIR=work, XDG_CONFIG_HOME=work, XDG_CACHE_HOME=work,
                   OPENROUTER_API_KEY="")
        if path == "no_python":
            env["HUMANIZE_POLISH_PYTHON"] = os.path.join(work, "no-such-python3")
        proc = subprocess.Popen([RUNNER, "--input", source], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0, start_new_session=True,
                                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN))
        first = os.read(proc.stdout.fileno(), 1)
        os.killpg(proc.pid, signal.SIGINT)
        out, err = proc.communicate(timeout=30)
        err = err.decode("utf-8", "replace")
        shutil.rmtree(work, ignore_errors=True)
        outcomes = [ln for ln in err.splitlines() if ln.startswith(OUTCOME_PREFIX)]
        reason = "too_large" if path == "python" else "missing_dependency"
        name = "SIGINT ignored on entry (%s)" % path.replace("_", " ")
        report("%s: the run finishes normally with exit 0" % name,
               proc.returncode == 0 and first + out == payload
               and outcomes == [OUTCOME_PREFIX + "skipped reason=%s delivered=yes" % reason],
               "rc=%s %r" % (proc.returncode, outcomes))


def main():
    # Children must not inherit an ignored SIGINT (for example when this script
    # runs as a background job); the cases that want one set it themselves.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    effort_cases()
    file_signal_cases()
    late_signal_cases()
    shell_finish_race_cases()
    blocked_stdout_cases()
    ignored_signal_cases()
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3])
    else:
        main()
