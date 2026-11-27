#!/usr/bin/env python3
"""Run a Humanize RLCR loop in agy with nobody at the keyboard.

agy lets a Stop hook keep the agent working at most 10 times per user
message, so a long loop pauses about every 10 rounds and waits for the user
to say "continue". This driver plays that user: it starts agy in print mode
with the humanize-start-rlcr-loop skill, and each time agy stops while the
loop is still active, it resumes the same conversation with "continue".

Safety while unattended:
- agy's own permission prompts are approved automatically (nobody could
  answer them), so the driver sets HUMANIZE_AGY_UNATTENDED=1. The Humanize
  hook adapter then blocks file changes outside the project and `git push`
  (unless the loop was started with --push-every-round). As a backstop the
  driver also makes git itself refuse to push, through a pushInsteadOf rule
  in the environment (a remote with its own pushurl is not covered by
  that rule, only by the hook check). agy itself is also
  told to keep its file tools inside the workspace and not to switch to paid
  AI credits when the subscription quota runs out. Shell commands can still
  reach outside the project; run unattended loops only where that is
  acceptable.
- The driver gives up after --stall-limit resumes in a row that change
  nothing, or after --max-resumes resumes in total.

Exit codes: 0 the loop finished; 1 the loop ended another way (cancelled,
round limit, stopped) or never started; 2 the driver gave up; 64 usage error.
"""

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

USAGE = """\
Run a Humanize RLCR loop in agy with nobody at the keyboard.

Usage:
  agy-rlcr-run.sh [driver options] <plan-file> [setup options]
  agy-rlcr-run.sh [driver options] --skip-impl [setup options]
  agy-rlcr-run.sh [driver options] --resume CONVERSATION_ID

Starts agy in print mode with the humanize-start-rlcr-loop skill. Each time
agy stops while the loop is still active, the driver resumes the same agy
conversation with "continue", until the loop ends. Then it prints Gemini's
finalize summary, or Gemini's last reply if the loop ended another way.

Driver options (must come before the plan file):
  --model MODEL        agy model (default: agy's own default)
  --effort LEVEL       agy reasoning effort (low|medium|high|xhigh|max)
  --max-resumes N      give up after N resumes in total (default 50)
  --stall-limit N      give up after N resumes in a row that change nothing
                       in the loop or the repository (default 3)
  --log-dir DIR        where to keep agy's output
                       (default .humanize/agy-runs/<timestamp>)
  --resume ID          drive an agy conversation that already runs a loop,
                       for example after the driver itself was stopped
  --agy PATH           agy executable (default: agy on PATH)
  -h, --help           show this help

Setup options are passed to setup-rlcr-loop.sh unchanged. --skip-quiz is
added because nobody is there to answer the quiz.

While the driver runs, agy's permission prompts are approved automatically.
The Humanize hooks then block file changes outside the project and git push
(unless you pass --push-every-round; git itself is also set to refuse
pushes), agy keeps its file tools inside the project, and agy does not
switch to paid AI credits when your quota runs out. These checks catch
mistakes; they are not a sandbox. Shell commands can still reach outside the
project, so run unattended loops only where that is acceptable.

Exit codes: 0 loop finished, 1 loop ended another way or never started,
2 driver gave up, 64 usage error.
"""

ACTIVE_STATE_FILES = ("state.md", "finalize-state.md", "methodology-analysis-state.md")
UNATTENDED_ENV = "HUMANIZE_AGY_UNATTENDED"
# Settings for the driven agy runs only; agy never saves them. Prompts are
# approved automatically because nobody could answer them, file tools stay in
# the workspace, and a used-up subscription quota never turns into paid
# AI credits.
AGY_SETTINGS = json.dumps({
    "toolPermission": "always-proceed",
    "allowNonWorkspaceAccess": False,
    "useG1Credits": False,
})
QUIZ_SKIP_FLAGS = ("--skip-quiz", "--yolo", "--skip-impl")

START_PROMPT = """\
Use the humanize-start-rlcr-loop skill to start a Humanize RLCR loop with these setup arguments:

{arguments}

Nobody is watching this session: a driver script stands in for the user.
- Do not ask the user anything; ask_question gets no answer. If something blocks you, explain it plainly in your final reply and end your turn.
- When the loop pauses at agy's continuation limit, just end your turn. The driver replies "continue" for you.

Then do the work the loop gives you until the loop ends."""

RESUME_PROMPT = "continue"

# pushInsteadOf with an empty prefix matches every push URL and rewrites it to
# a transport git does not have, so `git push` fails while fetch still works.
# The scheme name is what git shows in its error.
PUSH_BLOCK_KEY = "url.humanize-unattended-run-blocks-git-push://.pushInsteadOf"


class UsageError(Exception):
    pass


def log(message):
    print(f"[agy-rlcr-run] {message}", file=sys.stderr, flush=True)


def positive_int(flag, value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise UsageError(f"{flag} needs a whole number, got: {value}")
    if number < 1:
        raise UsageError(f"{flag} must be at least 1, got: {value}")
    return number


def parse_args(argv):
    options = {
        "model": None,
        "effort": None,
        "max_resumes": 50,
        "stall_limit": 3,
        "log_dir": None,
        "resume": None,
        "agy": "agy",
        "help": False,
        "setup_args": [],
    }
    with_value = {
        "--model": "model",
        "--effort": "effort",
        "--max-resumes": "max_resumes",
        "--stall-limit": "stall_limit",
        "--log-dir": "log_dir",
        "--resume": "resume",
        "--agy": "agy",
    }
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("-h", "--help"):
            options["help"] = True
            return options
        if arg == "--":
            index += 1
            break
        if arg in with_value:
            if index + 1 >= len(argv) or not argv[index + 1]:
                raise UsageError(f"{arg} needs a value")
            options[with_value[arg]] = argv[index + 1]
            index += 2
            continue
        break
    options["setup_args"] = list(argv[index:])
    options["max_resumes"] = positive_int("--max-resumes", options["max_resumes"])
    options["stall_limit"] = positive_int("--stall-limit", options["stall_limit"])
    if options["resume"] and options["setup_args"]:
        raise UsageError("--resume takes no plan file or setup options; the loop already exists")
    if not options["resume"] and not options["setup_args"]:
        raise UsageError("give a plan file (or --skip-impl), or --resume CONVERSATION_ID")
    if not options["resume"] and not any(flag in options["setup_args"] for flag in QUIZ_SKIP_FLAGS):
        options["setup_args"].append("--skip-quiz")
    return options


def git_root(cwd):
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(out.stdout.strip()).resolve()


def read_fields(path):
    fields = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return fields
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and " " not in key.strip():
            fields.setdefault(key.strip(), value.strip())
    return fields


def find_loop(root, conversation):
    """The loop directory whose state names this conversation, newest first."""
    rlcr = root / ".humanize" / "rlcr"
    try:
        loop_dirs = sorted((d for d in rlcr.iterdir() if d.is_dir()), reverse=True)
    except OSError:
        return None
    for loop_dir in loop_dirs:
        for state in sorted(loop_dir.glob("*state.md")):
            if read_fields(state).get("session_id") == conversation:
                return loop_dir
    return None


def loop_state(loop_dir):
    """(name, is_active) of the loop's current state file, or (None, False)."""
    for name in ACTIVE_STATE_FILES:
        if (loop_dir / name).is_file():
            return name, True
    terminal = sorted(p.name for p in loop_dir.glob("*-state.md"))
    if terminal:
        return terminal[0], False
    return None, False


def file_stamp(path):
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


def fingerprint(root, loop_dir, skip_dirs=()):
    """Something that changes whenever the loop or the repository moves on:
    the loop's files, HEAD, and the size and time of every changed or
    untracked file (so edits to an already-dirty file count as progress).
    Files under .humanize/ and skip_dirs (the driver's log folder) are left
    out: the loop folder is checked on its own, and the logs change on every
    turn."""
    name, _active = loop_state(loop_dir)
    files = []
    try:
        for path in sorted(loop_dir.iterdir()):
            if path.is_file():
                files.append((path.name, file_stamp(path)))
    except OSError:
        pass
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    # Bytes, not text: -z prints file names unquoted, and they need not be UTF-8.
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=root, capture_output=True
    ).stdout
    skipped = [".humanize"]
    for folder in skip_dirs:
        try:
            skipped.append(Path(folder).resolve().relative_to(root).as_posix())
        except (OSError, ValueError):
            continue  # outside the project: git status never lists it
    changed = []
    entries = status.split(b"\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        code, rel = os.fsdecode(entry[:2]), os.fsdecode(entry[3:])
        if "R" in code or "C" in code:
            index += 1  # the next entry is the old name of a rename or copy
        if any(rel == folder or rel.startswith(folder + "/") for folder in skipped):
            continue
        changed.append((code, rel, file_stamp(root / rel)))
    return (name, tuple(files), head, tuple(changed))


def current_round(loop_dir):
    name, active = loop_state(loop_dir)
    if not active:
        return None
    return read_fields(loop_dir / name).get("current_round")


def parse_events(path):
    """conversation_id, status and final response from agy's stream-json output."""
    conversation = status = response = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return conversation, status, response
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        conversation = conversation or event.get("conversation_id")
        if event.get("event") == "result" and isinstance(event.get("result"), dict):
            result = event["result"]
            conversation = conversation or result.get("conversation_id")
            status = result.get("status")
            response = result.get("response")
    return conversation, status, response


def stop_process(process):
    if process.poll() is not None:
        return
    for sig, wait in ((signal.SIGINT, 10), (signal.SIGTERM, 5)):
        try:
            process.send_signal(sig)
            process.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue
        except OSError:
            return
    process.kill()
    process.wait()


def raise_keyboard_interrupt(_signum, _frame):
    raise KeyboardInterrupt


class Driver:
    def __init__(self, options, root):
        self.options = options
        self.root = root
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        log_dir = options["log_dir"] or str(root / ".humanize" / "agy-runs" / stamp)
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.turn = 0
        self.last_response = None
        self.conversation = options["resume"]
        self.env = dict(os.environ)
        self.env[UNATTENDED_ENV] = "1"
        # agy runs in the project root even when the driver was started from a
        # subfolder; PWD must agree, or tools that trust it see the subfolder.
        self.env["PWD"] = str(root)

    def block_git_push(self):
        try:
            count = int(self.env.get("GIT_CONFIG_COUNT", "0"))
        except ValueError:
            count = 0
        self.env[f"GIT_CONFIG_KEY_{count}"] = PUSH_BLOCK_KEY
        self.env[f"GIT_CONFIG_VALUE_{count}"] = ""
        self.env["GIT_CONFIG_COUNT"] = str(count + 1)

    def agy_command(self, prompt, conversation=None):
        command = [self.options["agy"]]
        if conversation:
            command += ["--conversation", conversation]
        command += ["-p", prompt, "--output-format", "stream-json", "--settings", AGY_SETTINGS]
        if self.options["model"]:
            command += ["--model", self.options["model"]]
        if self.options["effort"]:
            command += ["--effort", self.options["effort"]]
        return command

    def run_turn(self, prompt, conversation=None):
        self.turn += 1
        events = self.log_dir / f"turn-{self.turn:03d}.jsonl"
        errors = self.log_dir / f"turn-{self.turn:03d}.stderr"
        command = self.agy_command(prompt, conversation)
        kind = f"resume {conversation} with {prompt!r}" if conversation else "start"
        with open(self.log_dir / "driver.log", "a", encoding="utf-8") as record:
            record.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} turn {self.turn}: {kind}\n")
        with open(events, "w", encoding="utf-8") as out, open(errors, "w", encoding="utf-8") as err:
            process = subprocess.Popen(command, cwd=self.root, env=self.env, stdout=out, stderr=err)
            try:
                while True:
                    try:
                        code = process.wait(timeout=2)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    # Report the conversation as soon as agy names it, so a
                    # driver stopped during a long first turn can still say
                    # how to resume.
                    if self.conversation is None:
                        self.note_conversation(parse_events(events)[0])
            except KeyboardInterrupt:
                # Never leave agy working on the loop after the driver stops.
                stop_process(process)
                if self.conversation is None:
                    self.note_conversation(parse_events(events)[0])
                raise
        found, status, response = parse_events(events)
        if self.conversation is None:
            self.note_conversation(found)
        if response:
            self.last_response = response
        return code, found, status

    def note_conversation(self, conversation):
        if conversation and self.conversation is None:
            self.conversation = conversation
            log(f"agy conversation: {conversation}")

    def finish(self, loop_dir, code):
        """Print what Gemini wrote for people: the finalize summary when the
        loop finished, otherwise Gemini's last reply."""
        name, _active = loop_state(loop_dir) if loop_dir else (None, False)
        summary = loop_dir / "finalize-summary.md" if loop_dir else None
        if name == "complete-state.md" and summary is not None and summary.is_file():
            print(summary.read_text(encoding="utf-8", errors="replace").rstrip())
        elif self.last_response:
            print(self.last_response.rstrip())
        log(f"agy output kept in {self.log_dir}")
        if loop_dir:
            log(f"loop folder: {loop_dir} (state: {name or 'unknown'})")
        return code

    def run(self):
        options = self.options
        if options["resume"]:
            conversation = options["resume"]
            loop_dir = find_loop(self.root, conversation)
            if loop_dir is None:
                log(f"no Humanize loop in this project belongs to agy conversation {conversation}")
                return 1
            name, _active = loop_state(loop_dir)
            pushes_allowed = bool(name) and read_fields(loop_dir / name).get("push_every_round") == "true"
            if not pushes_allowed:
                self.block_git_push()
        else:
            if "--push-every-round" not in options["setup_args"]:
                self.block_git_push()
            arguments = shlex.join(options["setup_args"])
            log(f"starting agy: humanize-start-rlcr-loop {arguments}")
            code, conversation, status = self.run_turn(START_PROMPT.format(arguments=arguments))
            conversation = self.conversation
            if not conversation:
                log(f"agy did not start a conversation (exit {code}); see {self.log_dir}")
                return self.finish(None, 2)
            loop_dir = find_loop(self.root, conversation)
            if loop_dir is None:
                log("the loop did not start; agy's last reply follows")
                return self.finish(None, 1)

        resumes = 0
        stalled = 0
        while True:
            name, active = loop_state(loop_dir)
            if not active:
                done = name == "complete-state.md"
                log("the loop finished" if done else f"the loop ended: {name or 'no state file'}")
                return self.finish(loop_dir, 0 if done else 1)
            if resumes >= options["max_resumes"]:
                log(f"giving up after {resumes} resumes (--max-resumes); resume later with --resume {conversation}")
                return self.finish(loop_dir, 2)
            before = fingerprint(self.root, loop_dir, [self.log_dir])
            resumes += 1
            log(f"round {current_round(loop_dir) or '?'} ({name}): resuming agy ({resumes} of at most {options['max_resumes']})")
            code, _found, status = self.run_turn(RESUME_PROMPT, conversation)
            if code != 0 or (status and status != "SUCCESS"):
                log(f"agy exited with code {code}, status {status or 'unknown'}")
            if fingerprint(self.root, loop_dir, [self.log_dir]) == before:
                stalled += 1
                log(f"nothing changed in this resume ({stalled} of at most {options['stall_limit']} in a row)")
                if stalled >= options["stall_limit"]:
                    log(f"giving up: the loop is not moving; resume later with --resume {conversation}")
                    return self.finish(loop_dir, 2)
            else:
                stalled = 0


def main(argv):
    try:
        options = parse_args(argv)
    except UsageError as exc:
        print(f"agy-rlcr-run: {exc}", file=sys.stderr)
        print("Run with --help for usage.", file=sys.stderr)
        return 64
    if options["help"]:
        print(USAGE, end="")
        return 0
    root = git_root(os.getcwd())
    if root is None:
        print("agy-rlcr-run: run this inside the project's git repository", file=sys.stderr)
        return 64
    if shutil.which(options["agy"]) is None:
        print(f"agy-rlcr-run: agy not found: {options['agy']}", file=sys.stderr)
        return 64
    driver = Driver(options, root)
    # Stopping the driver (Ctrl-C, kill, tmux kill-session) stops agy too.
    # A hangup is ignored when the driver was started that way (nohup).
    signal.signal(signal.SIGTERM, raise_keyboard_interrupt)
    if signal.getsignal(signal.SIGHUP) != signal.SIG_IGN:
        signal.signal(signal.SIGHUP, raise_keyboard_interrupt)
    try:
        return driver.run()
    except KeyboardInterrupt:
        if driver.conversation:
            log(f"stopped; the loop state is kept. Resume with: --resume {driver.conversation}")
        else:
            log("stopped before agy started a conversation; nothing to resume.")
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
