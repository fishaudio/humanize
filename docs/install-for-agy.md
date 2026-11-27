# Install Humanize for agy (Antigravity CLI)

This guide sets up Humanize inside agy, Google's Antigravity CLI. In this setup, Gemini writes the plan and the code, and an independent reviewer checks the work: Codex by default, or Claude if you choose it.

Everything people read comes from Gemini: its replies; the plans, documents, and web pages it writes; and the final summary at the end of the loop. The reviewer's output goes only to Gemini, which explains it to you in its own words.

## What You Need

- agy, signed in (run `agy` once and follow the sign-in steps).
- The reviewer CLI: `codex` (the default), or `claude` if you choose Claude as a reviewer.
- `git`, `jq`, and `python3`.

## Install

From the Humanize repository root:

```bash
./scripts/install-agy-plugin.sh
```

This writes the plugin to `~/.gemini/config/plugins/humanize/`:

| Path | What it is |
|------|------------|
| `plugin.json` | Plugin manifest |
| `hooks.json` | The hooks agy runs before and after tool calls, and when Gemini tries to stop |
| `skills/humanize-gen-plan/` | Skill that turns a draft into a plan |
| `skills/humanize-start-rlcr-loop/` | Skill that starts a loop |
| `skills/humanize-cancel-rlcr-loop/` | Skill that cancels a loop |
| `runtime/` | Humanize scripts, hooks, prompt templates, and command procedures used by the hooks and skills |
| `runtime/scripts/agy-rlcr-run.sh` | Script that runs a loop with nobody watching |

Run the same command again to update. It replaces the old copy.

Options:

```bash
# Install somewhere else, for example into one project only
./scripts/install-agy-plugin.sh --plugins-dir /path/to/project/.agents/plugins

# Show what would happen without writing anything
./scripts/install-agy-plugin.sh --dry-run
```

## Check the Install

```bash
agy plugin validate ~/.gemini/config/plugins/humanize
agy plugin list
```

`validate` should report 3 skills and 1 hook file.

## Write a Plan

A loop works from a plan file. To turn a rough draft into a plan, ask inside agy, for example:

```text
Use the humanize-gen-plan skill with --input docs/draft.md --output docs/plan.md
```

Gemini follows the same steps as `/humanize:gen-plan` in Claude Code and writes the plan itself:

1. Checks the file paths and confirms that the draft belongs to this repository.
2. Asks Codex to point out risks and gaps in the draft.
3. Writes an initial plan, asks Codex to review it, and revises it until they agree (up to 3 rounds).
4. Asks you about anything only you can decide.
5. Writes the final plan, with acceptance criteria, a task list, and a record of where Gemini and Codex agreed or disagreed.

Codex's notes go only to Gemini. The plan keeps the section names and labels that Humanize tools read, such as `Claude Position`. In a plan written in agy, "Claude" in those labels refers to Gemini, and the plan states this.

The options are the same as in Claude Code: `--direct` skips the Codex review rounds, `--discussion` keeps them, `--coach` adds short check-in questions, and `--auto-start-rlcr-if-converged` starts the loop right away when nothing is left for you to decide. See the [Usage Guide](usage.md#gen-plan).

## Start a Loop

From your project inside agy, ask to start a loop in plain words, for example:

```text
Use the humanize-start-rlcr-loop skill to start an RLCR loop on docs/plan.md
```

Gemini then:

1. reads the plan and checks that it belongs to this repository;
2. asks you two questions about the plan to make sure you know what it will build (add `--skip-quiz` to skip them);
3. runs the setup script and works through the plan in rounds;
4. tries to stop at the end of each round. The Humanize hook then asks the reviewer whether the round is done. If it is not, Gemini gets the feedback and keeps working;
5. once the work is done, the reviewer checks the code, and Gemini fixes what the reviewer finds in the same way;
6. finishes with a short tidy-up round and writes `finalize-summary.md` for you.

The options are the same as `/humanize:start-rlcr-loop` in Claude Code, except `--agent-teams`, which only works in Claude Code. See the [Usage Guide](usage.md#start-rlcr-loop).

To cancel, ask Gemini to use the `humanize-cancel-rlcr-loop` skill.

## The 10-Continuation Pause

agy lets a hook keep the agent going at most 10 times per message you send, and each review round uses one continuation. As a result, a long loop pauses about every 10 rounds:

- Before the pause, Gemini tells you that the loop stopped only because of this limit.
- Reply `continue`. The review of the last round runs, and the loop goes on from there.

The loop keeps its state in files under `.humanize/rlcr/`, so nothing is lost during a pause.

## Run a Loop Unattended

To run a loop with nobody watching, for example on a server, start it from a terminal in the project instead of from inside agy:

```bash
~/.gemini/config/plugins/humanize/runtime/scripts/agy-rlcr-run.sh docs/plan.md
```

The script starts agy with the `humanize-start-rlcr-loop` skill and replies `continue` for you each time the loop pauses at agy's limit. It adds `--skip-quiz` because nobody is there to answer the quiz. Any other loop options go after the plan file, as usual. When the loop finishes, the script prints Gemini's finalize summary; if the loop ends another way, it prints Gemini's last reply.

Because nobody can approve agy's permission prompts, the script approves them automatically. To keep that safe:

- Humanize blocks file changes outside the project;
- Humanize blocks `git push` unless you passed `--push-every-round`: it checks each command Gemini runs, and it also sets git itself to refuse pushes;
- agy keeps its file tools inside the project, and does not switch to paid AI credits when your subscription quota runs out.

These checks catch mistakes; they are not a sandbox. Shell commands can still reach outside the project, so use unattended runs only on machines and projects where that is acceptable.

The script stops by itself if three resumes in a row change nothing (`--stall-limit`), or after 50 resumes (`--max-resumes`). It saves agy's output in `.humanize/agy-runs/<time>/`. If the script itself stops (for example, after a reboot), run it again with `--resume <conversation-id>`; it prints the ID when it starts. Other options: `--model`, `--effort`, and `--log-dir`. Run it with `--help` for details.

Exit codes: `0` means the loop finished, `1` means it ended another way (for example, cancelled) or never started, and `2` means the script gave up.

To keep it running after you log out, start it inside `tmux` or with `nohup`.

## Choosing the Reviewer

Codex is the default for both review jobs. To use Claude instead, set `rlcr_verifier` (checks each round) and `rlcr_reviewer` (reviews the code) in `~/.config/humanize/config.json` or in the project's `.humanize/config.json`:

```json
{
  "rlcr_verifier": "claude",
  "rlcr_reviewer": "claude"
}
```

Claude runs read-only: it can read and search files, and nothing else. The loop hands it the diff as a file to read. See [Choosing the RLCR Reviewers](usage.md#choosing-the-rlcr-reviewers).

## Watch Progress

In another terminal:

```bash
source ~/.gemini/config/plugins/humanize/runtime/scripts/humanize.sh
humanize monitor rlcr
```

## How It Works

agy and Claude Code both run hook scripts, but they send different data. The plugin's hooks call `runtime/hooks/agy-hook.sh`, which hands each event to `agy-hook-adapter.py`. The adapter:

- finds the project from the folder agy is working in, and does nothing unless that project has an active loop;
- maps agy's tool calls (`write_file`, `edit_file`, `read_file`, `run_command`, and their older names) to the checks Humanize already runs in Claude Code, such as "do not edit the loop's state files" and "do not push";
- links the loop to the agy conversation right after setup, so other agy conversations in the same project are not affected;
- runs the same Stop hook as Claude Code when Gemini finishes a turn normally, and passes the reviewer's feedback back to Gemini;
- does not start a review when you cancel a turn, when agy hits an error, when a background command or subagent is still running, or when agy is past its continuation limit.

When a check blocks a tool call, agy shows the reason. Otherwise, the plugin stays silent and agy's own permission settings decide, so installing the plugin never grants extra permissions. The only extra checks come from `agy-rlcr-run.sh`: it sets `HUMANIZE_AGY_UNATTENDED=1`, and the adapter then also blocks file changes outside the project and `git push`.

## Troubleshooting

- **Nothing happens when Gemini stops.** Check that the loop is active (`ls .humanize/rlcr/*/state.md`) and that agy loaded the plugin (`agy plugin list`).
- **"Codex CLI Not Found" or "Claude CLI Not Found".** Install the reviewer CLI, or switch `rlcr_verifier` and `rlcr_reviewer` to the one you have.
- **Every file edit is blocked with a Humanize message.** Read the message: it names the file or command and the rule. Loop state files and the goal tracker's fixed section are protected on purpose.
- **python3 is missing.** Without it, the hooks stay silent and the loop cannot run. Install python3 and run the installer again.
