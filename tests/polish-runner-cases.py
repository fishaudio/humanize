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
- SIGINT that was ignored when the run started stays ignored on both paths;
- shell fallback edges: a failed stdin copy, SIGTERM during the output mode
  lookup, SIGTERM right before a usage error exits, SIGTERM in the moment
  before a delivery step ignores signals, and mv killed after the rename;
- the fallback's stderr holds only polish-gemini lines (a TMPDIR carrying a
  fake outcome line, a file size limit, a missing output directory);
- a group SIGTERM before each temporary file is created, and after it is
  created but before its path is registered, leaves no file behind.

No network is used: the HTTP call is replaced in the child process.
"""

import itertools
import json
import os
import re
import resource
import shutil
import signal
import socket
import stat
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
    if mode == "signal_in_except":
        # A SIGTERM right after the handlers are installed, and a second one
        # on the first line of the handler for the first.
        import inspect
        src, first = inspect.getsourcelines(p.Runner.run)
        target_line = first + next(k for k, ln in enumerate(src) if "signum = exc.signum" in ln)
        original_set = p._set_signal_handlers
        fired = {"set": False, "line": False}

        def set_then_signal(handler):
            original_set(handler)
            if not fired["set"]:
                fired["set"] = True
                os.kill(os.getpid(), signal.SIGTERM)

        def tracer(frame, event, arg):
            if frame.f_code is p.Runner.run.__code__:
                def line_tracer(frame, event, arg):
                    if event == "line" and frame.f_lineno == target_line and not fired["line"]:
                        fired["line"] = True
                        os.kill(os.getpid(), signal.SIGTERM)
                    return line_tracer
                return line_tracer
            return None

        p._set_signal_handlers = set_then_signal
        sys.settrace(tracer)
    if mode in ("signal_after_handlers", "signal_twice"):
        # A signal right after the run installs its handlers, and (signal_twice)
        # a second one before the interruption path defers signals.
        original_set = p._set_signal_handlers
        original_block = p._block_signals
        state = {"set": 0, "block": 0}

        def set_then_signal(handler):
            original_set(handler)
            state["set"] += 1
            if state["set"] == 1:
                os.kill(os.getpid(), signal.SIGTERM)

        def signal_then_block():
            state["block"] += 1
            if mode == "signal_twice" and state["block"] == 1:
                os.kill(os.getpid(), signal.SIGTERM)
            original_block()

        p._set_signal_handlers = set_then_signal
        p._block_signals = signal_then_block
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


def fallback_env(work, extra=None):
    env = dict(os.environ)
    for key in ("HUMANIZE_CONFIG", "PYTHONPATH", "HUMANIZE_POLISH_BASE_URL", "BASH_ENV"):
        env.pop(key, None)
    env.update(CLAUDE_PROJECT_DIR=work, XDG_CONFIG_HOME=work, XDG_CACHE_HOME=work,
               OPENROUTER_API_KEY="", HUMANIZE_POLISH_PYTHON=os.path.join(work, "no-such-python3"))
    env.update(extra or {})
    return env


def outcome_lines(err):
    return [ln for ln in err.decode("utf-8", "replace").splitlines() if ln.startswith(OUTCOME_PREFIX)]


def write_script(path, body):
    with open(path, "w") as fh:
        fh.write(body)
    os.chmod(path, 0o755)


def fallback_edge_cases():
    """Shell fallback paths found by the second Round 1 re-review."""
    payload = b"Read the source text for the fallback path.\n"
    failed_no = [OUTCOME_PREFIX + "failed reason=delivery_error delivered=no"]
    skipped_yes = [OUTCOME_PREFIX + "skipped reason=missing_dependency delivered=yes"]

    # Copying stdin to a temporary file fails (file size limit): nothing is
    # delivered and an existing output is left alone.
    big = b"Read the source text.\n" * 70000
    limit = lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (8192, 8192))
    work = tempfile.mkdtemp(prefix="polish-runner-edge-")
    out = os.path.join(work, "out.md")
    with open(out, "wb") as fh:
        fh.write(b"old\n")
    proc = subprocess.run([RUNNER, "--input", "-"], input=big, env=fallback_env(work),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=limit, timeout=60)
    report("failed stdin copy to stdout: delivery_error, nothing delivered, exit 4",
           proc.returncode == 4 and outcome_lines(proc.stderr) == failed_no and proc.stdout == b"",
           "rc=%s %r %d bytes" % (proc.returncode, outcome_lines(proc.stderr), len(proc.stdout)))
    proc = subprocess.run([RUNNER, "--input", "-", "--output", out], input=big, env=fallback_env(work),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=limit, timeout=60)
    with open(out, "rb") as fh:
        unchanged = fh.read() == b"old\n"
    report("failed stdin copy to a file: delivery_error and the file is unchanged",
           proc.returncode == 4 and outcome_lines(proc.stderr) == failed_no and unchanged,
           "rc=%s %r unchanged=%s" % (proc.returncode, outcome_lines(proc.stderr), unchanged))
    shutil.rmtree(work, ignore_errors=True)

    # A group SIGTERM while the output's mode is looked up ends the run before
    # delivery; the file keeps its content and mode 600.
    work = tempfile.mkdtemp(prefix="polish-runner-edge-")
    source = os.path.join(work, "input.md")
    out = os.path.join(work, "out.md")
    with open(source, "wb") as fh:
        fh.write(payload)
    with open(out, "wb") as fh:
        fh.write(b"old\n")
    os.chmod(out, 0o600)
    shim = os.path.join(work, "bin")
    os.mkdir(shim)
    flag = os.path.join(work, "stat.flag")
    real_stat = shutil.which("stat")
    write_script(os.path.join(shim, "stat"),
                 "#!/bin/bash\n: > '%s'\nsleep 2\nexec '%s' \"$@\"\n" % (flag, real_stat))
    proc = subprocess.Popen([RUNNER, "--input", source, "--output", out],
                            env=fallback_env(work, {"PATH": shim + os.pathsep + os.environ["PATH"]}),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    for _ in range(200):
        if os.path.exists(flag):
            break
        time.sleep(0.05)
    os.killpg(proc.pid, signal.SIGTERM)
    _, err = proc.communicate(timeout=30)
    with open(out, "rb") as fh:
        unchanged = fh.read() == b"old\n"
    mode = stat.S_IMODE(os.stat(out).st_mode)
    report("SIGTERM during the mode lookup: interrupted, file and mode 600 unchanged, exit 143",
           proc.returncode == 143 and unchanged and mode == 0o600
           and outcome_lines(err) == [OUTCOME_PREFIX + "failed reason=interrupted delivered=no"],
           "rc=%s %r mode=%o unchanged=%s" % (proc.returncode, outcome_lines(err), mode, unchanged))
    shutil.rmtree(work, ignore_errors=True)

    # SIGTERM right before a usage error exits: still one outcome line.
    work = tempfile.mkdtemp(prefix="polish-runner-edge-")
    env_file = os.path.join(work, "bash-env.sh")
    with open(env_file, "w") as fh:
        fh.write("set -o functrace\n"
                 "trap 'if [[ \"${FUNCNAME[0]:-}\" == usage_error && \"$BASH_COMMAND\" == exit* ]]; then"
                 " kill -TERM $$; fi' DEBUG\n")
    proc = subprocess.run([RUNNER, "--input", os.path.join(work, "missing.md")],
                          env=fallback_env(work, {"BASH_ENV": env_file}),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    report("SIGTERM right before a usage error exits: one outcome line, exit 143",
           proc.returncode == 143
           and outcome_lines(proc.stderr) == [OUTCOME_PREFIX + "failed reason=usage_error delivered=no"],
           "rc=%s %r" % (proc.returncode, outcome_lines(proc.stderr)))
    shutil.rmtree(work, ignore_errors=True)

    # A group SIGTERM in the moment before a delivery step ignores signals:
    # the step is run again and delivery completes.
    for target in ("stdout", "file"):
        work = tempfile.mkdtemp(prefix="polish-runner-edge-")
        source = os.path.join(work, "input.md")
        out = os.path.join(work, "out.md")
        with open(source, "wb") as fh:
            fh.write(payload)
        flag = os.path.join(work, "fired")
        env_file = os.path.join(work, "bash-env.sh")
        with open(env_file, "w") as fh:
            fh.write("set -o functrace\n"
                     "trap 'if (( BASH_SUBSHELL > 0 )) && [[ \"$BASH_COMMAND\" == \"trap '\"''\"' INT TERM\""
                     " && ! -e \"%s\" ]]; then : > \"%s\"; kill -TERM 0; fi' DEBUG\n" % (flag, flag))
        args = [RUNNER, "--input", source] + (["--output", out] if target == "file" else [])
        proc = subprocess.Popen(args, env=fallback_env(work, {"BASH_ENV": env_file}),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        stdout, err = proc.communicate(timeout=30)
        if target == "file":
            with open(out, "rb") if os.path.exists(out) else open(os.devnull, "rb") as fh:
                got = fh.read()
        else:
            got = stdout
        fired = os.path.exists(flag)
        shutil.rmtree(work, ignore_errors=True)
        report("SIGTERM before a %s delivery step ignores signals: delivered, exit 143" % target,
               fired and proc.returncode == 143 and got == payload and outcome_lines(err) == skipped_yes,
               "fired=%s rc=%s %r exact=%s" % (fired, proc.returncode, outcome_lines(err), got == payload))

    # mv is killed right after the rename: the delivery is still reported.
    work = tempfile.mkdtemp(prefix="polish-runner-edge-")
    source = os.path.join(work, "input.md")
    out = os.path.join(work, "out.md")
    with open(source, "wb") as fh:
        fh.write(payload)
    with open(out, "wb") as fh:
        fh.write(b"old\n")
    shim = os.path.join(work, "bin")
    os.mkdir(shim)
    write_script(os.path.join(shim, "mv"), "#!/bin/bash\n'%s' \"$@\"\nkill -USR1 $$\n" % shutil.which("mv"))
    proc = subprocess.run([RUNNER, "--input", source, "--output", out],
                          env=fallback_env(work, {"PATH": shim + os.pathsep + os.environ["PATH"]}),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    with open(out, "rb") as fh:
        exact = fh.read() == payload
    shutil.rmtree(work, ignore_errors=True)
    report("mv killed after the rename: delivered=yes, exit 0",
           proc.returncode == 0 and exact and outcome_lines(proc.stderr) == skipped_yes,
           "rc=%s %r exact=%s" % (proc.returncode, outcome_lines(proc.stderr), exact))


def only_prefixed(err):
    lines = err.decode("utf-8", "replace").splitlines()
    return all(ln.startswith("polish-gemini: ") for ln in lines)


def fallback_stderr_cases():
    """The fallback's stderr holds only polish-gemini lines, one outcome last."""
    failed_no = [OUTCOME_PREFIX + "failed reason=delivery_error delivered=no"]
    work = tempfile.mkdtemp(prefix="polish-runner-err-")
    fake = OUTCOME_PREFIX + "polished reason=ok delivered=yes"
    bad_tmp = os.path.join(work, "missing") + "\n" + fake + "\n"
    proc = subprocess.run([RUNNER, "--input", "-"], input=b"Original prose.\n",
                          env=fallback_env(work, {"TMPDIR": bad_tmp}),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    report("a TMPDIR carrying a newline and a fake outcome: only prefixed lines, one outcome, exit 4",
           proc.returncode == 4 and only_prefixed(proc.stderr) and outcome_lines(proc.stderr) == failed_no
           and proc.stderr.decode("utf-8", "replace").splitlines()[-1] == failed_no[0] and proc.stdout == b"",
           "rc=%s %r" % (proc.returncode, proc.stderr))
    big = b"Read the source text.\n" * 70000
    limit = lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (8192, 8192))
    proc = subprocess.run([RUNNER, "--input", "-"], input=big, env=fallback_env(work),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=limit, timeout=60)
    report("a stdin copy stopped by the file size limit: no job status line on stderr",
           only_prefixed(proc.stderr) and outcome_lines(proc.stderr) == failed_no, proc.stderr)
    source = os.path.join(work, "input.md")
    with open(source, "wb") as fh:
        fh.write(b"Original prose.\n")
    out = os.path.join(work, "no-such-dir", "out.md")
    proc = subprocess.run([RUNNER, "--input", source, "--output", out], env=fallback_env(work),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    report("an output in a missing directory: only prefixed lines, delivery_error, exit 4",
           proc.returncode == 4 and only_prefixed(proc.stderr) and outcome_lines(proc.stderr) == failed_no,
           "rc=%s %r" % (proc.returncode, proc.stderr))
    shutil.rmtree(work, ignore_errors=True)


def temp_file_signal_cases():
    """A group SIGTERM around the creation of each temporary file leaves none behind."""
    payload = b"Read the source text for the fallback path.\n"
    boundaries = (("before it is created", '":"*'), ("after it is created, before it is registered", '"rc=\\$?"'))
    for prefix, label in (("polish-gemini-config.", "the config message file"),
                          ("polish-gemini-in.", "the stdin copy"),
                          (".polish-gemini-", "the output file")):
        for when, pattern in boundaries:
            work = tempfile.mkdtemp(prefix="polish-runner-tmp-")
            tmp_dir = os.path.join(work, "tmp")
            out_dir = os.path.join(work, "out")
            os.mkdir(tmp_dir)
            os.mkdir(out_dir)
            source = os.path.join(work, "input.md")
            out = os.path.join(out_dir, "out.md")
            with open(source, "wb") as fh:
                fh.write(payload)
            with open(out, "wb") as fh:
                fh.write(b"old\n")
            flag = os.path.join(work, "fired")
            env_file = os.path.join(work, "bash-env.sh")
            with open(env_file, "w") as fh:
                fh.write("set -o functrace\n"
                         "trap 'if [[ ! -e \"%s\" && \"${FUNCNAME[0]:-}\" == make_temp"
                         " && \"${prefix:-}\" == \"%s\" && \"$BASH_COMMAND\" == %s ]];"
                         " then : >| \"%s\"; kill -TERM 0; fi' DEBUG\n" % (flag, prefix, pattern, flag))
            env = fallback_env(work, {"BASH_ENV": env_file, "TMPDIR": tmp_dir})
            if prefix == "polish-gemini-in.":
                args, stdin = [RUNNER, "--input", "-"], payload
            elif prefix == ".polish-gemini-":
                args, stdin = [RUNNER, "--input", source, "--output", out], None
            else:
                args, stdin = [RUNNER, "--input", source], None
            proc = subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, start_new_session=True)
            stdout, err = proc.communicate(input=stdin, timeout=60)
            fired = os.path.exists(flag)
            leftovers = [f for f in os.listdir(tmp_dir)] + [f for f in os.listdir(out_dir) if f != "out.md"]
            with open(out, "rb") as fh:
                dest = fh.read()
            shutil.rmtree(work, ignore_errors=True)
            if prefix == ".polish-gemini-":
                # Delivery is under way: it finishes, then the signal is reported.
                expected = [OUTCOME_PREFIX + "skipped reason=missing_dependency delivered=yes"]
                delivered_ok = dest == payload
            else:
                expected = [OUTCOME_PREFIX + "failed reason=interrupted delivered=no"]
                delivered_ok = stdout == b"" and dest == b"old\n"
            report("SIGTERM %s for %s: no temporary file left, truthful outcome, exit 143" % (when, label),
                   fired and proc.returncode == 143 and not leftovers and delivered_ok
                   and outcome_lines(err) == expected and only_prefixed(err),
                   "fired=%s rc=%s leftovers=%r %r" % (fired, proc.returncode, leftovers, outcome_lines(err)))


def shell_step_cases():
    """Delivery steps run once, cleanup survives a group signal, and a failed
    exec of Python still delivers the original."""
    payload = b"Read the source text for the fallback path.\n"
    path = os.environ["PATH"]

    # A step whose command writes and then exits with 143 is a failure, never
    # run a second time.
    for target in ("stdout", "file"):
        work = tempfile.mkdtemp(prefix="polish-runner-step-")
        source = os.path.join(work, "input.md")
        out = os.path.join(work, "out.md")
        with open(source, "wb") as fh:
            fh.write(payload)
        with open(out, "wb") as fh:
            fh.write(b"old\n")
        shim = os.path.join(work, "bin")
        os.mkdir(shim)
        flag = os.path.join(work, "cat.flag")
        write_script(os.path.join(shim, "cat"),
                     "#!/bin/bash\nif [[ ! -e '%s' ]]; then : > '%s'; '%s' \"$@\"; exit 143; fi\n"
                     "exec '%s' \"$@\"\n" % (flag, flag, shutil.which("cat"), shutil.which("cat")))
        args = [RUNNER, "--input", source] + (["--output", out] if target == "file" else [])
        proc = subprocess.run(args, env=fallback_env(work, {"PATH": shim + os.pathsep + path}),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        with open(out, "rb") as fh:
            dest = fh.read()
        leftovers = [f for f in os.listdir(work) if f.startswith(".polish-gemini-")]
        shutil.rmtree(work, ignore_errors=True)
        if target == "stdout":
            written_once = proc.stdout == payload
        else:
            written_once = proc.stdout == b"" and dest == b"old\n" and not leftovers
        report("a %s copy that writes and exits 143 is not run again: delivery_error, exit 4" % target,
               proc.returncode == 4 and written_once and only_prefixed(proc.stderr)
               and outcome_lines(proc.stderr) == [OUTCOME_PREFIX + "failed reason=delivery_error delivered=no"],
               "rc=%s %d bytes leftovers=%r %r" % (proc.returncode, len(proc.stdout), leftovers,
                                                  outcome_lines(proc.stderr)))

    # A group SIGTERM while cleanup removes a temporary file: the removal
    # still runs and no temporary file is left. After a fallback delivery the
    # outcome reports the delivered original; in the cleanup right before the
    # Python handoff the run ends as interrupted with nothing delivered.
    for prefix, python, expected, want_out in (
            ("polish-gemini-config.", None, "skipped reason=missing_dependency delivered=yes", payload),
            ("polish-gemini-in.", None, "skipped reason=missing_dependency delivered=yes", payload),
            ("polish-gemini-config.", sys.executable, "failed reason=interrupted delivered=no", b"")):
        work = tempfile.mkdtemp(prefix="polish-runner-step-")
        tmp_dir = os.path.join(work, "tmp")
        os.mkdir(tmp_dir)
        shim = os.path.join(work, "bin")
        os.mkdir(shim)
        flag = os.path.join(work, "rm.flag")
        write_script(os.path.join(shim, "rm"),
                     "#!/bin/bash\nif [[ ! -e '%s' && \"${2:-}\" == */%s* ]]; then : > '%s'; kill -TERM 0; fi\n"
                     "exec '%s' \"$@\"\n" % (flag, prefix, flag, shutil.which("rm")))
        proc = subprocess.Popen([RUNNER, "--input", "-"],
                                env=fallback_env(work, dict({"PATH": shim + os.pathsep + path, "TMPDIR": tmp_dir},
                                                            **({"HUMANIZE_POLISH_PYTHON": python} if python else {}))),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        stdout, err = proc.communicate(input=payload, timeout=60)
        fired = os.path.exists(flag)
        leftovers = os.listdir(tmp_dir)
        shutil.rmtree(work, ignore_errors=True)
        report("a group SIGTERM while cleanup removes %s (%s): no temporary file left, %s, exit 143"
               % (prefix + "*", "before the Python handoff" if python else "after delivery",
                  expected.split(" ")[0]),
               fired and proc.returncode == 143 and stdout == want_out and not leftovers and only_prefixed(err)
               and outcome_lines(err) == [OUTCOME_PREFIX + expected],
               "fired=%s rc=%s leftovers=%r %r" % (fired, proc.returncode, leftovers, outcome_lines(err)))

    # The Python interpreter passes the version check and is gone when the
    # wrapper execs it: the original is delivered with one outcome line and
    # no raw shell error.
    for target in ("stdout", "file"):
        work = tempfile.mkdtemp(prefix="polish-runner-step-")
        source = os.path.join(work, "input.md")
        out = os.path.join(work, "out.md")
        with open(source, "wb") as fh:
            fh.write(payload)
        vanishing = os.path.join(work, "vanishing-python3")
        write_script(vanishing, "#!/bin/bash\nrm -f \"$0\"\nexec '%s' \"$@\"\n" % sys.executable)
        args = [RUNNER, "--input", source] + (["--output", out] if target == "file" else [])
        proc = subprocess.run(args, env=fallback_env(work, {"HUMANIZE_POLISH_PYTHON": vanishing}),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if target == "stdout":
            delivered = proc.stdout == payload
        else:
            delivered = os.path.exists(out) and proc.stdout == b""
            if delivered:
                with open(out, "rb") as fh:
                    delivered = fh.read() == payload
        lines = proc.stderr.decode("utf-8", "replace").splitlines()
        report("a Python interpreter gone at exec (%s): original delivered, one outcome, exit 0" % target,
               proc.returncode == 0 and delivered and only_prefixed(proc.stderr) and lines
               and lines[-1] == OUTCOME_PREFIX + "skipped reason=missing_dependency delivered=yes"
               and len(outcome_lines(proc.stderr)) == 1,
               "rc=%s %r" % (proc.returncode, proc.stderr))
        shutil.rmtree(work, ignore_errors=True)


def plugin_copy(work):
    """A scratch copy of the plugin files the wrapper needs."""
    root = os.path.join(work, "plugin")
    for name in ("scripts", "config", "prompt-template"):
        shutil.copytree(os.path.join(ROOT, name), os.path.join(root, name))
    return root


def startup_cases():
    """Cleanup retries, a missing helper, and signals while Python starts."""
    payload = b"Read the source text for the startup path.\n"
    path = os.environ["PATH"]

    # A removal that fails once is tried again: no temporary file is left,
    # after a fallback delivery or before the Python handoff.
    for prefix, python, expected in (
            ("polish-gemini-in.", None, "skipped reason=missing_dependency delivered=yes"),
            ("polish-gemini-config.", sys.executable, "skipped reason=no_api_key delivered=yes")):
        work = tempfile.mkdtemp(prefix="polish-runner-start-")
        tmp_dir = os.path.join(work, "tmp")
        os.mkdir(tmp_dir)
        shim = os.path.join(work, "bin")
        os.mkdir(shim)
        flag = os.path.join(work, "rm.flag")
        write_script(os.path.join(shim, "rm"),
                     "#!/bin/bash\nif [[ ! -e '%s' && \"${2:-}\" == */%s* ]]; then : > '%s'; exit 1; fi\n"
                     "exec '%s' \"$@\"\n" % (flag, prefix, flag, shutil.which("rm")))
        extra = {"PATH": shim + os.pathsep + path, "TMPDIR": tmp_dir}
        if python:
            extra["HUMANIZE_POLISH_PYTHON"] = python
        proc = subprocess.run([RUNNER, "--input", "-"], env=fallback_env(work, extra), input=payload,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        fired = os.path.exists(flag)
        leftovers = os.listdir(tmp_dir)
        shutil.rmtree(work, ignore_errors=True)
        report("a removal of %s that fails once is retried: no temporary file left, exit 0" % (prefix + "*"),
               fired and proc.returncode == 0 and proc.stdout == payload and not leftovers
               and only_prefixed(proc.stderr) and outcome_lines(proc.stderr) == [OUTCOME_PREFIX + expected],
               "fired=%s rc=%s leftovers=%r %r" % (fired, proc.returncode, leftovers, outcome_lines(proc.stderr)))

    # A removal that keeps failing is reported on stderr before the outcome
    # line; the delivery itself is unaffected.
    work = tempfile.mkdtemp(prefix="polish-runner-start-")
    tmp_dir = os.path.join(work, "tmp")
    os.mkdir(tmp_dir)
    shim = os.path.join(work, "bin")
    os.mkdir(shim)
    write_script(os.path.join(shim, "rm"),
                 "#!/bin/bash\nif [[ \"${2:-}\" == */polish-gemini-in.* ]]; then exit 1; fi\n"
                 "exec '%s' \"$@\"\n" % shutil.which("rm"))
    proc = subprocess.run([RUNNER, "--input", "-"],
                          env=fallback_env(work, {"PATH": shim + os.pathsep + path, "TMPDIR": tmp_dir}),
                          input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    leftovers = os.listdir(tmp_dir)
    shutil.rmtree(work, ignore_errors=True)
    lines = proc.stderr.decode("utf-8", "replace").splitlines()
    report("a removal that keeps failing is reported before the one outcome line",
           proc.returncode == 0 and proc.stdout == payload and only_prefixed(proc.stderr)
           and any("could not remove the temporary file" in ln for ln in lines) and len(leftovers) == 1
           and lines[-1] == OUTCOME_PREFIX + "skipped reason=missing_dependency delivered=yes"
           and len(outcome_lines(proc.stderr)) == 1,
           "rc=%s leftovers=%r %r" % (proc.returncode, leftovers, proc.stderr))

    # The Python helper is missing from the plugin: the wrapper delivers the
    # original itself.
    work = tempfile.mkdtemp(prefix="polish-runner-start-")
    root = plugin_copy(work)
    os.unlink(os.path.join(root, "scripts", "lib", "polish_gemini.py"))
    proc = subprocess.run([os.path.join(root, "scripts", "polish-gemini.sh"), "--input", "-"],
                          env=fallback_env(work, {"HUMANIZE_POLISH_PYTHON": sys.executable}), input=payload,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    shutil.rmtree(work, ignore_errors=True)
    report("a missing Python helper: original delivered, missing_dependency, exit 0",
           proc.returncode == 0 and proc.stdout == payload and only_prefixed(proc.stderr)
           and outcome_lines(proc.stderr) == [OUTCOME_PREFIX + "skipped reason=missing_dependency delivered=yes"],
           "rc=%s %r" % (proc.returncode, proc.stderr))

    # A signal while Python imports its modules (before the run installs its
    # handlers) still ends with one interrupted outcome and exit 130 or 143.
    for signame, code in (("SIGTERM", 143), ("SIGINT", 130)):
        work = tempfile.mkdtemp(prefix="polish-runner-start-")
        root = plugin_copy(work)
        guard_py = os.path.join(root, "scripts", "lib", "polish_guard.py")
        with open(guard_py) as fh:
            body = fh.read()
        with open(guard_py, "w") as fh:
            fh.write("import os as _o, signal as _s\n_o.kill(_o.getpid(), _s.%s)\n" % signame + body)
        source = os.path.join(work, "input.md")
        with open(source, "wb") as fh:
            fh.write(payload)
        proc = subprocess.run([os.path.join(root, "scripts", "polish-gemini.sh"), "--input", source],
                              env=fallback_env(work, {"HUMANIZE_POLISH_PYTHON": sys.executable,
                                                      "OPENROUTER_API_KEY": DUMMY_KEY}),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        shutil.rmtree(work, ignore_errors=True)
        report("%s while Python starts: one interrupted outcome, nothing delivered, exit %d" % (signame, code),
               proc.returncode == code and proc.stdout == b"" and only_prefixed(proc.stderr)
               and outcome_lines(proc.stderr) == [OUTCOME_PREFIX + "failed reason=interrupted delivered=no"],
               "rc=%s %r" % (proc.returncode, proc.stderr))

    # A SIGTERM in the moment the wrapper execs Python is ignored rather than
    # ending the run without an outcome line.
    work = tempfile.mkdtemp(prefix="polish-runner-start-")
    shim = os.path.join(work, "python-shim")
    write_script(shim, "#!/bin/bash\nif [[ \"${3:-}\" == */polish_gemini.py ]]; then kill -TERM $$; fi\n"
                       "exec '%s' \"$@\"\n" % sys.executable)
    proc = subprocess.run([RUNNER, "--input", "-"], env=fallback_env(work, {"HUMANIZE_POLISH_PYTHON": shim}),
                          input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    shutil.rmtree(work, ignore_errors=True)
    report("a SIGTERM during the exec of Python: exactly one outcome line",
           proc.stdout == payload and only_prefixed(proc.stderr) and len(outcome_lines(proc.stderr)) == 1
           and proc.returncode == 0,
           "rc=%s %r" % (proc.returncode, proc.stderr))


def interruption_window_cases():
    """A signal right after the run installs its handlers, or a second one
    while the interruption is handled, still gives one interrupted outcome."""
    for mode, label in (("signal_after_handlers", "right after the handlers are installed"),
                        ("signal_twice", "twice, the second before signals are deferred"),
                        ("signal_in_except", "twice, the second in the handler of the first")):
        r = run_child(mode)
        lines = r["err"].splitlines()
        report("SIGTERM %s: one interrupted outcome, exit 143, no raw stderr" % label,
               r["rc"] == 143 and r["outcomes"] == [OUTCOME_PREFIX + "failed reason=interrupted delivered=no"]
               and all(ln.startswith("polish-gemini: ") for ln in lines) and lines[-1] == r["outcomes"][0],
               "rc=%s %r" % (r["rc"], r["err"][-300:]))


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
    fallback_edge_cases()
    fallback_stderr_cases()
    temp_file_signal_cases()
    shell_step_cases()
    startup_cases()
    interruption_window_cases()
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3])
    else:
        main()
