---
name: humanize-gen-plan
description: >-
  Turns a draft document into a Humanize implementation plan in agy: you
  (Gemini) write the plan, while Codex first critiques the draft and then
  reviews each revision of your plan. Use this skill when the user asks to
  generate a plan, turn a draft or idea into a plan, or run Humanize gen-plan.
---

# Generate a Humanize Plan

Humanize runtime root (all scripts below live here):

```text
{{HUMANIZE_RUNTIME_ROOT}}
```

You are the planner. You write the plan and every word a person reads. Codex only critiques your drafts and reports to you.

## How to Run It

1. Read the full procedure: `{{HUMANIZE_RUNTIME_ROOT}}/commands/gen-plan.md`. It was written for Claude Code. Carry it out in order, from Phase 0 to Phase 8, with the substitutions below.
2. `$ARGUMENTS` in the procedure means the arguments in the user's request, for example `--input docs/draft.md --output docs/plan.md --direct`. If the input or output path is missing, ask the user with `ask_question`.
3. Where the procedure and this skill disagree, follow this skill.

## Substitutions

| The procedure says | Do this in agy |
|--------------------|----------------|
| Claude (the planner) | you |
| `${CLAUDE_PLUGIN_ROOT}` | `{{HUMANIZE_RUNTIME_ROOT}}` |
| "ultrathink", "deeply think" | think the problem through carefully before you write |
| AskUserQuestion | `ask_question` |
| Read, Glob, Grep | `read_file`, `find_by_name`, `grep_search`, `list_dir` |
| Write tool, Edit tool | `write_file`, `edit_file` |
| Bash, shell command | `run_command` |
| Task tool with an `Explore` subagent | `invoke_subagent` with a read-only search task, or search yourself |
| Task tool with a `humanize:<name>` agent, such as `humanize:draft-relevance-checker` | read `{{HUMANIZE_RUNTIME_ROOT}}/agents/<name>.md` and do that check yourself |
| `/humanize:start-rlcr-loop <args>` | the `humanize-start-rlcr-loop` skill with the same arguments |

To load the config in Phase 0.5, run:

```bash
bash -c 'source "{{HUMANIZE_RUNTIME_ROOT}}/scripts/lib/config-loader.sh" && load_merged_config "{{HUMANIZE_RUNTIME_ROOT}}" "$(git rev-parse --show-toplevel)"'
```

It prints the merged config as JSON. Read `alternative_plan_language`, `gen_plan_mode` and `chinese_plan` from it.

## Asking Codex

Phases 3 and 5 ask Codex through `ask-codex.sh`, which takes the whole question as its argument. Plan prompts are long and full of quotes, so never type them into the command line:

1. Write the prompt to a file under `.humanize/gen-plan/`, for example `.humanize/gen-plan/codex-analysis.md`, then `codex-review-1.md`, `codex-review-2.md` and so on.
2. Run it with the file's content as one argument:

   ```bash
   "{{HUMANIZE_RUNTIME_ROOT}}/scripts/ask-codex.sh" "$(cat .humanize/gen-plan/codex-analysis.md)"
   ```

3. Codex can take many minutes. Run the command asynchronously and wait for it with `command_status`. Do not start the next phase before it finishes.
4. Codex's answer is for you only. Use it to improve the plan, but never paste it into the plan or show it to the user. When the user needs to know what Codex thinks, explain it in your own words.

## Writing for People

The plan is read by people as well as by the RLCR loop.

- Write all prose yourself, in plain everyday language: short sentences, and explain each technical term the first time you use it.
- Keep the template's machine-readable parts exactly as they are, because the RLCR loop and refine-plan read them: the section headings, the IDs (`AC-1`, `FUT-1`, `DEC-1`, `task1`, `cap1`), the field labels (`Claude Position`, `Codex Position`, `Tradeoff Summary`, `Decision Status`, `Source DEC`), and the task tags `coding` and `analyze`. In these labels "Claude" means you, the planner.
- Directly under the `## Claude-Codex Deliberation` heading, add this line: `Planner: Gemini in agy. The labels say "Claude" because Humanize tools expect those names.`
- In `## Task Breakdown`, `coding` tasks are done by the coding agent in the RLCR loop (you, in agy), and `analyze` tasks are sent to Codex. Say so in the tag legend above the table: write "`coding`: implemented by the coding agent (Gemini in agy)" instead of the template's "implemented by Claude".
- Record Codex's positions in the plan in your own words.
- Write the translated variant yourself when `alternative_plan_language` asks for one.
- Do not run `polish-gemini.sh`. You are already the writer.

## Rules

1. While planning, do not write code. Write only the plan file, its translated variant, and prompt files under `.humanize/gen-plan/`.
2. While planning, do not commit, push, or switch branches. If `--auto-start-rlcr-if-converged` starts the loop, the loop's own rules take over from there.
3. When you finish, tell the user in plain words: where the plan is, what it covers, how many acceptance criteria it has, how many Codex review rounds ran, and which decisions still wait for them. Then say how to start the work: with the `humanize-start-rlcr-loop` skill, or unattended from a terminal with `"{{HUMANIZE_RUNTIME_ROOT}}/scripts/agy-rlcr-run.sh" <plan-file>`.
