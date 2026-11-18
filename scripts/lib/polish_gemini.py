#!/usr/bin/env python3
"""polish_gemini - readability-only polish through the OpenRouter chat API.

Internal helper for scripts/polish-gemini.sh. The shell wrapper parses the
public command line and the merged humanize config, then runs this module with
resolved settings. This module:

1. reads the source bytes (a file or stdin);
2. checks them (size, encoding, marker collisions, format-specific parsing);
3. resolves the API key inside this process;
4. sends one chat completions request with no tools, plus at most one retry
   (effort fallback or rate limiting), under one overall deadline;
5. verifies the candidate with polish_guard;
6. delivers either the polished text or the exact original bytes;
7. writes the run record and prints exactly one outcome line on stderr.

Standard library only. The API key never appears on a command line, in a run
record, in a cache file, on stdout, or on stderr.
"""

import sys

sys.dont_write_bytecode = True

import email.utils  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import stat  # noqa: E402
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
FORMAT_TEMPLATES = {
    "markdown": "polish-format-markdown.md",
    "text": "polish-format-text.md",
    "segments": "polish-format-segments.md",
    "html": "polish-format-html.md",
}
REJECTION_WORDS = ("unsupported", "not supported", "invalid", "must be one of",
                   "allowed values", "not allowed", "unknown", "enum", "expected one of",
                   "not a valid", "is not one of")


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


def _raise_interrupt(signum, frame):
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
                 "skip-reason", "block-ratio", "doc-ratio", "source-label")
FLAG_OPTIONS = ("strict",)


def parse_options(argv):
    opts = {
        "input": None, "output": "", "format": "", "model": "", "effort": "xhigh",
        "timeout": "900", "max-tokens": "131072", "max-bytes": "262144", "base-url": "",
        "api-key-file": "", "project-root": "", "template-dir": "", "skip-reason": "",
        "block-ratio": "", "doc-ratio": "", "source-label": "", "strict": False,
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


def is_effort_rejection(raw_body):
    """True only when an HTTP 400 body explicitly rejects the effort value xhigh."""
    try:
        data = json.loads(raw_body.decode("utf-8", "replace"))
    except ValueError:
        return False
    if not isinstance(data, dict) or not isinstance(data.get("error"), dict):
        return False
    err = data["error"]
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
    try:
        data = json.loads(raw_body.decode("utf-8", "replace"))
    except ValueError:
        return ""
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        msg = data["error"].get("message")
        if isinstance(msg, str):
            # Not truncated here: diag() redacts the key first, then truncates.
            return msg
    return ""


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
        self.records_note_done = False
        self.delivered = False
        self.outcome_emitted = False
        self.temp_paths = []
        self.source_bytes = b""
        self.effort_used = opts["effort"]
        self.usage = {}
        self.started = time.time()
        self.deadline = None
        self.candidate_raw = None
        self.format = ""

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
        sys.stderr.write("%s outcome=%s reason=%s delivered=%s\n"
                         % (PREFIX, outcome, reason, "yes" if delivered else "no"))
        sys.stderr.flush()

    # -- entry --------------------------------------------------------------

    def run(self):
        _set_signal_handlers(_raise_interrupt)
        try:
            return self._run()
        except Interrupted as exc:
            return self._interrupted(exc.signum)

    def _interrupted(self, signum):
        _block_signals()
        self._cleanup_temps()
        if self.record is not None and not self.outcome_emitted:
            self._finish_record("failed", "interrupted", False)
        self.emit("failed", "interrupted", self.delivered)
        return _exit_code_for(signum)

    def _cleanup_temps(self):
        for path in list(self.temp_paths):
            try:
                os.unlink(path)
            except OSError:
                pass
            self.temp_paths.remove(path)

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

        self.key = self._resolve_key()
        if not self.key:
            raise Stop("skipped", "no_api_key",
                       "set OPENROUTER_API_KEY or gemini_polish_api_key_file to enable polishing")
        if self.key in text:
            raise Stop("skipped", "secret_in_input", "input contains the API key; refusing to send it")

        system_msg, user_msg, markers = self._build_messages(fmt, payload)
        self._open_record(fmt, len(data))
        content = self._request(system_msg, user_msg)
        self.candidate_raw = content
        if self.record is not None:
            self.record.write_skill_file("candidate.txt", content)
        body = self._extract_envelope(content, markers)
        final_text = self._verify(fmt, text, payload, body, spans)
        if crlf:
            final_text = final_text.replace("\n", "\r\n")
        if bom:
            final_text = "\ufeff" + final_text
        return final_text.encode("utf-8")

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
        values["FORMAT_RULES"] = self._load_template(FORMAT_TEMPLATES[fmt]).strip()
        values["FORMAT_NAME"] = FORMAT_NAMES[fmt]
        system_msg = self._render(self._load_template("polish-contract.md"), values)
        preamble = self._render(self._load_template("polish-request.md"), values).strip()
        user_msg = "%s\n\n%s\n%s\n%s\n" % (preamble, markers["INPUT_BEGIN"], payload, markers["INPUT_END"])
        return system_msg, user_msg, markers

    @staticmethod
    def _render(template, values):
        return re.sub(r"\{\{([A-Z_]+)\}\}",
                      lambda m: values.get(m.group(1), m.group(0)), template)

    def _open_record(self, fmt, size):
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
            "- Backend: openrouter\n- Mode: polish\n- Timestamp: %s\n- Tool: gemini\n"
            % (label, size, fmt, self.opts["model"], self.opts["effort"], self.opts["timeout"],
               self.opts["max-tokens"], time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(self.started))))
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
        if not done.wait(remaining):
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
        if self.record is None:
            return
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
            ("backend", "openrouter"),
            ("model", self.opts["model"]),
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
            out.append("[[%s]] %s" % (m.group(1), new_text[m.group(1)]))
        else:
            out.append(line)
    return "\n".join(out)


def main(argv):
    try:
        opts = parse_options(argv)
    except UsageError as exc:
        sys.stderr.write("%s %s\n" % (PREFIX, one_line(exc)))
        sys.stderr.write("%s outcome=failed reason=usage_error delivered=no\n" % PREFIX)
        return EXIT_USAGE
    rc = Runner(opts).run()
    if _DEFERRED_SIGNALS and rc in (EXIT_OK, EXIT_STRICT, EXIT_DELIVERY):
        # A signal that arrived after the outcome line was printed.
        rc = _exit_code_for(_DEFERRED_SIGNALS[0])
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
