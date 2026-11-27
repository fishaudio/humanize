# Humanize Usage Guide

Detailed usage documentation for the Humanize plugin. For installation, see [Install for Claude Code](install-for-claude.md).

## How It Works

Humanize creates an iterative feedback loop with two phases:

1. **Implementation Phase**: Claude works on your plan, Codex reviews summaries until COMPLETE
2. **Review Phase**: `codex review --base <branch>` checks code quality with `[P0-9]` severity markers

The loop continues until all acceptance criteria are met or no issues remain.

When a plan includes `Feature Map / Capability Map`, RLCR also tracks a per-round
`Capability Anchor`. Claude uses it to keep implementation tied to the relevant
business, design, and implementation context, while Codex reviews capability-map
alignment alongside normal acceptance criteria.

## Begin with the End in Mind

Before the RLCR loop starts any work, Humanize runs a **Plan Understanding Quiz** -- a brief pre-flight check that verifies you genuinely understand the plan you are about to execute.

### Why This Exists

The most expensive failure in AI-assisted development is not a bug. It is running a 40-round RLCR loop on a plan you never actually read. We call this **wishful coding**: treating a generated plan like a wish -- toss it in, hope for the best, check back later.

The problem is structural. An RLCR loop is an amplifier: it will faithfully execute whatever plan you give it. If the plan is wrong, the loop makes it wrong faster and at scale. If the plan is right but you do not understand it, you cannot course-correct when Codex raises questions, and the loop drifts.

Understanding your plan before execution is not optional overhead. It is the single highest-leverage thing you can do to ensure the loop succeeds.

### How the Quiz Works

When you run `start-rlcr-loop`, an independent agent analyzes the plan and generates two multiple-choice questions about the plan's technical implementation details:

1. **What components are changing and how?** -- Tests whether you know the core mechanism.
2. **How do the pieces connect?** -- Tests whether you understand the architecture being modified.

If you answer both correctly, the loop proceeds immediately. If you miss one or both, Humanize explains what the plan actually does and offers a choice: proceed anyway, or stop and review.

The agent is asked to write in plain words, and when [Gemini polishing](#polish-gemini) is on, the questions, options, and plan summary are also polished for readability before you see them. The answers are not sent, and the options keep their letters.

The quiz is advisory, not a gate. You always have the option to proceed. But that moment of friction -- the two seconds it takes to read the question and realize you do not know the answer -- is the entire point.

### Skipping the Quiz

- `--skip-quiz` -- Skip the quiz only. The rest of the RLCR loop behaves normally.
- `--yolo` -- Skip the quiz AND let Claude answer Codex's open questions directly (`--claude-answer-codex`). This is full automation mode for users who have already reviewed the plan and want to hand over complete control.
- Plans started via `gen-plan --auto-start-rlcr-if-converged` skip the quiz automatically, because the gen-plan convergence discussion already verified the user's understanding.

## Typical Planning Flow

1. Generate the initial implementation plan:
   ```bash
   /humanize:gen-plan --input draft.md --output docs/plan.md
   ```
   The generated plan includes a `Feature Map / Capability Map` that records
   capability dependencies and context before tasks are split into executable
   `coding` and `analyze` work.
2. If the plan is reviewed with comment annotations, refine it and generate a QA ledger:
   ```bash
   /humanize:refine-plan --input docs/plan.md
   ```
3. Start the RLCR loop on the refined plan:
   ```bash
   /humanize:start-rlcr-loop docs/plan.md
   ```

## Commands

| Command | Purpose |
|---------|---------|
| `/gen-idea <idea-or-path>` | Generate a repo-grounded idea draft with N parallel directions |
| `/explore-idea <draft-or-directions.json>` | Launch bounded parallel prototype workers and synthesize a two-tier report |
| `/start-rlcr-loop <plan.md>` | Start iterative development with Codex review |
| `/cancel-rlcr-loop` | Cancel active loop |
| `/gen-plan --input <draft.md> --output <plan.md>` | Generate structured plan from draft |
| `/refine-plan --input <annotated-plan.md>` | Refine an annotated plan and generate a QA ledger |
| `/ask-codex [question]` | One-shot consultation with Codex |
| `/polish-gemini --input <file>` | Readability-only polish of human-facing text with Gemini |

## Command Reference

### gen-idea

```
/humanize:gen-idea <idea-text-or-path> [--n <int>] [--output <path>]
```

Generates a repo-grounded idea draft using directed-diversity exploration. A lead agent picks N orthogonal directions, N parallel Explore subagents develop each direction with objective evidence from the repo, and the lead synthesizes a draft with one primary direction plus N-1 alternatives.

**Outputs:**
- Draft file: `.humanize/ideas/<slug>-<timestamp>.md` (or `--output` path)
- Companion JSON: `<draft-path-without-.md>.directions.json` — lossless record of all direction proposals, used as input to `explore-idea`

**Options:**
- `--n <int>` — number of parallel directions (default: 6)
- `--output <path>` — custom output path for the draft (must have `.md` suffix)

### explore-idea

```
/humanize:explore-idea <draft.md | draft.directions.json> [--directions ids] [--concurrency N] [--max-worker-iterations N] [--worker-timeout-min N] [--codex-timeout-min N]
```

Launches bounded parallel prototype workers — one per selected direction — each running in an isolated git worktree. After all workers complete, synthesizes an explore report plus a plan-ready final idea:
- **Tier 1**: Best product direction (ranked by user value, evidence, strategic fit)
- **Tier 2**: Most implementation-ready prototype (ranked by outcome: task status, Codex verdict, tests, commits)

**Options:**
- `--directions <ids>` — comma-separated `direction_id` or `source_index` values to run (default: first 6 by display order)
- `--concurrency <N>` — parallel worker count (default: 6, max: 10)
- `--max-worker-iterations <N>` — per-worker iteration cap (default: 2, max: 3)
- `--worker-timeout-min <N>` — worker timeout in minutes (default: 60, max: 60)
- `--codex-timeout-min <N>` — Codex call timeout in minutes (default: 20, max: 20)

**Run artifacts** stored in `.humanize/explore/<RUN_ID>/`:
- `manifest.json` — coordinator state and per-worker metadata
- `dispatch-prompts/` — exact prompts sent to each worker
- `worker-results.jsonl` — machine-readable result rows
- `explore-report.md` — audit report with two-tier rankings, adoption paths, and cleanup guidance
- `final-idea.md` — plan-ready synthesis artifact for `/humanize:gen-plan`

Default follow-up:
```bash
/humanize:gen-plan --input .humanize/explore/<run-id>/final-idea.md --output docs/plan.md
/humanize:start-rlcr-loop docs/plan.md
```

### start-rlcr-loop

```
/humanize:start-rlcr-loop [path/to/plan.md | --plan-file path/to/plan.md] [OPTIONS]

OPTIONS:
  --plan-file <path>     Explicit plan file path (alternative to positional arg)
  --max <N>              Maximum iterations before auto-stop (default: 42)
  --codex-model <MODEL:EFFORT>
                         Codex model and reasoning effort (default from config, fallback gpt-5.5:high)
  --codex-timeout <SECONDS>
                         Timeout for each Codex review in seconds (default: 5400)
  --track-plan-file      Indicate plan file should be tracked in git (must be clean)
  --push-every-round     Require git push after each round (default: commits stay local)
  --base-branch <BRANCH> Base branch for code review phase (default: auto-detect)
                         Priority: user input > remote default > main > master
  --full-review-round <N>
                         Interval for Full Alignment Check rounds (default: 5, min: 2)
                         Full Alignment Checks occur at rounds N-1, 2N-1, 3N-1, etc.
  --skip-impl            Skip implementation phase, go directly to code review
                         Plan file is optional when using this flag
  --claude-answer-codex  When Codex finds Open Questions, let Claude answer them
                         directly instead of asking user via AskUserQuestion
  --agent-teams          Enable Claude Code Agent Teams mode for parallel development.
                         Requires CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 environment variable.
                         Claude acts as team leader, splitting tasks among team members.
  --yolo                 Skip Plan Understanding Quiz and let Claude answer Codex Open
                         Questions directly. Alias for --skip-quiz --claude-answer-codex.
  --skip-quiz            Skip the Plan Understanding Quiz only (without other changes).
  -h, --help             Show help message
```

### gen-plan

```
/humanize:gen-plan --input <path/to/draft.md> --output <path/to/plan.md> [OPTIONS]

OPTIONS:
  --input   Path to the input draft file (required)
  --output  Path to the output plan file (required)
  --auto-start-rlcr-if-converged
             Start the RLCR loop automatically when the plan is converged
             (discussion mode only; ignored in --direct)
  --discussion  Use discussion mode (iterative Claude/Codex convergence rounds)
  --direct      Use direct mode (skip convergence rounds, proceed immediately to plan)
  --coach
             Run mandatory short-answer stage quizzes before expanding each planning layer
  -h, --help             Show help message
```

The gen-plan command transforms rough draft documents into structured implementation plans.

Workflow:
1. Validates input/output paths
2. Checks if draft is relevant to the repository
3. Analyzes draft for clarity, consistency, completeness, and functionality
4. Engages user to resolve any issues found
5. When `--coach` is enabled, runs mandatory stage quizzes after each planning stage; normal plan decision questions stay separate, and quiz mismatches become design drift, AI design corrections, or background gaps before overall acceptance
6. Generates a structured plan.md with acceptance criteria, capability map, and task routing tags
7. Optionally starts `/humanize:start-rlcr-loop` if `--auto-start-rlcr-if-converged` conditions are met

The capability map supplements the task breakdown: it tells Claude and Codex
which global feature or capability each task belongs to, what it depends on, and
which business/design/implementation context must be preserved during RLCR.

If reviewers later annotate the generated plan with comment blocks, run
`/humanize:refine-plan --input <plan.md>` before starting or resuming implementation.

### refine-plan

```
/humanize:refine-plan --input <path/to/annotated-plan.md> [OPTIONS]

OPTIONS:
  --input <path>        Path to the annotated plan file (required)
  --output <path>       Path to the refined plan output file
                        Defaults to refining --input in place
  --qa-dir <path>       Directory for QA document output
                        Default: .humanize/plan_qa
  --alt-language <LANG>
                        Generate translated plan and QA variants
                        Supported: zh, ko, ja, es, fr, de, pt, ru, ar
                        Full language names are also accepted; en/English is a no-op
  --discussion          Interactive mode for ambiguous comment classification
  --direct              Non-interactive mode; makes minimal safe assumptions
  -h, --help            Show help message
```

The refine-plan command reads an annotated `gen-plan` document, processes embedded review
comments, removes those comment blocks from the final plan, and writes a QA ledger that records
how each comment was handled.

**Usage examples:**

```bash
# Refine a plan in place and write QA output to the default directory
/humanize:refine-plan --input docs/plan.md

# Write the refined plan to a new file and store QA output in a custom directory
/humanize:refine-plan --input docs/plan.annotated.md --output docs/plan.refined.md --qa-dir docs/plan-qa

# Run in direct mode and generate translated variants
/humanize:refine-plan --input docs/plan.md --direct --alt-language zh
```

**Annotated comment block format:**

`refine-plan` supports three comment formats for reviewer annotations. Both inline
and multi-line comment blocks are supported in all formats:

**Classic format (CMT:/ENDCMT):**
```markdown
Text before CMT: clarify why AC-3 is split here ENDCMT text after
```

```markdown
CMT:
Please investigate whether this task should depend on task4 or task5.
If the dependency is unclear, add a pending decision instead of guessing.
ENDCMT
```

**Short tag format (<cmt></cmt>):**
```markdown
Text before <cmt>clarify why AC-3 is split here</cmt> text after
```

```markdown
<cmt>
Please investigate whether this task should depend on task4 or task5.
If the dependency is unclear, add a pending decision instead of guessing.
</cmt>
```

**Long tag format (<comment></comment>):**
```markdown
Text before <comment>clarify why AC-3 is split here</comment> text after
```

```markdown
<comment>
Please investigate whether this task should depend on task4 or task5.
If the dependency is unclear, add a pending decision instead of guessing.
</comment>
```

Rules:
- At least one non-empty comment block must exist in the input file.
- Comment markers inside fenced code blocks or HTML comments are ignored.
- Empty comment blocks are removed but do not create QA ledger entries.
- The input plan must still follow the `gen-plan` section schema.
- All three formats can be mixed within the same file.

**QA output structure:**

For an input plan named `plan.md`, the default QA output path is `.humanize/plan_qa/plan-qa.md`.
The generated QA document includes:

- `## Summary`: overall refinement outcome and comment counts
- `## Comment Ledger`: one row per raw `CMT-N` block with classification, location, excerpt, and disposition
- `## Answers`: responses to question comments and any clarifying edits
- `## Research Findings`: repository research performed for `research_request` comments
- `## Plan Changes Applied`: changes made for `change_request` comments and cross-reference updates
- `## Remaining Decisions`: unresolved items or assumption-heavy decisions that still need user input
- `## Refinement Metadata`: input/output paths, QA path, classification counts, modified sections, convergence status, and date

Disposition values in the ledger are `answered`, `applied`, `researched`, `deferred`, or
`resolved`.

If `--alt-language` is set to a supported non-English language, the command also generates
translated plan and QA variants by inserting `_<code>` before the file extension, such as
`plan_zh.md` and `plan-qa_zh.md`.

### ask-codex

```
/humanize:ask-codex [OPTIONS] <question or task>

OPTIONS:
  --codex-model <MODEL:EFFORT>
                         Codex model and reasoning effort (default from config, fallback gpt-5.5:high)
  --codex-timeout <SECONDS>
                         Timeout for the Codex query in seconds (default: 3600)
  -h, --help             Show help message
```

The ask-codex skill sends a one-shot question or task to Codex and returns the response
inline. Unlike the RLCR loop, this is a single consultation without iteration -- useful
for getting a second opinion, reviewing a design, or asking domain-specific questions.

Responses are saved to `.humanize/skill/<timestamp>/` with `input.md`, `output.md`,
and `metadata.md` for reference.

### polish-gemini

```
/humanize:polish-gemini --input <file|-> [OPTIONS]

scripts/polish-gemini.sh --input <file|-> [--output <file>]
                         [--format markdown|text|segments|html] [--auto]
                         [--backend agy|openrouter]
                         [--model MODEL] [--effort xhigh|high|medium|low]
                         [--timeout SECONDS] [--max-tokens N] [--max-bytes N]
                         [--strict]

OPTIONS:
  --input <file|->       Source document, or - for stdin (required)
  --output <file>        Write the result to this file atomically; may equal --input.
                         Without it, the result goes to stdout.
  --format <name>        markdown, text, segments or html. Default: from the file
                         extension (.html/.htm -> html, .md -> markdown, else text)
  --auto                 Automatic call site: skip when gemini_polish_enabled is false
                         or the config cannot be loaded
  --backend <name>       agy (default) or openrouter
  --model <id>           Model of the selected backend: an agy model name
                         (default: gemini-4-neon) or an OpenRouter model ID
                         (default: google/gemini-4-neon)
  --effort <level>       Reasoning effort (default: medium)
  --timeout <seconds>    Overall deadline for the request (default: 900)
  --max-tokens <n>       OpenRouter completion budget, reasoning included (default: 131072)
  --max-bytes <n>        Largest input to send (default: 262144)
  --strict               Exit 3 instead of 0 when the original had to be delivered
```

Claude and Codex often write documents full of jargon. `polish-gemini` sends text that people will read to a Gemini model for a readability-only pass, then delivers either the polished text or the exact original bytes. By default the request goes through agy, the Antigravity CLI, on the Gemini subscription you are signed in to, with Gemini 4 Neon at medium effort, so a run costs nothing per call. OpenRouter, which bills each call, is the other backend (see [Backends](#backends)).

Gemini acts only as a copy editor:

- Gemini gets no tool it can use, so it cannot read files, run commands, or search the web. On OpenRouter the request carries no tools, and web-search model IDs (ending in `:online`) are refused. agy is an agent with such tools, so every polish run locks them down, and a run in which agy tries any tool is rejected (`reason=tool_call`).
- The document is sent as data between per-run marker lines. Instructions inside the document are not followed.
- Gemini may reword sentences, replace jargon with plainer words, add brief glosses for terms already present, split long sentences, and fix grammar.
- Gemini must not translate, add or remove facts, change negations or obligation words, or change code, identifiers, paths, URLs, numbers, or document structure.
- English words inside Chinese, Japanese, or Korean text stay as written, even when they are jargon. Gemini may gloss one where it first appears, in the language of the surrounding text. Replacing them would change the mix of scripts, and the guard would reject the whole reply as a translation.

#### When it runs

Polishing is on by default (`gemini_polish_enabled: true`) in four scenarios, where Claude runs it with `--auto`:

1. **Writing documentation** for people: README files, files under `docs/`, guides, reports, release notes.
2. **Making web pages**: `.html` files are handled by the HTML adapter. Component files (JSX, TSX, Vue, Svelte) use the skill's manual segments procedure.
3. **Writing the RLCR finalize summary**: the finalize prompt tells Claude to polish `finalize-summary.md`. Round summaries are never polished.
4. **Asking the Plan Understanding Quiz**: `start-rlcr-loop` writes the questions, options, and plan summary to `.humanize/quiz/quiz-segments.txt` and polishes them with `--format segments` before it asks them. The answer letters are not sent. If a polished question or option fails Claude's review, its original text is used.

Everything else (chat replies, commit messages, PR descriptions, code comments, idea drafts, plans) is polished only when you ask. Plan files, round summaries, the goal tracker, review results, QA ledgers, code, and config are never polished automatically because tools parse them.

`--auto` marks an automatic call site. With `--auto`, the script skips when `gemini_polish_enabled` is `false` (`reason=disabled`) or when the config cannot be loaded (`reason=config_error`). Without `--auto`, an explicit request always runs.

#### Backends

`gemini_polish_backend` picks where the request goes. `--backend` and the `HUMANIZE_POLISH_BACKEND` environment variable override it.

| Backend | How it runs | Cost | Needs |
|---------|-------------|------|-------|
| `agy` (default) | One headless run of the Antigravity CLI with model `gemini_polish_agy_model` (default `gemini-4-neon`) | Uses your Gemini subscription quota; no charge per call | `agy` installed and signed in |
| `openrouter` | One request to the OpenRouter chat completions API with model `gemini_polish_model` (default `google/gemini-4-neon`) | Billed per call | An OpenRouter API key |

Both use `gemini_polish_reasoning_effort` (default `medium`), the same contract, the same guard, and the same rule that any failure delivers the original. `--model` names the model of the selected backend.

##### The agy backend

The script looks for `agy` on `PATH`, then at `~/.local/bin/agy`. Set `gemini_polish_agy_bin` (or `HUMANIZE_POLISH_AGY_BIN`) to use another path. Sign in once by running `agy` in a terminal with the Google account that has your Gemini subscription. `agy models` lists the models you can use; the model name and the effort are passed separately (`--model gemini-4-neon --effort medium`).

agy is an agent with tools that edit files, run commands, search the web, and more, and your own agy settings may approve them without asking. Each polish run therefore:

- runs agy from a new, empty temporary folder, which agy treats as its workspace, and removes the folder afterwards;
- passes settings for this run only, which agy never saves: `toolPermission` `strict` (every tool needs an approval that a headless run cannot give, so agy refuses the call), an empty `agentMode` (no Auto mode), no access outside the workspace, no trusted folders, `useG1Credits` off (a used-up quota never turns into paid AI credits), and deny rules for `command(*)`, `write_file(*)`, `read_file(*)`, `read_url(*)`, and `mcp(*)`;
- puts a `PreToolUse` hook in that folder that denies every tool call, including web search, which permission rules do not cover;
- turns off slash commands and skills (`--disable-slash-commands`) and turns on the terminal sandbox (`--sandbox`), and never passes `--dangerously-skip-permissions`;
- sends the contract and the document on standard input, never on the command line;
- hides `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`, and `AGY_ADC_AUTH` from agy, so it uses the signed-in subscription and never a key that bills per call;
- reads agy's `stream-json` events and uses the reply only when agy confirmed the strict permission mode and no tool step or denied action appears.

agy's log names the model it actually used. The run record keeps that name as `model_label`, for example `Gemini 4 Neon (Medium)`.

When agy cannot polish, the original is delivered and the last line says why:

| Reason | Meaning |
|--------|---------|
| `agy_not_found` (skipped) | No `agy` command was found |
| `auth` | agy is not signed in |
| `quota_exhausted` | The subscription quota is used up |
| `rate_limited` | Too many requests for now |
| `bad_model` | agy does not offer the configured model |
| `timeout` | agy did not finish within `gemini_polish_timeout` |
| `agy_lockdown` | agy did not confirm the strict tool permission mode |
| `agy_error` | Any other agy error; the message is shown |

No agy failure falls back to OpenRouter on its own, so polishing never starts costing money without your say. Set `gemini_polish_fallback_to_openrouter` to `true` to send the document to OpenRouter after an agy failure. The fallback needs an OpenRouter API key, and a rejected reply never falls back. The run record then says `backend: openrouter` and `fallback_from: agy:<reason>`.

#### API key setup (OpenRouter backend)

The OpenRouter backend, and the optional fallback, need an [OpenRouter](https://openrouter.ai/) API key. The agy backend needs none. The script looks for the key in this order:

1. the `OPENROUTER_API_KEY` environment variable;
2. the file named by `gemini_polish_api_key_file`, which holds either the raw key or one `OPENROUTER_API_KEY=value` line (an optional `export` prefix is allowed).

```bash
printf '%s\n' 'sk-or-...' > ~/.env/openrouter_key
chmod 600 ~/.env/openrouter_key
```

```json
{
  "gemini_polish_api_key_file": "~/.env/openrouter_key"
}
```

The key is read inside the Python helper. It is never placed on a command line, it never appears in run records, cache files, stdout, or stderr, and agy never sees it. A key file that group or others can read produces a warning. On the OpenRouter backend without a key, the original is delivered with `reason=no_api_key`.

#### Outcomes and exit codes

Every run ends with exactly one line on stderr:

```
polish-gemini: outcome=<polished|unchanged|skipped|rejected|failed> reason=<code> delivered=<yes|no>
```

| Outcome | Meaning | Example reasons |
|---------|---------|-----------------|
| `polished` | The guard accepted a rewrite and it was delivered | `ok` |
| `unchanged` | Gemini returned the same text | `identical` |
| `skipped` | Nothing was sent; the original was delivered | `agy_not_found`, `no_api_key`, `disabled`, `config_error`, `empty_input`, `too_large`, `sentinel_collision`, `secret_in_input`, `unsupported_encoding`, `unsupported_html`, `invalid_segments`, `nothing_to_polish`, `missing_dependency` |
| `rejected` | The reply failed the guard; the original was delivered | `envelope`, `structure`, `region_changed`, `protected_token`, `inline_markup`, `script_changed`, `length_ratio`, `segment_mismatch`, `markup_in_text`, `html_mismatch`, `tool_call` |
| `failed` | The request failed; the original was delivered | `network`, `auth`, `quota_exhausted`, `insufficient_credits`, `rate_limited`, `bad_model`, `agy_lockdown`, `agy_error`, `provider_error`, `timeout`, `truncated`, `empty_response`, `bad_json`, `api_error`, `internal_error`, `delivery_error`, `interrupted`, `usage_error` |

| Exit code | Meaning |
|-----------|---------|
| `0` | Content delivered: the polished text or the exact original bytes |
| `3` | `--strict` only: the original was delivered because polishing was skipped, rejected, or failed |
| `1` | Usage error; nothing delivered |
| `4` | Delivery failed (for example an unwritable `--output`); the destination is unchanged |
| `130` / `143` | Interrupted by SIGINT / SIGTERM; nothing is delivered if the signal arrives before delivery starts |

Delivery to stdout is a single write after every check has finished. Delivery to `--output` goes through a temporary file in the same directory and a rename, so the file is either the old content or the new content.

A signal that arrives while delivery is under way does not cut it short: the write or rename finishes, the outcome line still describes what was delivered (for example `outcome=polished reason=ok delivered=yes`), and the run exits 130 or 143. This also holds for a Ctrl-C sent to the whole process group while the fallback copy runs without Python. `reason=interrupted` with `delivered=no` means the signal came before delivery and nothing was written. A signal that was ignored when the run started (for example SIGINT in a background job started by a non-interactive shell) stays ignored. The script stays the runner's process while the Python helper starts and works: a SIGINT or SIGTERM sent to it, or to its whole process group, before delivery begins ends the run with `reason=interrupted`, `delivered=no`, and exit 130 or 143, also while the helper is still starting. The helper reports that it is ready by writing one byte to a private named pipe (created in `TMPDIR` or `/tmp` and removed again before the helper starts; the script uses it only after checking that what it opened is a named pipe it owns, so a name replaced in a shared directory cannot redirect the byte into another file) and reads no input until the script releases it with SIGUSR1; a signal that came before that is passed on to the helper, which then ends the run. If the script itself is killed (for example with SIGKILL), the helper notices before it delivers and ends as interrupted with nothing delivered. When no such pipe can be made, the helper is not started: the script keeps handling SIGINT and SIGTERM and delivers the original itself (`outcome=skipped reason=missing_dependency delivered=yes`). Diagnostic lines are always single lines starting with `polish-gemini:`; line breaks and control characters in error messages, file names, and config values are replaced with spaces, and no diagnostic can start with `outcome=`. A malformed reply, or any unexpected error inside the script, still delivers the original (`reason=bad_json`, `api_error`, or `internal_error`). When `python3` 3.7 or newer or the helper files cannot be found or started (also when the interpreter disappears between the version check and the start), the script delivers the original itself (`outcome=skipped reason=missing_dependency delivered=yes`).

#### OpenRouter request details

- One `POST <gemini_polish_base_url>/chat/completions` per run, plus at most one retry.
- The body holds the model, a system message with the polish-only contract (`prompt-template/gemini/polish-contract.md`), the document in the user message, `reasoning: {"effort": ..., "exclude": true}`, and `max_tokens`. It never holds `tools`, `tool_choice`, or `plugins`.
- If the API answers HTTP 400 and explicitly rejects reasoning effort `xhigh`, the script retries once with `high` and records `effort_used: high`.
- HTTP 429 is retried once, after `Retry-After`, if that still fits inside the deadline.
- The reply is accepted only for HTTP 200, valid JSON with valid Unicode, no `error` field (any value except `null` counts as an error), `finish_reason` `stop`, no tool calls, and non-empty text inside exactly one output block.
- `effort_used` in the run record is the effort of the last request sent, even when that request failed.

#### The guard and its limits

A local, deterministic guard checks every reply before delivery. For Markdown and text it requires:

- the same blocks, one to one and in order: headings and their levels, paragraphs, list items, and table rows and columns;
- blank lines where Markdown sees them;
- the same list nesting, list markers, task boxes, and blockquotes;
- byte-identical front matter, code blocks, HTML blocks, and text between `<!-- polish:off -->` and `<!-- polish:on -->`. Lines that the two reference renderers (cmark-gfm and markdown-it) may read differently are also kept byte for byte;
- the same protected tokens in each block, in the same order: inline code, math, URLs, paths, identifiers, numbers, and similar tokens;
- the same inline markup: HTML tags, links and images, and emphasis;
- the same writing scripts in each block (for example Latin, Han, Kana, Hangul, Cyrillic, Arabic), with similar shares;
- length ratios between 0.5 and 2.0 per block and between 0.6 and 1.8 for the whole document. A block under 40 characters may grow to at most twice its length or 12 more characters, whichever is larger. Set `HUMANIZE_POLISH_BLOCK_RATIO` or `HUMANIZE_POLISH_DOC_RATIO` (format `LOW:HIGH`) to change them.

Every rule, with its edge cases, is listed in [Polish Guard Rules](polish-guard-rules.md).

The guard cannot prove that meaning is unchanged. It does not detect translation between two languages that use the same script (for example English to Spanish), changed negations, caveats, or obligation words, numbers that keep their order but move to other nouns (`2 workers and 5 retries` becoming `2 retries and 5 workers`), or conversion between Simplified and Traditional Chinese. That is why Claude reviews every polished result against a checklist (same claims, same negations and caveats, same obligation strength, same language and variant, glosses only explain existing terms, nothing added, nothing dropped) before delivering it.

The guard errs toward rejecting. A rewrite of a name written as `__word__` (treated as an identifier), a less common slash pair such as `black/white` reworded as `black and white` (treated as a path), a paragraph or segment whose bracketed texts that hold emphasis markers may be links under more than four different labels (also when they sit inside an inline `polish:off` region of that paragraph), or a cut that shortens a wordy document below the 0.6 document ratio is rejected even when it is harmless; the original is then delivered.

Documents that contain the text `@@HUMANIZE-POLISH-` are not sent (`reason=sentinel_collision`), because that prefix is reserved for the marker lines. Documents with mixed line endings or bare carriage returns are not sent either (`reason=unsupported_encoding`), and the guard rejects them too; files that use CRLF throughout are fine (the guard reads them as line feeds).

#### HTML pages

For `.html` and `.htm` files, the script polishes only visible text: text nodes inside `<body>` and `<title>`, and the values of `alt`, `title`, `aria-label`, and `placeholder`, quoted or unquoted, on any element that is not excluded (including `<html>`, `<body>`, and elements in `<head>` such as `<link title=...>`). A new unquoted value has its spaces, quotes, `=`, and a trailing `/` written as character references, so it stays one value. It skips `script`, `style`, `template`, `code`, `pre`, `kbd`, `samp`, `noscript`, `textarea`, `svg`, `math`, `iframe`, `xmp`, `listing`, `plaintext`, `noembed`, `noframes`, elements with an inline `white-space: pre` style (and everything nested in all of these), whitespace-only text, and text that contains template syntax (`{{`, `}}`, `{%`, `${`, `<%`). Text and attribute values between `<!-- polish:off -->` and `<!-- polish:on -->` comments are skipped as well. Only HTML whitespace is collapsed in the text sent to the model; non-breaking spaces are kept. Character references such as `&amp;` must come back unchanged. The polished strings are put back at their original offsets with `&`, `<`, `>`, and the attribute quote escaped, and the page is parsed again to confirm that tags, attributes, comments, scripts, and styles are unchanged. A page is skipped (`reason=unsupported_html`) when the parser cannot map it to source offsets, when a non-void element is written self-closing outside SVG or MathML (browsers ignore the slash, so `<script/>` still opens a script), when attribute syntax could be read two ways, or when eligible text has a character reference without its semicolon (such as `&copy 2026`). CSS rules in stylesheets that preserve whitespace are not detected.

#### Run records

Each run that sends a request writes `.humanize/skill/<timestamp>-<pid>-<hex>/` with `input.md`, a copy of the source, the raw `candidate.txt`, the delivered `output.md`, and `metadata.md` (`tool: gemini`, `mode: polish`, `backend` (`agy` or `openrouter`), model, `model_label` for agy, `fallback_from` after a fallback, `effort_used`, status, outcome, reason, token counts, and cost, which is `subscription` for agy). The cache directory under `~/.cache/humanize/` holds `gemini-run.cmd` (the OpenRouter request without the key, or the agy command line and its standard input), `gemini-run.out` (the response without reasoning text, or agy's events), `gemini-run.log`, and for agy `agy-run.log`, agy's own log. Polish runs appear in `humanize monitor gemini` and `humanize monitor skill`.

#### Privacy and cost

- **Privacy**: polishing is on by default, so in the four default scenarios the document text is sent to Google: through agy on the default backend, or to OpenRouter and on to Google on the OpenRouter backend. agy also keeps its own conversation history under `~/.gemini/antigravity-cli/`. Local copies of each run are kept under `.humanize/skill/` (gitignored). Set `gemini_polish_enabled` to `false` to stop automatic polishing.
- **Cost and time on agy**: a run uses your Gemini subscription quota and costs nothing per call. In tests on 2026-11-24 with Gemini 4 Neon at medium effort, short documents (one to three paragraphs) took 14 to 17 seconds and a six-section document took 31 seconds (about 500 to 2,000 reasoning tokens); the same documents on Gemini 4 Hydrogen at `xhigh` through OpenRouter took 12 seconds to 2 minutes. Each run also carries agy's own instructions, about 11,000 input tokens, which count against the subscription quota.
- **Cost and time on OpenRouter**: each call is billed. These numbers are from Gemini 4 Hydrogen at reasoning effort `xhigh`, the earlier default: `xhigh` is slow and costs money, and the amount of reasoning varies from run to run. In tests on 2026-11-18, short documents (one to three paragraphs) took 12 seconds to 2 minutes and cost $0.02 to $0.14 (about 1,700 to 18,000 reasoning tokens), and a six-section document took about 2 minutes and cost about $0.15 (about 17,000 reasoning tokens). With `max_tokens` at 8,000, one request ran out of tokens before answering, which is why the default is 131,072. Lowering `gemini_polish_reasoning_effort` (for example to `high` or `medium`) reduces both time and cost.

#### Environment variables

| Variable | Purpose |
|----------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key (takes precedence over `gemini_polish_api_key_file`); never passed to agy |
| `HUMANIZE_POLISH_BACKEND` | Overrides `gemini_polish_backend` (`agy` or `openrouter`) |
| `HUMANIZE_POLISH_AGY_BIN` | Overrides `gemini_polish_agy_bin` (used by the offline tests) |
| `HUMANIZE_POLISH_BASE_URL` | Overrides `gemini_polish_base_url` (used by the offline tests) |
| `HUMANIZE_POLISH_BLOCK_RATIO`, `HUMANIZE_POLISH_DOC_RATIO` | Length-ratio bounds as `LOW:HIGH` |
| `HUMANIZE_POLISH_PYTHON` | Python 3 interpreter to use (default `python3`) |

## Configuration

Humanize uses a 4-layer config hierarchy (lowest to highest priority):
1. **Plugin defaults**: `config/default_config.json`
2. **User config**: `~/.config/humanize/config.json`
3. **Project config**: `.humanize/config.json`
4. **CLI flags**: Command-line arguments (where available)

Current built-in keys:

| Key | Default | Description |
|-----|---------|-------------|
| `codex_model` | `gpt-5.5` | Shared default model for Codex-backed review and analysis |
| `codex_effort` | `high` | Shared default reasoning effort (`max`, `xhigh`, `high`, `medium`, `low`) |
| `rlcr_verifier` | `codex` | Who checks each RLCR round to decide whether the work is done: `codex` or `claude` |
| `rlcr_reviewer` | `codex` | Who runs the RLCR code review phase: `codex` or `claude` |
| `claude_review_model` | `""` | Model for Claude when it is a reviewer (for example `opus`); empty means the Claude CLI default |
| `bitlesson_model` | `haiku` | Model used by the BitLesson selector agent |
| `provider_mode` | unset | Optional runtime mode hint such as `codex-only` |
| `agent_teams` | `false` | Project-level default for agent teams workflow |
| `alternative_plan_language` | `""` | Optional translated plan variant language; supported values include `Chinese`, `Korean`, `Japanese`, `Spanish`, `French`, `German`, `Portuguese`, `Russian`, `Arabic`, or ISO codes like `zh` |
| `gen_plan_mode` | `discussion` | Default plan-generation mode |
| `gemini_polish_enabled` | `true` | Whether automatic (`--auto`) readability polishing runs |
| `gemini_polish_backend` | `agy` | Where polish requests go: `agy` (Antigravity CLI on your Gemini subscription) or `openrouter` (billed per call) |
| `gemini_polish_agy_model` | `gemini-4-neon` | agy model used for polishing (see `agy models`) |
| `gemini_polish_agy_bin` | `""` | Path of the agy command; empty means `PATH`, then `~/.local/bin/agy` |
| `gemini_polish_fallback_to_openrouter` | `false` | Whether an agy failure falls back to OpenRouter (billed per call) |
| `gemini_polish_model` | `google/gemini-4-neon` | OpenRouter model used for polishing |
| `gemini_polish_reasoning_effort` | `medium` | Reasoning effort for polishing on either backend (`xhigh`, `high`, `medium`, `low`) |
| `gemini_polish_max_tokens` | `131072` | Completion budget for one OpenRouter polish request, reasoning included |
| `gemini_polish_timeout` | `900` | Overall deadline for one polish request, in seconds |
| `gemini_polish_max_bytes` | `262144` | Largest document that is sent for polishing |
| `gemini_polish_api_key_file` | `""` | Optional file that holds the OpenRouter API key |
| `gemini_polish_base_url` | `https://openrouter.ai/api/v1` | OpenRouter API base URL |

### Codex Model Configuration

All Codex-using features (RLCR loop, ask-codex) share the same model configuration:

| Key | Default | Description |
|-----|---------|-------------|
| `codex_model` | `gpt-5.5` | Model used for Codex operations (reviews, analysis, queries) |
| `codex_effort` | `high` | Reasoning effort (`max`, `xhigh`, `high`, `medium`, `low`) |

To override, add to `.humanize/config.json`:

```json
{
  "codex_model": "gpt-5.2",
  "codex_effort": "xhigh",
  "bitlesson_model": "sonnet"
}
```

On Codex installs, Humanize also seeds `${XDG_CONFIG_HOME:-~/.config}/humanize/config.json`
with a Codex/OpenAI `bitlesson_model` and `provider_mode: "codex-only"` when those keys
are unset, so BitLesson selection stays on the Codex/OpenAI path without probing Claude.

Codex model is resolved with this precedence:
1. CLI `--codex-model` flag (highest priority)
2. Feature-specific defaults
3. Config-backed defaults from the 4-layer hierarchy above
4. Hardcoded fallback (`gpt-5.5:high`)

### Choosing the RLCR Reviewers

An RLCR loop has two review jobs, and you can assign each one to Codex or Claude:

- `rlcr_verifier` checks the summary at the end of each round and decides whether the work is done.
- `rlcr_reviewer` reviews the code once the work is done and reports problems as `[P0]` to `[P9]` findings.

Both default to `codex`. To use Claude for both, add this to `.humanize/config.json`:

```json
{
  "rlcr_verifier": "claude",
  "rlcr_reviewer": "claude"
}
```

The environment variables `HUMANIZE_RLCR_VERIFIER` and `HUMANIZE_RLCR_REVIEWER` override the config for one session.

When Claude reviews, it runs as `claude -p` in read-only mode. Only the Read, Grep, and Glob tools are loaded, so it can read and search files, but it cannot run shell commands, edit files, browse the web, use MCP servers, or trigger Humanize hooks. Permissions you granted Claude elsewhere, such as "allow Bash", do not change this. For the code review, the loop writes the commit list and the full diff to a file for Claude to read. Because it cannot write files, it prints its review and the loop saves it. Instead of editing the goal tracker itself, it lists corrections for the coding agent to apply. Codex works as before: `codex exec` checks each round, and `codex review --base` reviews the code.

Pick a reviewer from a different model family than the coding agent when you can. Using Claude Code to code and Codex to review (or Gemini in agy to code and Codex or Claude to review) gives a more independent review.

**Migration note**: If your `.humanize/config.json` contains the legacy keys
`loop_reviewer_model` or `loop_reviewer_effort`, they are silently ignored.
Use `codex_model` and `codex_effort` instead.


## Monitoring

Set up the monitoring helper for real-time progress tracking:

```bash
# Add to your .bashrc or .zshrc
source ~/.claude/plugins/cache/PolyArch/humanize/<LATEST.VERSION>/scripts/humanize.sh

# Terminal monitors (one project per terminal):
humanize monitor rlcr        # latest RLCR loop log
humanize monitor skill       # all skill invocations (codex + gemini)
humanize monitor codex       # ask-codex skill invocations only
humanize monitor gemini      # ask-gemini skill invocations only

# Browser dashboard (multiple loops at once, foreground default):
humanize monitor web --project /path/to/project
```

Progress data is stored in `.humanize/rlcr/<timestamp>/` for each loop session.

### Browser dashboard (`humanize monitor web`)

The web dashboard layers on top of the same `.humanize/rlcr/<session>/`
metadata and `~/.cache/humanize/<sanitized-project>/<session>/round-*-codex-{run,review}.log`
cache logs that the terminal monitors read. There is no parallel
capture pipeline; the dashboard is a reader, not a writer.

Lifecycle (per DEC-1, DEC-3):

- Foreground default (`humanize monitor web --project <path>`). Press
  Ctrl+C to stop. The server is CLI-fixed to one project at startup;
  to monitor several projects simultaneously, run multiple instances
  (one per project) with different `--port` values.
- `--daemon` runs the same server inside a per-project tmux session
  (`humanize-viz-<8-hex>`); use `viz-stop.sh --project <path>` or
  the project's own tmux kill command to stop it.

Per-session inline live log panes appear on the home page for every
active session, driven by Server-Sent Events from
`/api/sessions/<session_id>/logs/<basename>`. Multiple loops stream
in parallel without leaving the home page.

### Remote browser access

The dashboard binds to `127.0.0.1` by default. To expose it over the
network, supply `--host` and an authentication token. The token is
required for any non-loopback host; the server refuses to start
otherwise.

Token-aware endpoints honor `Authorization: Bearer <tok>` for normal
fetch requests and `?token=<tok>` query parameters for the SSE stream
(per DEC-4: browsers cannot set arbitrary headers on EventSource).
WebSocket transport is rejected entirely in remote mode.

#### Pattern 1 (recommended): SSH tunnel

The safest remote pattern keeps the server bound to localhost and
forwards the port over SSH:

```bash
# On the server machine:
humanize monitor web --project /path/to/project --port 18000

# On your laptop:
ssh -N -L 18000:localhost:18000 user@server.example.com
# Then open http://localhost:18000 in the local browser.
```

No token is required because the server still binds to loopback. The
SSH tunnel provides authentication and encryption.

#### Pattern 2: Direct LAN bind

For trusted-network deployments where SSH tunneling is impractical:

```bash
# Generate a strong random token (one-time):
TOKEN="$(openssl rand -hex 32)"

# Start the dashboard:
humanize monitor web \
    --project /path/to/project \
    --host 0.0.0.0 \
    --port 18000 \
    --auth-token "$TOKEN"

# Or supply the token via env var instead of CLI:
HUMANIZE_VIZ_TOKEN="$TOKEN" humanize monitor web \
    --project /path/to/project --host 0.0.0.0 --port 18000
```

Open the dashboard with `http://server:18000/?token=<TOKEN>` once;
the browser caches the token in `sessionStorage` and propagates it
on subsequent fetches and SSE reconnects.

## Cancellation

- **RLCR loop**: `/humanize:cancel-rlcr-loop`

## Environment Variables

### HUMANIZE_CODEX_BYPASS_SANDBOX

**WARNING: This is a dangerous option that disables security protections. Use only if you understand the implications.**

- **Purpose**: Controls whether Codex runs with sandbox protection
- **Default**: Not set (uses `--sandbox workspace-write`: Codex may write only inside the project)
- **Values**:
  - `true` or `1`: Bypasses Codex sandbox and approvals (uses `--dangerously-bypass-approvals-and-sandbox`)
  - Any other value or unset: Uses safe mode with sandbox

**When to use this**:
- Linux servers without landlock kernel support (where Codex sandbox fails)
- Automated CI/CD pipelines in trusted environments
- Development environments where you have full control

**When NOT to use this**:
- Public or shared development servers
- When reviewing untrusted code or pull requests
- Production systems
- Any environment where unauthorized system access could cause damage

**Security implications**:
- Codex will have unrestricted access to your filesystem
- Codex can execute arbitrary commands without approval prompts
- Review all code changes carefully when using this mode

**Usage example**:
```bash
# Export before starting Claude Code
export HUMANIZE_CODEX_BYPASS_SANDBOX=true

# Or set for a single session
HUMANIZE_CODEX_BYPASS_SANDBOX=true claude --plugin-dir /path/to/humanize
```
