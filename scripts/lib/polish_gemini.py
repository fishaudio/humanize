#!/usr/bin/env python3
"""polish_gemini - readability-only polish with Gemini.

Internal helper for scripts/polish-gemini.sh. The shell wrapper parses the
public command line and the merged humanize config, then runs this module with
resolved settings. This module:

1. reads the source bytes (a file or stdin);
2. checks them (size, encoding, marker collisions, format-specific parsing);
3. gets one reply from the selected backend:
   - agy: one headless run of the Antigravity CLI on the signed-in Gemini
     subscription, from an empty temporary workspace, with every tool refused
     (strict tool permission, deny rules, and a deny-all PreToolUse hook) and
     the prompt on standard input;
   - openrouter: one chat completions request with no tools, plus at most one
     retry (effort fallback or rate limiting), with the API key resolved
     inside this process;
   both under one overall deadline. An agy failure falls back to OpenRouter
   only when the caller asks for it;
4. verifies the candidate with polish_guard;
5. delivers either the polished text or the exact original bytes;
6. writes the run record and prints exactly one outcome line on stderr.

Standard library only. The API key never appears on a command line, in a run
record, in a cache file, on stdout, or on stderr, and agy never receives it.
"""

import sys

sys.dont_write_bytecode = True


import os  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402

# SIGINT and SIGTERM received before the run installs its own handlers.
_STARTUP_SIGNALS = []
# Set when the shell wrapper supervises the start (HUMANIZE_POLISH_SUPERVISOR):
# (wrapper pid, descriptor that reports readiness, signal that releases the
# run); None when the setting cannot be used.
_SUPERVISOR = []
_RELEASED = []
# Seconds to wait for the release before giving up; the wrapper then
# delivers the original itself.
RELEASE_WAIT_LIMIT = 60.0


def _adopt_stderr():
    """Take the caller's standard error from the descriptor the shell wrapper
    kept it on (HUMANIZE_POLISH_STDERR_FD). Until then standard error is the
    wrapper's /dev/null, so a failed start or import prints nothing raw.
    """
    value = os.environ.pop("HUMANIZE_POLISH_STDERR_FD", None)
    if value is None or not re.fullmatch(r"[0-9]+", value) or int(value) < 3:
        return
    fd = int(value)
    try:
        os.dup2(fd, 2)
    except OSError:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _record_startup_signal(signum, frame):
    _STARTUP_SIGNALS.append(signum)


def _catch_startup_signals():
    """Record SIGINT and SIGTERM from the first statements on; the run acts on
    them once its own handlers are in place, so an interruption while Python
    starts still ends with one outcome line. The shell wrapper ignores both
    signals across the exec and names the ones this process must handle in
    HUMANIZE_POLISH_SIGNALS; a signal it does not name was ignored when the
    run started and stays ignored. Without the wrapper, every signal that is
    not ignored is caught."""
    names = os.environ.pop("HUMANIZE_POLISH_SIGNALS", None)
    table = {"INT": signal.SIGINT, "TERM": signal.SIGTERM}
    if names is None:
        wanted = [s for s in table.values() if signal.getsignal(s) != signal.SIG_IGN]
    else:
        wanted = [table[x] for x in names.split(",") if x in table]
    for signum in wanted:
        signal.signal(signum, _record_startup_signal)


def _record_release(signum, frame):
    _RELEASED.append(signum)


# How often a supervised run checks that its wrapper still exists while it
# waits for a reply.
SUPERVISOR_POLL = 0.5


def _supervisor_gone():
    """True when the supervising wrapper has ended (for example killed with
    SIGKILL): this process was given another parent. The run then ends as
    interrupted and delivers nothing, as the runner's own process is gone."""
    return bool(_SUPERVISOR) and _SUPERVISOR[0] is not None and os.getppid() != _SUPERVISOR[0][0]


def _ignore_signal(signum, frame):
    pass


def _read_supervisor():
    """Read HUMANIZE_POLISH_SUPERVISOR ("PID:FD:RELEASE": the wrapper's
    process ID, the write end of the pipe that reports readiness, and the
    release signal, USR1 or USR2) and catch the release signal from here on,
    so it cannot end the process."""
    value = os.environ.pop("HUMANIZE_POLISH_SUPERVISOR", None)
    if value is None:
        return
    names = {"USR1": signal.SIGUSR1, "USR2": signal.SIGUSR2}
    m = re.fullmatch(r"([0-9]{1,9}):([0-9]{1,4}):(USR1|USR2)", value)
    if not m or int(m.group(2)) < 3:
        # A wrapper that asked for supervision but cannot be answered: the
        # run must not go ahead unsupervised.
        _SUPERVISOR.append(None)
        return
    _SUPERVISOR.append((int(m.group(1)), int(m.group(2)), names[m.group(3)]))
    signal.signal(names[m.group(3)], _record_release)


def _close_ready_pipe():
    """Close the readiness pipe, so the wrapper sees end of file if it still
    waits for readiness."""
    if _SUPERVISOR and _SUPERVISOR[0] is not None:
        try:
            os.close(_SUPERVISOR[0][1])
        except OSError:
            pass


def _await_release(handled):
    """The start handshake with the supervising shell wrapper.

    The wrapper keeps its SIGINT and SIGTERM traps while this process starts.
    Once its handlers are in place (``handled`` are the signals it catches),
    this process blocks them, tells the wrapper it is ready (one byte on the
    readiness pipe), and waits for the release before it reads any input. A
    SIGINT or SIGTERM that arrives meanwhile is recorded, and the run then
    ends as interrupted; the wrapper
    sends a signal it received before readiness the same way, followed by
    the release. Returns False when the wrapper is gone or does not answer:
    the process must then end without delivering anything.
    """
    if not _SUPERVISOR:
        return True
    if _SUPERVISOR[0] is None:
        return False
    pid, ready_fd, release = _SUPERVISOR[0]
    if os.getppid() != pid:
        _close_ready_pipe()
        return False
    waited = set(handled) | {release, signal.SIGALRM}
    old_alarm = signal.signal(signal.SIGALRM, _ignore_signal)
    signal.pthread_sigmask(signal.SIG_BLOCK, waited)
    ok = True
    try:
        try:
            if os.write(ready_fd, b"R") != 1:
                raise OSError("short write")
        finally:
            _close_ready_pipe()
        deadline = time.monotonic() + RELEASE_WAIT_LIMIT
        signal.setitimer(signal.ITIMER_REAL, 0.5, 0.5)
        while not _RELEASED:
            signum = signal.sigwait(waited)
            if signum == release:
                break
            if signum == signal.SIGALRM:
                if os.getppid() != pid or time.monotonic() > deadline:
                    ok = False
                    break
                continue
            _STARTUP_SIGNALS.append(signum)
    except OSError:
        ok = False
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0, 0)
        # A signal still pending reaches its handler here: a startup signal
        # is recorded, a timer tick is ignored.
        signal.pthread_sigmask(signal.SIG_UNBLOCK, waited)
        signal.signal(signal.SIGALRM, old_alarm)
    return ok


if __name__ == "__main__":
    _catch_startup_signals()
    _read_supervisor()

import email.utils  # noqa: E402
import json  # noqa: E402
import secrets  # noqa: E402
import shlex  # noqa: E402
import shutil  # noqa: E402
import socket  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402

LIB_DIR = os.path.dirname(os.path.abspath(__file__))
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import polish_guard as guard  # noqa: E402

PREFIX = "polish-gemini:"
MARKER_FAMILY = "@@HUMANIZE-POLISH-"
EFFORTS = ("xhigh", "high", "medium", "low")
FORMATS = ("markdown", "text", "segments", "html")
BACKENDS = ("agy", "openrouter")
MAX_POSTS = 2
DEFAULT_RETRY_AFTER = 2.0
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_STRICT = 3
EXIT_DELIVERY = 4

FORMAT_NAMES = {
    "markdown": "Markdown",
    "text": "plain text",
    "segments": "segments",
    "html": "segments taken from an HTML page",
}
REJECTION_WORDS = ("unsupported", "not supported", "invalid", "must be one of",
                   "allowed values", "not allowed", "unknown", "enum", "expected one of",
                   "not a valid", "is not one of")

# agy (Antigravity CLI) settings for one polish run. They apply to this run
# only and are never saved. Under "strict" every tool call needs an approval
# that a headless run cannot give, so agy refuses it; the deny rules refuse
# the tools that permission rules cover even before that, and an empty
# agentMode keeps Auto mode from approving anything. useG1Credits stays off so
# a used-up subscription quota never turns into paid AI credits.
AGY_SETTINGS = {
    "toolPermission": "strict",
    "agentMode": "",
    "allowNonWorkspaceAccess": False,
    "trustedWorkspaces": [],
    "useG1Credits": False,
    "permissions": {
        "allow": [],
        "deny": ["command(*)", "write_file(*)", "read_file(*)", "read_url(*)", "mcp(*)"],
    },
}
# Workspace hook that refuses every tool call, including the tools that
# permission rules do not cover (web search, subagents, scheduling).
AGY_HOOKS = {
    "humanize-polish-no-tools": {
        "PreToolUse": [{
            "matcher": "*",
            "hooks": [{
                "type": "command",
                "command": "printf '%s\\n' '{\"decision\":\"deny\",\"reason\":\"Polish runs allow no tools.\"}'",
                "timeout": 10,
            }],
        }],
    },
}
AGY_PREFACE = ("Your only task is the copy-editing request below. Do not call any tool: every tool "
               "call in this session is refused. Answer with the output block only.\n\n")
# Credentials agy must not see: the OpenRouter key is not its business, and a
# Gemini API key or Application Default Credentials would bill per call
# instead of using the signed-in subscription.
AGY_ENV_DROP = ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                "GOOGLE_APPLICATION_CREDENTIALS", "AGY_ADC_AUTH")
# Seconds agy gets past its own --print-timeout before it is killed.
AGY_KILL_GRACE = 10.0
AGY_LABEL_RE = re.compile(r'label="([^"\n]+)"')
AGY_HINTS = {
    "auth": " (agy is not signed in: run agy once in a terminal and sign in with the account "
            "that has your Gemini subscription)",
    "quota_exhausted": " (the Gemini subscription quota is used up: wait for it to reset, lower the "
                       "effort, or set gemini_polish_fallback_to_openrouter to true to pay per call "
                       "on OpenRouter)",
    "bad_model": " (run agy models to list the models agy offers, then set gemini_polish_agy_model)",
}


class Interrupted(BaseException):
    def __init__(self, signum):
        BaseException.__init__(self, signum)
        self.signum = signum


class Stop(Exception):
    """Ends a run before delivery; the original bytes are delivered."""

    def __init__(self, outcome, reason, detail=""):
        Exception.__init__(self, "%s %s %s" % (outcome, reason, detail))
        self.outcome = outcome
        self.reason = reason
        self.detail = detail


class UsageError(Exception):
    pass


_INTERRUPTING = []


def _raise_interrupt(signum, frame):
    # Raise once per process: a later signal is only recorded, so it cannot
    # escape the handler of the first one.
    if _INTERRUPTING:
        _DEFERRED_SIGNALS.append(signum)
        return
    _INTERRUPTING.append(signum)
    raise Interrupted(signum)


_DEFERRED_SIGNALS = []

# A signal that was ignored when the process started (for example SIGINT in a
# background job started by a non-interactive shell) stays ignored, as it does
# in the shell wrapper, which cannot trap such a signal.
_HANDLED_SIGNALS = tuple(s for s in (signal.SIGINT, signal.SIGTERM)
                         if signal.getsignal(s) != signal.SIG_IGN)


def _set_signal_handlers(handler):
    for signum in _HANDLED_SIGNALS:
        signal.signal(signum, handler)


def _defer_signal(signum, frame):
    _DEFERRED_SIGNALS.append(signum)


def _block_signals():
    """Defer SIGINT and SIGTERM until exit (main thread only)."""
    _set_signal_handlers(_defer_signal)


def _exit_code_for(signum):
    return 130 if signum == signal.SIGINT else 143


_CONTROL_RE = re.compile("[\x00-\x1f\x7f\x85\u2028\u2029]+")


def one_line(text, limit=1000):
    """Make untrusted text safe for a single diagnostic line.

    Control characters and line separators become spaces, the text is
    truncated, and it never starts like the outcome line.
    """
    text = _CONTROL_RE.sub(" ", str(text))
    if len(text) > limit:
        text = text[:limit] + "..."
    if text.lstrip().startswith("outcome="):
        text = "note: " + text
    return text


def emit_outcome(outcome, reason, delivered):
    """Print the final outcome line on stderr."""
    sys.stderr.write("%s outcome=%s reason=%s delivered=%s\n"
                     % (PREFIX, outcome, reason, "yes" if delivered else "no"))
    sys.stderr.flush()


def _mask_signals_in_thread():
    """Keep signals away from worker threads so the main thread sees them at once."""
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    except (AttributeError, OSError, ValueError):
        pass


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


# ----------------------------------------------------------------------------
# Option parsing (internal interface; the shell wrapper validates user input)
# ----------------------------------------------------------------------------

VALUE_OPTIONS = ("input", "output", "format", "model", "effort", "timeout", "max-tokens",
                 "max-bytes", "base-url", "api-key-file", "project-root", "template-dir",
                 "skip-reason", "block-ratio", "doc-ratio", "source-label", "backend",
                 "agy-bin", "agy-model")
FLAG_OPTIONS = ("strict", "fallback-openrouter")


def parse_options(argv):
    opts = {
        "input": None, "output": "", "format": "", "model": "", "effort": "xhigh",
        "timeout": "900", "max-tokens": "131072", "max-bytes": "262144", "base-url": "",
        "api-key-file": "", "project-root": "", "template-dir": "", "skip-reason": "",
        "block-ratio": "", "doc-ratio": "", "source-label": "", "strict": False,
        "backend": "openrouter", "agy-bin": "", "agy-model": "gemini-4-neon",
        "fallback-openrouter": False,
    }
    i = 0
    while i < len(argv):
        arg = argv[i]
        if not arg.startswith("--"):
            raise UsageError("unexpected argument: %s" % arg)
        name = arg[2:]
        if name in FLAG_OPTIONS:
            opts[name] = True
            i += 1
            continue
        if name not in VALUE_OPTIONS:
            raise UsageError("unknown option: %s" % arg)
        if i + 1 >= len(argv):
            raise UsageError("%s requires a value" % arg)
        opts[name] = argv[i + 1]
        i += 2
    if opts["input"] is None:
        raise UsageError("--input is required")
    for name in ("timeout", "max-tokens", "max-bytes"):
        if not re.match(r"^[1-9][0-9]*$", opts[name]):
            raise UsageError("--%s must be a positive integer" % name)
    if opts["effort"] not in EFFORTS:
        raise UsageError("--effort must be one of %s" % ", ".join(EFFORTS))
    if opts["format"] and opts["format"] not in FORMATS:
        raise UsageError("--format must be one of %s" % ", ".join(FORMATS))
    if opts["backend"] not in BACKENDS:
        raise UsageError("--backend must be one of %s" % ", ".join(BACKENDS))
    if opts["backend"] == "agy" and not re.match(r"^[A-Za-z0-9._-]+$", opts["agy-model"]):
        raise UsageError("--agy-model must be an agy model name such as gemini-4-neon")
    if opts["backend"] == "openrouter" or opts["fallback-openrouter"]:
        if not opts["model"] or opts["model"].endswith(":online"):
            raise UsageError("a model ID is required and must not end in :online")
        if not opts["base-url"]:
            raise UsageError("--base-url is required")
    return opts


def detect_format(path):
    lowered = path.lower()
    if lowered.endswith((".html", ".htm")):
        return "html"
    if lowered.endswith((".md", ".markdown")):
        return "markdown"
    return "text"


def parse_key_text(text):
    """Return the key from a key file's text, or None."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    assign_re = re.compile(r"^(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(.*)$")
    value = None
    if len(lines) == 1 and not assign_re.match(lines[0]):
        value = lines[0]
    else:
        matches = []
        for ln in lines:
            m = assign_re.match(ln)
            if m and m.group(1) == "OPENROUTER_API_KEY":
                matches.append(m.group(2).strip())
        if len(matches) == 1:
            value = matches[0]
    if value is None:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value if valid_key(value) else None


def valid_key(value):
    return bool(value) and bool(re.match(r"^[\x21-\x7e]+$", value))


def _error_obj(raw_body):
    """The "error" object of a JSON error body, or {} when there is none."""
    try:
        data = json.loads(raw_body.decode("utf-8", "replace"))
    except ValueError:
        return {}
    err = data.get("error") if isinstance(data, dict) else None
    return err if isinstance(err, dict) else {}


def is_effort_rejection(raw_body):
    """True only when an HTTP 400 body explicitly rejects the effort value xhigh."""
    err = _error_obj(raw_body)
    texts = []
    if isinstance(err.get("message"), str):
        texts.append(err["message"])
    meta = err.get("metadata")
    if isinstance(meta, dict):
        raw = meta.get("raw")
        if isinstance(raw, str):
            texts.append(raw)
        elif raw is not None:
            texts.append(json.dumps(raw))
    for text in texts:
        lowered = text.lower()
        if "effort" in lowered and "xhigh" in lowered and any(w in lowered for w in REJECTION_WORDS):
            return True
    return False


def parse_retry_after(value):
    if not value:
        return DEFAULT_RETRY_AFTER
    value = value.strip()
    if re.match(r"^[0-9]+(?:\.[0-9]+)?$", value):
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return DEFAULT_RETRY_AFTER
    if when is None:
        return DEFAULT_RETRY_AFTER
    return max(0.0, when.timestamp() - time.time())


def classify_status(status):
    if status in (401, 403):
        return "auth"
    if status == 402:
        return "insufficient_credits"
    if status == 408:
        return "timeout"
    if status == 429:
        return "rate_limited"
    if 500 <= status <= 599:
        return "provider_error"
    return "api_error"


def classify_exception(exc):
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(exc, urllib.error.URLError) and isinstance(
            getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
        return "timeout"
    return "network"


def api_error_message(raw_body):
    msg = _error_obj(raw_body).get("message")
    # Not truncated here: diag() redacts the key first, then truncates.
    return msg if isinstance(msg, str) else ""


def classify_agy_error(text):
    """Map an agy error message (result error plus stderr) to a reason code."""
    t = text.lower()
    if any(w in t for w in ("authentication", "not signed in", "sign in", "log in", "login",
                            "unauthenticated", "oauth")):
        return "auth"
    if any(w in t for w in ("not recognized as a known model", "invalid model", "unknown model")):
        return "bad_model"
    if any(w in t for w in ("quota", "resource_exhausted", "resource exhausted", "exhausted",
                            "spend cap", "out of credits", "prepaid", "usage limit")):
        return "quota_exhausted"
    if any(w in t for w in ("rate limit", "rate-limit", "too many requests", "429")):
        return "rate_limited"
    if any(w in t for w in ("timed out", "timeout", "deadline exceeded")):
        return "timeout"
    if any(w in t for w in ("network", "connection", "dial tcp", "no such host", "proxy")):
        return "network"
    return "agy_error"


def agy_model_label(log_path):
    """The last model label agy sent to its backend, read from its log, or ""."""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            labels = AGY_LABEL_RE.findall(fh.read())
    except OSError:
        return ""
    return labels[-1] if labels else ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects, so the Authorization header stays with the configured host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_post(url, body, headers, timeout):
    """POST and return (status, lowercased headers, body bytes). Raises on transport errors."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    handlers = [_NoRedirect()]
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read()
        except Exception:
            payload = b""
        hdrs = {}
        if exc.headers is not None:
            hdrs = dict((k.lower(), v) for k, v in exc.headers.items())
        return exc.code, hdrs, payload
    try:
        payload = response.read()
        hdrs = dict((k.lower(), v) for k, v in response.headers.items())
        return response.status, hdrs, payload
    finally:
        response.close()


# ----------------------------------------------------------------------------
# Run records
# ----------------------------------------------------------------------------


class Record(object):
    """Run record under .humanize/skill/<id>/ plus the cache directory."""

    def __init__(self, runner, skill_dir, cache_dir):
        self.runner = runner
        self.skill_dir = skill_dir
        self.cache_dir = cache_dir
        self.broken = False

    @classmethod
    def create(cls, runner, project_root):
        run_id = "%s-%d-%s" % (time.strftime("%Y-%m-%d_%H-%M-%S"), os.getpid(), secrets.token_hex(4))
        skill_dir = os.path.join(project_root, ".humanize", "skill", run_id)
        os.makedirs(skill_dir)
        sanitized = re.sub(r"-+", "-", re.sub(r"[^a-zA-Z0-9._-]", "-", project_root))
        cache_base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        cache_dir = os.path.join(cache_base, "humanize", sanitized, "skill-" + run_id)
        try:
            os.makedirs(cache_dir)
        except OSError:
            cache_dir = os.path.join(skill_dir, "cache")
            os.makedirs(cache_dir)
            runner.diag("warning: home cache not writable, using %s" % cache_dir)
        return cls(runner, skill_dir, cache_dir)

    def _write(self, directory, name, data, atomic=False):
        """Write one record file. Never raises: records are optional."""
        if self.broken:
            return
        path = os.path.join(directory, name)
        tmp = None
        try:
            if isinstance(data, str):
                data = self.runner.redact(data).encode("utf-8", "backslashreplace")
            if atomic:
                fd, tmp = tempfile.mkstemp(prefix="." + name + ".", dir=directory)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, path)
                tmp = None
            else:
                with open(path, "wb") as fh:
                    fh.write(data)
        except Exception as exc:  # any failure only disables records
            self.broken = True
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            detail = getattr(exc, "strerror", None) or exc
            sys.stderr.write("%s %s\n" % (PREFIX, one_line(
                "records=unavailable (could not write %s: %s)" % (name, self.runner.redact(str(detail))))))

    def write_input(self, text):
        self._write(self.skill_dir, "input.md", text)

    def write_skill_file(self, name, data):
        self._write(self.skill_dir, name, data)

    def write_cache_file(self, name, data):
        self._write(self.cache_dir, name, data)

    def log(self, text):
        if self.broken:
            return
        try:
            with open(os.path.join(self.cache_dir, "gemini-run.log"), "a", encoding="utf-8",
                      errors="backslashreplace") as fh:
                fh.write("[%s] %s\n" % (_iso(time.time()), one_line(self.runner.redact(text))))
        except Exception:
            pass

    def write_metadata(self, fields):
        lines = ["---"]
        for key, value in fields:
            lines.append("%s: %s" % (key, value))
        lines.append("---")
        self._write(self.skill_dir, "metadata.md", "\n".join(lines) + "\n", atomic=True)


# ----------------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------------


class Runner(object):
    def __init__(self, opts):
        self.opts = opts
        self.key = None
        self.record = None
        self.delivered = False
        self.outcome_emitted = False
        self.temp_paths = []
        self.source_bytes = b""
        self.effort_used = opts["effort"]
        self.usage = {}
        self.started = time.time()
        self.deadline = None
        self.format = ""
        self.backend_used = opts["backend"]
        self.fallback_from = ""
        self.model_label = ""
        self.record_opened = False
        self.child = None
        self.temp_dirs = []

    # -- messages -----------------------------------------------------------

    def redact(self, text):
        if self.key and self.key in text:
            text = text.replace(self.key, "[REDACTED]")
        return text

    def diag(self, message):
        # Redact before truncating so a key cut in half cannot slip through.
        text = one_line(self.redact(str(message)))
        sys.stderr.write("%s %s\n" % (PREFIX, text))
        sys.stderr.flush()
        if self.record is not None:
            self.record.log(text)

    def emit(self, outcome, reason, delivered):
        if self.outcome_emitted:
            return
        self.outcome_emitted = True
        emit_outcome(outcome, reason, delivered)

    # -- entry --------------------------------------------------------------

    def run(self):
        try:
            # Installed inside the try, so a signal right after installation
            # is handled like any other.
            _set_signal_handlers(_raise_interrupt)
            if _STARTUP_SIGNALS:
                # Through the raise-once state, so a further signal is only
                # recorded.
                _INTERRUPTING.append(_STARTUP_SIGNALS[0])
                raise Interrupted(_STARTUP_SIGNALS[0])
            return self._run()
        except Interrupted as exc:
            signum = exc.signum
        while True:
            # A further signal before the handlers defer it starts the
            # interruption path again; it is idempotent.
            try:
                _block_signals()
                return self._interrupted(signum)
            except Interrupted:
                continue

    def _interrupted(self, signum):
        _block_signals()
        self._cleanup_temps()
        if self.record is not None and not self.outcome_emitted:
            self._finish_record("failed", "interrupted", False)
        self.emit("failed", "interrupted", self.delivered)
        return _exit_code_for(signum)

    def _cleanup_temps(self):
        self._kill_child()
        for path in list(self.temp_paths):
            try:
                os.unlink(path)
            except OSError:
                pass
            self.temp_paths.remove(path)
        for path in list(self.temp_dirs):
            shutil.rmtree(path, ignore_errors=True)
            self.temp_dirs.remove(path)

    def _kill_child(self):
        """Stop a running agy and everything it started (its own process group)."""
        proc, self.child = self.child, None
        if proc is None or proc.poll() is not None:
            return
        for sig, wait in ((signal.SIGTERM, AGY_KILL_GRACE), (signal.SIGKILL, 5.0)):
            try:
                os.killpg(proc.pid, sig)
            except OSError:
                return
            try:
                proc.wait(timeout=wait)
                return
            except subprocess.TimeoutExpired:
                continue

    def _run(self):
        opts = self.opts
        try:
            data = self._read_input()
        except UsageError as exc:
            self.diag(str(exc))
            self.emit("failed", "usage_error", False)
            return EXIT_USAGE
        self.source_bytes = data
        try:
            final_bytes = self._polish(data)
        except Stop as stop:
            if stop.detail:
                self.diag(stop.detail)
            return self.finish(stop.outcome, stop.reason, data)
        except Exception as exc:  # never let an unexpected error skip delivery
            self.diag("internal error: %s: %s" % (type(exc).__name__, exc))
            return self.finish("failed", "internal_error", data)
        if final_bytes == data:
            return self.finish("unchanged", "identical", data)
        return self.finish("polished", "ok", final_bytes)

    def _read_input(self):
        path = self.opts["input"]
        try:
            if path == "-":
                return sys.stdin.buffer.read()
            with open(path, "rb") as fh:
                return fh.read()
        except OSError as exc:
            raise UsageError("cannot read input %s: %s" % (path, exc.strerror or exc))

    # -- main pipeline ------------------------------------------------------

    def _polish(self, data):
        opts = self.opts
        if opts["skip-reason"]:
            raise Stop("skipped", opts["skip-reason"])
        if not data.strip():
            raise Stop("skipped", "empty_input")
        if len(data) > int(opts["max-bytes"]):
            raise Stop("skipped", "too_large",
                       "input is %d bytes, above the %s byte limit" % (len(data), opts["max-bytes"]))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise Stop("skipped", "unsupported_encoding", "input is not valid UTF-8")
        bom = text.startswith("\ufeff")
        if bom:
            text = text[1:]
        crlf = "\r\n" in text and text.count("\r\n") == text.count("\n")
        if crlf:
            text = text.replace("\r\n", "\n")
        if "\r" in text:
            raise Stop("skipped", "unsupported_encoding",
                       "input mixes line endings or contains bare carriage returns")
        if MARKER_FAMILY in text:
            raise Stop("skipped", "sentinel_collision",
                       "input contains the reserved marker %s" % MARKER_FAMILY)

        fmt = opts["format"] or ("text" if opts["input"] == "-" else detect_format(opts["input"]))
        self.format = fmt
        spans = None
        if fmt in ("markdown", "text"):
            if guard.prose_block_count(text) == 0:
                raise Stop("skipped", "nothing_to_polish", "input has no prose blocks")
            payload = text.strip("\n")
        elif fmt == "segments":
            try:
                guard.parse_segments(text)
            except ValueError as exc:
                raise Stop("skipped", "invalid_segments", str(exc))
            payload = text.strip("\n")
        else:
            try:
                spans, payload = guard.html_extract(text)
            except guard.UnsupportedInput as exc:
                raise Stop("skipped", exc.reason, exc.detail)
            if not spans:
                raise Stop("skipped", "nothing_to_polish", "page has no eligible visible text")

        content, markers = self._fetch(text, fmt, len(data), payload)
        if self.record is not None:
            self.record.write_skill_file("candidate.txt", content)
        body = self._extract_envelope(content, markers)
        final_text = self._verify(fmt, text, payload, body, spans)
        if crlf:
            final_text = final_text.replace("\n", "\r\n")
        if bom:
            final_text = "\ufeff" + final_text
        return final_text.encode("utf-8")

    # -- backends -----------------------------------------------------------

    def _fetch(self, text, fmt, size, payload):
        """Return (reply content, markers) from the selected backend."""
        if self.opts["backend"] != "agy":
            return self._openrouter_fetch(text, fmt, size, payload)
        try:
            return self._agy_fetch(fmt, size, payload)
        except Stop as stop:
            # A reply the guard or the tool check rejected is a content
            # problem; paying for a second opinion would not fix it.
            if stop.outcome == "rejected":
                raise
            if stop.detail:
                self.diag(stop.detail)
            if not self.opts["fallback-openrouter"]:
                self.diag("not falling back to OpenRouter (gemini_polish_fallback_to_openrouter is false)")
                raise Stop(stop.outcome, stop.reason)
            self.key = self._resolve_key()
            if not self.key:
                self.diag("gemini_polish_fallback_to_openrouter is true, but no OpenRouter API key is set")
                raise Stop(stop.outcome, stop.reason)
            if self.key in text:
                self.diag("not falling back to OpenRouter: the input contains the API key")
                raise Stop(stop.outcome, stop.reason)
            self.diag("agy failed (reason=%s); falling back to OpenRouter because "
                      "gemini_polish_fallback_to_openrouter is true" % stop.reason)
            self.fallback_from = "agy:%s" % stop.reason
            self.backend_used = "openrouter"
            self.effort_used = self.opts["effort"]
            self.usage = {}
            system_msg, user_msg, markers = self._build_messages(fmt, payload)
            self._open_record(fmt, size)
            return self._request(system_msg, user_msg), markers

    def _openrouter_fetch(self, text, fmt, size, payload):
        self.key = self._resolve_key()
        if not self.key:
            raise Stop("skipped", "no_api_key",
                       "set OPENROUTER_API_KEY or gemini_polish_api_key_file to enable polishing")
        if self.key in text:
            raise Stop("skipped", "secret_in_input", "input contains the API key; refusing to send it")
        system_msg, user_msg, markers = self._build_messages(fmt, payload)
        self._open_record(fmt, size)
        return self._request(system_msg, user_msg), markers

    def _agy_fetch(self, fmt, size, payload):
        binary = self._agy_binary()
        if not binary:
            raise Stop("skipped", "agy_not_found",
                       "the agy command (Antigravity CLI) was not found; install it and sign in, "
                       "set gemini_polish_agy_bin, or set gemini_polish_backend to openrouter")
        system_msg, user_msg, markers = self._build_messages(fmt, payload)
        self._open_record(fmt, size)
        prompt = AGY_PREFACE + system_msg.strip("\n") + "\n\n" + user_msg
        return self._agy_request(binary, prompt), markers

    def _agy_binary(self):
        configured = self.opts["agy-bin"]
        if configured:
            path = os.path.expanduser(configured)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
            self.diag("gemini_polish_agy_bin is not an executable file: %s" % configured)
            return None
        found = shutil.which("agy")
        if found:
            return found
        # Claude Code hooks and other tools often run with a short PATH.
        local = os.path.expanduser("~/.local/bin/agy")
        if os.path.isfile(local) and os.access(local, os.X_OK):
            return local
        return None

    def _agy_request(self, binary, prompt):
        timeout = int(self.opts["timeout"])
        base = tempfile.mkdtemp(prefix="humanize-polish-agy-")
        self.temp_dirs.append(base)
        try:
            # agy treats its working directory as the workspace: an empty one
            # holding only the deny-all hook.
            workspace = os.path.join(base, "workspace")
            os.makedirs(os.path.join(workspace, ".agents"))
            with open(os.path.join(workspace, ".agents", "hooks.json"), "w") as fh:
                json.dump(AGY_HOOKS, fh, indent=2)
            if self.record is not None and not self.record.broken:
                log_path = os.path.join(self.record.cache_dir, "agy-run.log")
            else:
                log_path = os.path.join(base, "agy-run.log")
            argv = [binary, "--output-format", "stream-json",
                    "--model", self.opts["agy-model"], "--effort", self.opts["effort"],
                    "--disable-slash-commands", "--sandbox",
                    "--settings", json.dumps(AGY_SETTINGS, separators=(",", ":")),
                    "--print-timeout", "%ds" % timeout, "--log-file", log_path]
            env = dict((k, v) for k, v in os.environ.items() if k not in AGY_ENV_DROP)
            if self.record is not None:
                self.record.write_cache_file(
                    "gemini-run.cmd",
                    "# polish-gemini agy run (the prompt goes to standard input)\n"
                    "# Timestamp: %s\n# Timeout: %s seconds\n# Working directory: %s\n\n%s\n\n"
                    "# Standard input (%d characters):\n\n%s"
                    % (_iso(time.time()), timeout, workspace, " ".join(shlex.quote(a) for a in argv),
                       len(prompt), prompt))
            self.diag("running agy (model=%s effort=%s)" % (self.opts["agy-model"], self.opts["effort"]))
            rc, out, err = self._run_agy(argv, workspace, env, prompt.encode("utf-8"), timeout)
            self.model_label = agy_model_label(log_path)
            return self._agy_accept(rc, out, err, timeout)
        finally:
            self._kill_child()
            shutil.rmtree(base, ignore_errors=True)
            if base in self.temp_dirs:
                self.temp_dirs.remove(base)

    def _run_agy(self, argv, workspace, env, stdin_bytes, timeout):
        try:
            proc = subprocess.Popen(argv, cwd=workspace, env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    close_fds=True, start_new_session=True)
        except OSError as exc:
            raise Stop("skipped", "agy_not_found", "cannot start agy: %s" % (exc.strerror or exc))
        self.child = proc
        self.deadline = time.monotonic() + timeout + AGY_KILL_GRACE
        first = True
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                self._kill_child()
                raise Stop("failed", "timeout", "agy did not finish within %s seconds" % timeout)
            # Without a supervising wrapper there is nothing to poll for, so one
            # wait covers the whole budget.
            wait = min(SUPERVISOR_POLL, remaining) if _SUPERVISOR else remaining
            try:
                out, err = proc.communicate(input=stdin_bytes if first else None, timeout=wait)
                break
            except subprocess.TimeoutExpired:
                first = False
                if _supervisor_gone():
                    _raise_interrupt(signal.SIGTERM, None)
        self.child = None
        return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def _agy_accept(self, rc, out, err, timeout):
        events = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        if self.record is not None:
            kept = [e for e in events if not (e.get("event") == "step_update" and isinstance(
                e.get("step_update"), dict) and e["step_update"].get("step_type") == "agent_response")]
            self.record.write_cache_file(
                "gemini-run.out",
                "# agy exit status: %s\n# stderr:\n%s\n\n%s\n" % (
                    rc, err.strip(), "\n".join(json.dumps(e, ensure_ascii=False) for e in kept)))
        init = None
        result = None
        tools = []
        for event in events:
            kind = event.get("event")
            if kind == "init" and isinstance(event.get("init"), dict) and init is None:
                init = event["init"]
            elif kind == "result" and isinstance(event.get("result"), dict):
                result = event["result"]
            elif kind == "step_update" and isinstance(event.get("step_update"), dict):
                step = event["step_update"]
                if step.get("step_type") == "tool":
                    tools.append(str(step.get("tool_name") or "unknown tool"))
        stderr_line = one_line(err.strip(), 300)
        if result is None:
            if rc != 0:
                reason = classify_agy_error(err)
                raise Stop("failed", reason, "agy exited with status %s: %s%s"
                           % (rc, stderr_line, AGY_HINTS.get(reason, "")))
            raise Stop("failed", "bad_json", "agy printed no result event")
        usage = result.get("usage")
        if isinstance(usage, dict):
            self.usage = {
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
                "completion_tokens_details": {"reasoning_tokens": usage.get("thinking_tokens")},
                "cost": "subscription",
            }
        if result.get("finished_reason") == "print_timeout":
            raise Stop("failed", "timeout", "agy did not finish within %s seconds" % timeout)
        if result.get("status") != "SUCCESS" or rc != 0:
            message = result.get("error") if isinstance(result.get("error"), str) else ""
            reason = classify_agy_error("%s\n%s" % (message, err))
            raise Stop("failed", reason, "agy reported an error (exit status %s): %s%s"
                       % (rc, one_line(message or err.strip(), 300), AGY_HINTS.get(reason, "")))
        if init is None or init.get("permission_mode") != "strict":
            raise Stop("failed", "agy_lockdown",
                       "agy did not confirm the strict tool permission mode (got %r); the reply is not used"
                       % (init or {}).get("permission_mode"))
        denied = result.get("denied_actions")
        if isinstance(denied, list):
            tools.extend(str(d.get("action")) for d in denied if isinstance(d, dict) and d.get("action"))
        if tools:
            raise Stop("rejected", "tool_call", "agy tried to use tools (%s); the reply is not used"
                       % ", ".join(sorted(set(tools))))
        response = result.get("response")
        if not isinstance(response, str) or not response.strip():
            raise Stop("failed", "empty_response", "agy returned no text")
        return response.replace("\r\n", "\n")

    def _resolve_key(self):
        env_key = os.environ.get("OPENROUTER_API_KEY", "")
        if env_key.strip():
            value = env_key.strip()
            if valid_key(value):
                return value
            self.diag("OPENROUTER_API_KEY is set but is not a valid key; ignoring it")
        path = self.opts["api-key-file"]
        if not path:
            return None
        path = os.path.expanduser(path)
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError as exc:
            self.diag("cannot read the API key file %s: %s" % (path, exc.strerror or exc))
            return None
        chunks = []
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                self.diag("the API key file %s is not a regular file" % path)
                return None
            if st.st_mode & 0o044:
                self.diag("warning: the API key file %s is readable by group or others; "
                          "run: chmod 600 %s" % (path, path))
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(len(c) for c in chunks) > 65536:
                    break
        finally:
            os.close(fd)
        key = parse_key_text(b"".join(chunks).decode("utf-8", "replace"))
        if not key:
            self.diag("the API key file %s has no usable key (expected a raw key or one "
                      "OPENROUTER_API_KEY=value line)" % path)
        return key

    def _load_template(self, name):
        path = os.path.join(self.opts["template-dir"], name)
        try:
            with open(path, "r") as fh:
                return fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise Stop("skipped", "missing_dependency", "cannot read prompt template %s: %s" % (path, exc))

    def _build_messages(self, fmt, payload):
        nonce = secrets.token_hex(8).upper()
        markers = {
            "INPUT_BEGIN": "%sDOCUMENT-BEGIN-%s@@" % (MARKER_FAMILY, nonce),
            "INPUT_END": "%sDOCUMENT-END-%s@@" % (MARKER_FAMILY, nonce),
            "OUTPUT_BEGIN": "%sOUTPUT-BEGIN-%s@@" % (MARKER_FAMILY, nonce),
            "OUTPUT_END": "%sOUTPUT-END-%s@@" % (MARKER_FAMILY, nonce),
        }
        values = dict(markers)
        values["FORMAT_RULES"] = self._load_template("polish-format-%s.md" % fmt).strip()
        values["FORMAT_NAME"] = FORMAT_NAMES[fmt]
        system_msg = self._render(self._load_template("polish-contract.md"), values)
        preamble = self._render(self._load_template("polish-request.md"), values).strip()
        user_msg = "%s\n\n%s\n%s\n%s\n" % (preamble, markers["INPUT_BEGIN"], payload, markers["INPUT_END"])
        return system_msg, user_msg, markers

    @staticmethod
    def _render(template, values):
        return re.sub(r"\{\{([A-Z_]+)\}\}",
                      lambda m: values.get(m.group(1), m.group(0)), template)

    def _model_for(self, backend):
        return self.opts["agy-model"] if backend == "agy" else self.opts["model"]

    def _open_record(self, fmt, size):
        # Once per run, also when an agy failure falls back to OpenRouter.
        if self.record_opened:
            return
        self.record_opened = True
        root = self.opts["project-root"]
        if not root:
            self.diag("records=unavailable (no project root)")
            return
        try:
            self.record = Record.create(self, root)
        except OSError as exc:
            self.diag("records=unavailable (%s)" % (exc.strerror or exc))
            self.record = None
            return
        label = self.opts["source-label"] or (
            "stdin" if self.opts["input"] == "-" else os.path.basename(self.opts["input"]))
        label = re.sub(r"[\r\n]+", " ", label)
        self.record.write_input(
            "# Polish Gemini Input\n\n## Question\n\nPolish %s (%d bytes, %s)\n\n"
            "## Configuration\n\n- Model: %s\n- Effort: %s\n- Timeout: %ss\n- Max tokens: %s\n"
            "- Backend: %s\n- Mode: polish\n- Timestamp: %s\n- Tool: gemini\n"
            % (label, size, fmt, self._model_for(self.backend_used), self.opts["effort"],
               self.opts["timeout"], self.opts["max-tokens"], self.backend_used,
               time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(self.started))))
        ext = {"markdown": ".md", "text": ".txt", "segments": ".txt", "html": ".html"}[fmt]
        self.record.write_skill_file("source" + ext, self.source_bytes)

    # -- HTTP ---------------------------------------------------------------

    def _request_body(self, system_msg, user_msg, effort):
        return {
            "model": self.opts["model"],
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "reasoning": {"effort": effort, "exclude": True},
            "max_tokens": int(self.opts["max-tokens"]),
            "stream": False,
        }

    def _send_once(self, url, body, headers):
        holder = {}
        done = threading.Event()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            return "timeout", None

        def worker():
            _mask_signals_in_thread()
            try:
                holder["result"] = http_post(url, body, headers, remaining + 1.0)
            except BaseException as exc:  # reported to the main thread
                holder["error"] = exc
            finally:
                done.set()

        thread = threading.Thread(target=worker, name="polish-request")
        thread.daemon = True
        thread.start()
        # Without a supervising wrapper there is nothing to poll for, so one
        # wait covers the whole budget (_supervisor_gone() is then False).
        poll = SUPERVISOR_POLL if _SUPERVISOR else remaining
        end = time.monotonic() + remaining
        while not done.wait(min(poll, max(0.0, end - time.monotonic()))):
            if _supervisor_gone():
                _raise_interrupt(signal.SIGTERM, None)
            if time.monotonic() >= end:
                return "timeout", None
        if "error" in holder:
            return "error", holder["error"]
        return "ok", holder["result"]

    def _request(self, system_msg, user_msg):
        base = self.opts["base-url"].rstrip("/")
        scheme = urllib.parse.urlsplit(base).scheme.lower()
        if scheme not in ("http", "https"):
            raise Stop("failed", "api_error", "base URL must use http or https: %s" % base)
        url = base + "/chat/completions"
        headers = {
            "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Title": "humanize-polish",
            "User-Agent": "humanize-polish",
        }
        self.deadline = time.monotonic() + int(self.opts["timeout"])
        effort = self.opts["effort"]
        posts = 0
        while True:
            body = self._request_body(system_msg, user_msg, effort)
            body_json = json.dumps(body, ensure_ascii=False, indent=2)
            if self.record is not None:
                self.record.write_cache_file(
                    "gemini-run.cmd",
                    "# polish-gemini request (Authorization header omitted)\n"
                    "# Timestamp: %s\n# Timeout: %s seconds\n\nPOST %s\n"
                    "Content-Type: application/json\nAccept: application/json\nX-Title: humanize-polish\n\n%s\n"
                    % (_iso(time.time()), self.opts["timeout"], url, body_json))
            posts += 1
            # Record the effort of the request being sent, so a failed retry
            # is reported with the effort it actually used.
            self.effort_used = effort
            self.diag("sending request %d to %s (model=%s effort=%s max_tokens=%s)"
                      % (posts, url, self.opts["model"], effort, self.opts["max-tokens"]))
            kind, value = self._send_once(url, json.dumps(body).encode("utf-8"), headers)
            if kind == "timeout":
                raise Stop("failed", "timeout", "no complete response within %s seconds" % self.opts["timeout"])
            if kind == "error":
                reason = classify_exception(value)
                raise Stop("failed", reason, "request failed: %s" % self.redact(str(value))[:300])
            status, resp_headers, raw = value
            self.diag("HTTP %d after request %d" % (status, posts))
            if status == 200:
                return self._accept(raw)
            message = api_error_message(raw)
            if message:
                self.diag("API error (HTTP %d): %s" % (status, self.redact(message)))
            if status == 400 and effort == "xhigh" and posts < MAX_POSTS and is_effort_rejection(raw):
                self.diag("the API rejected reasoning effort xhigh; retrying once with high")
                effort = "high"
                continue
            if status == 429 and posts < MAX_POSTS:
                wait = parse_retry_after(resp_headers.get("retry-after"))
                remaining = self.deadline - time.monotonic()
                if wait < remaining - 1.0:
                    self.diag("rate limited; retrying once after %.1f seconds" % wait)
                    time.sleep(wait)
                    continue
                raise Stop("failed", "rate_limited", "rate limited and the retry would pass the deadline")
            raise Stop("failed", classify_status(status))

    def _accept(self, raw):
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Stop("failed", "bad_json", "response body is not valid JSON")
        try:
            # JSON escapes can decode to lone surrogates, which are not text.
            json.dumps(data, ensure_ascii=False).encode("utf-8")
        except (UnicodeError, ValueError, TypeError):
            raise Stop("failed", "bad_json", "response contains invalid Unicode")
        if not isinstance(data, dict):
            raise Stop("failed", "api_error", "response is not a JSON object")
        usage = data.get("usage")
        if isinstance(usage, dict):
            self.usage = usage
        if self.record is not None:
            try:
                cleaned = json.dumps(_strip_reasoning(data), indent=2, ensure_ascii=False) + "\n"
            except Exception:
                cleaned = "(response could not be serialized)\n"
            self.record.write_cache_file("gemini-run.out", cleaned)
        # An error field of any value except null means the call failed.
        if data.get("error", None) is not None:
            raise Stop("failed", "api_error", "response contains an error field: %s"
                       % api_error_message(raw))
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise Stop("failed", "api_error", "response has no choices")
        choice = choices[0]
        if choice.get("error", None) is not None:
            raise Stop("failed", "api_error", "response choice contains an error")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise Stop("failed", "api_error", "response choice has no message")
        if message.get("tool_calls") or message.get("function_call"):
            raise Stop("rejected", "tool_call", "the model returned a tool call")
        finish = choice.get("finish_reason")
        if finish == "tool_calls":
            raise Stop("rejected", "tool_call", "the model finished with tool_calls")
        if finish == "length":
            raise Stop("failed", "truncated",
                       "the reply hit max_tokens (%s); raise gemini_polish_max_tokens or lower the effort"
                       % self.opts["max-tokens"])
        if message.get("refusal"):
            raise Stop("failed", "api_error", "the model refused the request")
        if finish != "stop":
            raise Stop("failed", "api_error", "unexpected finish_reason %r (native %r)"
                       % (finish, choice.get("native_finish_reason")))
        content = message.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            raise Stop("failed", "empty_response", "the reply has no content")
        if not isinstance(content, str):
            raise Stop("failed", "api_error", "the reply content is not a string")
        return content.replace("\r\n", "\n")

    # -- verification -------------------------------------------------------

    def _extract_envelope(self, content, markers):
        begin = markers["OUTPUT_BEGIN"]
        end = markers["OUTPUT_END"]
        if content.count(begin) != 1 or content.count(end) != 1:
            raise Stop("rejected", "envelope", "reply must contain exactly one output block")
        b = content.index(begin)
        e = content.index(end)
        if e < b:
            raise Stop("rejected", "envelope", "output markers are out of order")
        if content[:b].strip() or content[e + len(end):].strip():
            raise Stop("rejected", "envelope", "reply has text outside the output block")
        inner = content[b + len(begin):e]
        if not inner.startswith("\n") or not inner.endswith("\n") or len(inner) < 2:
            raise Stop("rejected", "envelope", "output markers must be on their own lines")
        inner = inner[1:-1]
        if not inner.strip():
            raise Stop("rejected", "envelope", "output block is empty")
        if MARKER_FAMILY in inner:
            raise Stop("rejected", "envelope", "output block contains a reserved marker")
        return inner

    def _ratios(self):
        block = guard.parse_ratio_bounds(self.opts["block-ratio"], guard.BLOCK_RATIO_BOUNDS)
        doc = guard.parse_ratio_bounds(self.opts["doc-ratio"], guard.DOC_RATIO_BOUNDS)
        return block, doc

    def _verify(self, fmt, text, payload, body, spans):
        block_ratio, doc_ratio = self._ratios()
        lead = text[:len(text) - len(text.lstrip("\n"))]
        trail = text[len(text.rstrip("\n")):]
        try:
            if fmt in ("markdown", "text"):
                candidate = lead + body.strip("\n") + trail
                guard.check_document(text, candidate, block_ratio, doc_ratio)
                return candidate
            if fmt == "segments":
                segments = guard.check_segments(payload, body, False, block_ratio, doc_ratio)
                return _rebuild_segments(text, segments)
            segments = guard.check_segments(payload, body, True, block_ratio, doc_ratio)
            spliced = guard.html_splice(text, spans, [t for _, t in segments])
            guard.html_verify(text, spliced)
            return spliced
        except guard.GuardReject as exc:
            raise Stop("rejected", exc.reason, "guard: %s" % exc.detail)

    # -- delivery -----------------------------------------------------------

    def finish(self, outcome, reason, payload):
        _block_signals()
        if not _DEFERRED_SIGNALS and _supervisor_gone():
            _DEFERRED_SIGNALS.append(signal.SIGTERM)
        if _DEFERRED_SIGNALS:
            # Interrupted before delivery began: deliver nothing.
            return self._interrupted(_DEFERRED_SIGNALS[0])
        ok = self._deliver(payload)
        self.delivered = ok
        if not ok:
            outcome, reason = "failed", "delivery_error"
        if self.record is not None:
            try:
                if ok:
                    self.record.write_skill_file("output.md", payload)
                self._finish_record(outcome, reason, ok)
            except Exception as exc:  # records must never block the outcome
                self.diag("records=unavailable (%s)" % exc)
        if _DEFERRED_SIGNALS:
            # Interrupted during delivery: the delivery finished (or failed)
            # first. The outcome line still describes what was delivered, and
            # the exit code (130 or 143) reports the interruption. A signal
            # that arrives after this point is still reflected in the exit
            # code by main().
            self.diag("interrupted by %s during delivery; delivery %s first"
                      % ("SIGINT" if _DEFERRED_SIGNALS[0] == signal.SIGINT else "SIGTERM",
                         "finished" if ok else "failed"))
        self.emit(outcome, reason, ok)
        if _DEFERRED_SIGNALS:
            return _exit_code_for(_DEFERRED_SIGNALS[0])
        if not ok:
            return EXIT_DELIVERY
        if self.opts["strict"] and outcome in ("skipped", "rejected", "failed"):
            return EXIT_STRICT
        return EXIT_OK

    def _deliver(self, payload):
        out = self.opts["output"]
        if not out:
            try:
                _write_all(sys.stdout.fileno(), payload)
                return True
            except OSError as exc:
                self.diag("could not write to stdout: %s" % (exc.strerror or exc))
                try:
                    devnull = os.open(os.devnull, os.O_WRONLY)
                    os.dup2(devnull, sys.stdout.fileno())
                except OSError:
                    pass
                return False
        if (self.opts["input"] != "-" and payload == self.source_bytes and os.path.exists(out)
                and os.path.exists(self.opts["input"])):
            try:
                if os.path.samefile(out, self.opts["input"]):
                    return True
            except OSError:
                pass
        return self._atomic_write(out, payload)

    def _atomic_write(self, path, payload):
        directory = os.path.dirname(os.path.abspath(path))
        mode = None
        try:
            if os.path.exists(path):
                mode = stat.S_IMODE(os.stat(path).st_mode)
        except OSError:
            mode = None
        if mode is None:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        tmp = None
        try:
            if os.path.isdir(path):
                raise OSError(21, "is a directory")
            fd, tmp = tempfile.mkstemp(prefix=".polish-gemini-", suffix=".tmp", dir=directory)
            self.temp_paths.append(tmp)
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, path)
            self.temp_paths.remove(tmp)
            return True
        except OSError as exc:
            self.diag("could not write %s: %s" % (path, exc.strerror or exc))
            self._cleanup_temps()
            return False

    def _finish_record(self, outcome, reason, delivered):
        if outcome in ("polished", "unchanged"):
            status = "success"
        elif outcome == "failed" and reason == "timeout":
            status = "timeout"
        elif outcome == "failed" and reason == "empty_response":
            status = "empty_response"
        else:
            status = "error"
        usage = self.usage or {}
        details = usage.get("completion_tokens_details")
        reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None

        def known(value):
            return "unknown" if value is None else value

        fields = [
            ("tool", "gemini"),
            ("mode", "polish"),
            ("backend", self.backend_used),
            ("model", self._model_for(self.backend_used)),
        ]
        if self.backend_used == "agy":
            # The model and effort agy reports it actually used, from its log.
            fields.append(("model_label", self.model_label or "unknown"))
        if self.fallback_from:
            fields.append(("fallback_from", self.fallback_from))
        fields += [
            ("effort", self.effort_used),
            ("effort_used", self.effort_used),
            ("status", status),
            ("outcome", outcome),
            ("reason", reason),
            ("format", self.format or "unknown"),
            ("delivered", "yes" if delivered else "no"),
            ("prompt_tokens", known(usage.get("prompt_tokens"))),
            ("completion_tokens", known(usage.get("completion_tokens"))),
            ("reasoning_tokens", known(reasoning)),
            ("cost", known(usage.get("cost"))),
            ("timeout", self.opts["timeout"]),
            ("duration", "%ds" % int(round(time.time() - self.started))),
            ("started_at", _iso(self.started)),
        ]
        self.record.write_metadata(fields)


def _strip_reasoning(data):
    """Return a copy of a response without any reasoning text."""
    clean = json.loads(json.dumps(data))
    if not isinstance(clean, dict):
        return clean
    choices = clean.get("choices")
    if not isinstance(choices, list):
        return clean
    for choice in choices:
        if isinstance(choice, dict):
            for holder in (choice, choice.get("message"), choice.get("delta")):
                if isinstance(holder, dict):
                    for key in ("reasoning", "reasoning_details", "reasoning_content"):
                        holder.pop(key, None)
    return clean


def _rebuild_segments(text, segments):
    """Replace segment text in place, keeping blank lines and line order."""
    new_text = dict(segments)
    out = []
    for line in text.split("\n"):
        m = guard.SEGMENT_RE.match(line)
        if m and m.group(1) in new_text:
            out.append(guard.format_segments([(m.group(1), new_text[m.group(1)])]))
        else:
            out.append(line)
    return "\n".join(out)


def main(argv):
    try:
        opts = parse_options(argv)
    except UsageError as exc:
        sys.stderr.write("%s %s\n" % (PREFIX, one_line(exc)))
        emit_outcome("failed", "usage_error", False)
        return _exit_code_for(_STARTUP_SIGNALS[0]) if _STARTUP_SIGNALS else EXIT_USAGE
    rc = Runner(opts).run()
    if _DEFERRED_SIGNALS and rc in (EXIT_OK, EXIT_STRICT, EXIT_DELIVERY):
        # A signal that arrived after the outcome line was printed.
        rc = _exit_code_for(_DEFERRED_SIGNALS[0])
    return rc


if __name__ == "__main__":
    if not _await_release(_HANDLED_SIGNALS):
        # The supervising wrapper is gone or did not release the run: end
        # without reading input or delivering anything.
        sys.exit(EXIT_USAGE)
    _adopt_stderr()
    sys.exit(main(sys.argv[1:]))
