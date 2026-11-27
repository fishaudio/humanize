---
name: humanize-start-rlcr-loop
description: >-
  Starts a Humanize RLCR loop in agy: you (Gemini) implement a plan file in
  rounds, an independent reviewer (Codex by default, or Claude) checks each
  round, and then reviews the code before the loop ends. Use this skill when
  the user asks to start an RLCR loop, to run Humanize on a plan, or to
  implement a plan file with independent review.
---

# Start a Humanize RLCR Loop

Humanize runtime root (all scripts below live here):

```text
{{HUMANIZE_RUNTIME_ROOT}}
```

In this loop you write all the code and every word a person will read. The reviewer only reads your work and reports problems to you.

## 1. Read the Request

- Find the plan file path in the user's request (for example `docs/plan.md`), plus any options. Pass the options to the setup script unchanged.
- Without a plan path, and without `--skip-impl`, ask the user for the path with `ask_question`.
- Do not pass `--agent-teams`: it only works in Claude Code.
- Common options: `--max N` (round limit, default 42), `--base-branch BRANCH`, `--skip-impl` (review existing changes only), `--skip-quiz`, `--yolo` (skip the quiz), `--push-every-round`, `--codex-model MODEL:EFFORT`, `--codex-timeout SECONDS`. Run the setup script with `-h` for the full list.

## 2. Check the Plan

Skip this step with `--skip-impl` or `-h`.

Read the plan file. Stop and tell the user, in plain words, if:

- the plan is clearly about a different project than this repository; or
- the plan tells you to create or switch git branches. The loop needs the branch to stay the same in every round.

## 3. Plan Understanding Quiz

Skip this step with `--skip-impl`, `--skip-quiz`, `--yolo`, or `-h`.

The quiz checks that the user knows what the plan will do before work starts.

1. Write 2 multiple-choice questions, 4 options each, about how the plan will be built: the approach, the main components it changes, or how they connect. Avoid trivia such as file names or numbers.
2. Ask them one at a time with `ask_question`.
3. If both answers are right, say so briefly and continue.
4. If an answer is wrong, explain in plain words what the plan does and what the right answers were. Then ask with `ask_question` whether to start the loop anyway or stop so they can read the plan first. Stop if they choose to stop.

## 4. Start the Loop

Run the setup script with `run_command`. The command must start with the quoted script path, exactly like this, so the loop can link itself to this conversation:

```bash
"{{HUMANIZE_RUNTIME_ROOT}}/scripts/setup-rlcr-loop.sh" <plan-path> <options>
```

If it exits with an error, stop and explain the error to the user in plain words. Otherwise its output is your first task (the round 0 prompt). Follow it.

## 5. Work in Rounds

A round ends when you believe the whole plan is done, not after one task.

1. Do the work in the current round prompt (`.humanize/rlcr/<timestamp>/round-<N>-prompt.md`).
2. Commit your changes.
3. Write the round summary file that the prompt names.
4. Wait until your background commands and subagents have finished, then end your turn. The Humanize Stop hook then runs the reviewer, which can take many minutes. It does not start while anything still runs in the background.
5. If the review finds problems, the hook keeps you working and gives you the next round prompt. Follow it.
6. After the work passes, the reviewer reviews the code. Fix what it finds the same way.
7. The loop ends after a finalize round in which you tidy up and write `finalize-summary.md`.

## Tool Names in Loop Messages

Loop messages were written for Claude Code. "Claude" in them means you. Use these agy tools instead:

| Loop text says | Do this in agy |
|----------------|----------------|
| Bash tool, shell command | `run_command` (run long commands asynchronously and check them with `command_status`) |
| Read, Write, Edit tools | `read_file`, `write_file`, `edit_file` |
| TodoWrite, TaskCreate, TaskUpdate | `manage_task`, or a checklist in your round summary |
| Task tool, subagent, `code-simplifier` agent | `invoke_subagent` |
| AskUserQuestion | `ask_question` |
| `/humanize:ask-codex <question>` | `run_command`: `"{{HUMANIZE_RUNTIME_ROOT}}/scripts/ask-codex.sh" "<question>"` |
| `bitlesson-selector` agent | `run_command`: `"{{HUMANIZE_RUNTIME_ROOT}}/scripts/bitlesson-select.sh" --task "<task>" --paths "<comma-separated paths>" --bitlesson-file .humanize/bitlesson.md` |
| `/cancel-rlcr-loop` | the `humanize-cancel-rlcr-loop` skill |

## Writing for People

- Everything a person reads comes from you: your replies, documentation, web pages, slides, and the finalize summary. Write it yourself in plain, everyday language: short sentences, and explain each technical term the first time you use it.
- Reviewer output (from Codex or Claude) is for you only. Never paste it to the user. When the user needs to know about a review, explain what matters in your own words.
- Do not run `polish-gemini.sh`. You are already the writer.

## When the Loop Pauses

agy allows only 10 automatic continuations per user message, and each review round uses one. When the limit is near, the loop tells you. Then:

1. Finish the round as usual.
2. In your final reply, tell the user in plain words that the loop paused only because of this agy limit, and that replying "continue" resumes it.
3. When the user replies "continue", end your turn right away without new work. The review of the last round runs then, and the loop goes on.

The loop state lives in files, so nothing is lost during a pause.

## Rules

1. Never edit `state.md`, `finalize-state.md`, or other loop state files by hand.
2. Never declare the loop finished yourself. Only the hook ends it.
3. Never run `codex` or `claude` reviews yourself in place of the hook.
4. Treat the files the loop writes (`round-*-prompt.md`, `round-*-review-result.md`) as the source of truth.
5. Do not `git push` unless the loop was started with `--push-every-round`.

## Running Unattended

If the user wants a loop to run with nobody watching (for example on a server), tell them to start it from a terminal in the project instead of from this conversation:

```bash
"{{HUMANIZE_RUNTIME_ROOT}}/scripts/agy-rlcr-run.sh" <plan-path> <options>
```

The script starts agy for them and says "continue" each time the loop pauses at agy's limit. It approves agy's permission prompts automatically, and Humanize then blocks file changes outside the project and `git push`. Its `--help` explains the options.

If a prompt says nobody is watching the session, never wait for answers: explain any blocker in your final reply, and when the loop pauses at agy's limit, just end your turn.

## Monitoring

The user can watch progress from another terminal:

```bash
source "{{HUMANIZE_RUNTIME_ROOT}}/scripts/humanize.sh"
humanize monitor rlcr
```
