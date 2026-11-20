# Humanize Usage Guide

Detailed usage documentation for the Humanize plugin. For installation, see [Install for Claude Code](install-for-claude.md).

## How It Works

Humanize creates an iterative feedback loop with two phases:

1. **Implementation Phase**: Claude works on your plan, Codex reviews summaries until COMPLETE
2. **Review Phase**: `codex review --base <branch>` checks code quality with `[P0-9]` severity markers

The loop continues until all acceptance criteria are met or no issues remain.

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
| `/start-rlcr-loop <plan.md>` | Start iterative development with Codex review |
| `/cancel-rlcr-loop` | Cancel active loop |
| `/gen-plan --input <draft.md> --output <plan.md>` | Generate structured plan from draft |
| `/refine-plan --input <annotated-plan.md>` | Refine an annotated plan and generate a QA ledger |
| `/ask-codex [question]` | One-shot consultation with Codex |
| `/polish-gemini --input <file>` | Readability-only polish of human-facing text with Gemini |

## Command Reference

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
  -h, --help             Show help message
```

The gen-plan command transforms rough draft documents into structured implementation plans.

Workflow:
1. Validates input/output paths
2. Checks if draft is relevant to the repository
3. Analyzes draft for clarity, consistency, completeness, and functionality
4. Engages user to resolve any issues found
5. Generates a structured plan.md with acceptance criteria
6. Optionally starts `/humanize:start-rlcr-loop` if `--auto-start-rlcr-if-converged` conditions are met

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
  --model <id>           OpenRouter model ID (default: google/gemini-4-hydrogen)
  --effort <level>       Reasoning effort (default: xhigh)
  --timeout <seconds>    Overall deadline for the request (default: 900)
  --max-tokens <n>       Completion budget, reasoning included (default: 131072)
  --max-bytes <n>        Largest input to send (default: 262144)
  --strict               Exit 3 instead of 0 when the original had to be delivered
```

Claude and Codex often write documents full of jargon. `polish-gemini` sends text that people will read to a Gemini model on OpenRouter for a readability-only pass, then delivers either the polished text or the exact original bytes.

Gemini acts only as a copy editor:

- The request carries no tools, so Gemini cannot read files, run commands, or search the web. Web-search model IDs (ending in `:online`) are refused.
- The document is sent as data between per-run marker lines. Instructions inside the document are not followed.
- Gemini may reword sentences, replace jargon with plainer words, add brief glosses for terms already present, split long sentences, and fix grammar.
- Gemini must not translate, add or remove facts, change negations or obligation words, or change code, identifiers, paths, URLs, numbers, or document structure.

#### When it runs

Polishing is on by default (`gemini_polish_enabled: true`) in three scenarios, where Claude runs it with `--auto`:

1. **Writing documentation** for people: README files, files under `docs/`, guides, reports, release notes.
2. **Making web pages**: `.html` files are handled by the HTML adapter. Component files (JSX, TSX, Vue, Svelte) use the skill's manual segments procedure.
3. **Writing the RLCR finalize summary**: the finalize prompt tells Claude to polish `finalize-summary.md`. Round summaries are never polished.

Everything else (chat replies, commit messages, PR descriptions, code comments, idea drafts, plans) is polished only when you ask. Plan files, round summaries, the goal tracker, review results, QA ledgers, code, and config are never polished automatically because tools parse them.

`--auto` marks an automatic call site. With `--auto`, the script skips when `gemini_polish_enabled` is `false` (`reason=disabled`) or when the config cannot be loaded (`reason=config_error`). Without `--auto`, an explicit request always runs.

#### API key setup

Polishing needs an [OpenRouter](https://openrouter.ai/) API key. The script looks for it in this order:

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

The key is read inside the Python helper. It is never placed on a command line, and it never appears in run records, cache files, stdout, or stderr. A key file that group or others can read produces a warning. Without a key, the original is delivered with `reason=no_api_key`.

#### Outcomes and exit codes

Every run ends with exactly one line on stderr:

```
polish-gemini: outcome=<polished|unchanged|skipped|rejected|failed> reason=<code> delivered=<yes|no>
```

| Outcome | Meaning | Example reasons |
|---------|---------|-----------------|
| `polished` | The guard accepted a rewrite and it was delivered | `ok` |
| `unchanged` | Gemini returned the same text | `identical` |
| `skipped` | Nothing was sent; the original was delivered | `no_api_key`, `disabled`, `config_error`, `empty_input`, `too_large`, `sentinel_collision`, `secret_in_input`, `unsupported_encoding`, `unsupported_html`, `invalid_segments`, `nothing_to_polish`, `missing_dependency` |
| `rejected` | The reply failed the guard; the original was delivered | `envelope`, `structure`, `region_changed`, `protected_token`, `inline_markup`, `script_changed`, `length_ratio`, `segment_mismatch`, `markup_in_text`, `html_mismatch`, `tool_call` |
| `failed` | The request failed; the original was delivered | `network`, `auth`, `insufficient_credits`, `rate_limited`, `provider_error`, `timeout`, `truncated`, `empty_response`, `bad_json`, `api_error`, `internal_error`, `delivery_error`, `interrupted`, `usage_error` |

| Exit code | Meaning |
|-----------|---------|
| `0` | Content delivered: the polished text or the exact original bytes |
| `3` | `--strict` only: the original was delivered because polishing was skipped, rejected, or failed |
| `1` | Usage error; nothing delivered |
| `4` | Delivery failed (for example an unwritable `--output`); the destination is unchanged |
| `130` / `143` | Interrupted by SIGINT / SIGTERM; nothing is delivered if the signal arrives before delivery starts |

Delivery to stdout is a single write after every check has finished. Delivery to `--output` goes through a temporary file in the same directory and a rename, so the file is either the old content or the new content.

A signal that arrives while delivery is under way does not cut it short: the write or rename finishes, the outcome line still describes what was delivered (for example `outcome=polished reason=ok delivered=yes`), and the run exits 130 or 143. This also holds for a Ctrl-C sent to the whole process group while the fallback copy runs without Python. `reason=interrupted` with `delivered=no` means the signal came before delivery and nothing was written. A signal that was ignored when the run started (for example SIGINT in a background job started by a non-interactive shell) stays ignored. The script stays the runner's process while the Python helper starts and works: a SIGINT or SIGTERM sent to it, or to its whole process group, before delivery begins ends the run with `reason=interrupted`, `delivered=no`, and exit 130 or 143, also while the helper is still starting. The helper reports that it is ready by writing one byte to a private named pipe (created in `TMPDIR` or `/tmp` and removed again before the helper starts; the script uses it only after checking that what it opened is a named pipe it owns, so a name replaced in a shared directory cannot redirect the byte into another file) and reads no input until the script releases it with SIGUSR1; a signal that came before that is passed on to the helper, which then ends the run. If the script itself is killed (for example with SIGKILL), the helper notices before it delivers and ends as interrupted with nothing delivered. When no such pipe can be made, the helper is not started: the script keeps handling SIGINT and SIGTERM and delivers the original itself (`outcome=skipped reason=missing_dependency delivered=yes`). Diagnostic lines are always single lines starting with `polish-gemini:`; line breaks and control characters in error messages, file names, and config values are replaced with spaces, and no diagnostic can start with `outcome=`. A malformed reply, or any unexpected error inside the script, still delivers the original (`reason=bad_json`, `api_error`, or `internal_error`). When `python3` 3.7 or newer or the helper files cannot be found or started (also when the interpreter disappears between the version check and the start), the script delivers the original itself (`outcome=skipped reason=missing_dependency delivered=yes`).

#### Request details

- One `POST <gemini_polish_base_url>/chat/completions` per run, plus at most one retry.
- The body holds the model, a system message with the polish-only contract (`prompt-template/gemini/polish-contract.md`), the document in the user message, `reasoning: {"effort": ..., "exclude": true}`, and `max_tokens`. It never holds `tools`, `tool_choice`, or `plugins`.
- If the API answers HTTP 400 and explicitly rejects reasoning effort `xhigh`, the script retries once with `high` and records `effort_used: high`.
- HTTP 429 is retried once, after `Retry-After`, if that still fits inside the deadline.
- The reply is accepted only for HTTP 200, valid JSON with valid Unicode, no `error` field (any value except `null` counts as an error), `finish_reason` `stop`, no tool calls, and non-empty text inside exactly one output block.
- `effort_used` in the run record is the effort of the last request sent, even when that request failed.

#### The guard and its limits

A local, deterministic guard checks every reply before delivery. For Markdown and text it requires:

- the same blocks one-to-one and in order (headings and levels, paragraphs, list items, table rows and columns; as in GFM, a table needs a header row and a delimiter row with the same number of cells (a row splits at every pipe that is not escaped, also inside backticks), and the delimiter row must sit in the same quote and list item as the paragraph above it, which keeps a table whose header row is a lazy line inside that list item; as in cmark-gfm, the header row needs no pipe (`Name` above `:---` is a one-column table), it may be a paragraph line indented four columns or one that looks like a list item that cannot interrupt the paragraph (`2. Header.`), a lazy header row that starts with whitespace and a pipe has an empty first cell, and after one delimiter row whose header row does not match, no later line of that paragraph starts a table. Where markdown-it reads a table differently (a header row without a pipe, a lazy or indented header row, or a table that cmark-gfm does not start), a change between the two readings is rejected, and a paragraph that only markdown-it reads as a table is kept byte for byte; the markdown-it preset the guard checks has no tables and reads the rows as paragraph text, with the paragraph right before them and the lines after them that do not end that paragraph (lazy lines after a quoted table, a list item numbered other than 1, another table), so a row where a code span, raw HTML, a link, math or emphasis it reads there crosses a cell or a row, or that follows a cell leaving a `[` open, is kept byte for byte (so is a delimiter row such a construct covers; brackets and delimiters in code spans, raw HTML, autolinks, link destinations and titles or after a backslash do not count, delimiters in a link's text pair only inside it where that renderer reads a link (markdown-it refuses some destinations, link text that holds a link is no link, and bracket pairs that may be references are read each way in every combination of the labels the document may define), and TeX math is text to the renderers, so code, raw HTML and links that open inside it count too), and so are the lines from the paragraph or the lines after the table where such a construct reaches them; in a list item, markdown-it's paragraph ends at the next list item);
- blank lines as Markdown reads them: only spaces and tabs (a carriage return before the line feed belongs to the line ending). A line whose text past its quote markers, list markers and indentation starts or ends with other whitespace (a no-break space, a form feed, an ideographic space), which is text to the renderers, or that holds a carriage return not followed by a line feed, is kept byte for byte with the lines around it, from the line after the blank line before it to the first line after a blank line that starts at the left margin with no quote or list marker, or to the end of the document when those lines hold a fence or an HTML block that may run on over blank lines. List items are numbered with ASCII digits only (a fullwidth digit such as U+FF12 before the period is text);
- the same list nesting (measured from each item's content column), list markers, task boxes, a blank line before each list item, blockquote depth, the same blockquotes (each quote that opens counts, including an empty one; a blank line ends a quote, while a line with only `>` stays inside it, so two quotes cannot be merged or one split), and whether each quote marker reaches the content of the list items around it (so a quote cannot move into or out of a list item, also inside another quote, on a continuation line, in indented code, or in a table row; a quote marker four or more columns into a line still continues a quote when it sits inside the list items around that quote; when a list item closes, the quotes and lists inside it close too; tabs count to the next multiple of four columns, as in CommonMark), lazy continuation lines read past the list items they reach (so a nested list or heading after one is still a block), list items that start empty or with a number other than 1 do not interrupt a paragraph, a list item that starts empty and is followed by a line of only spaces or tabs is checked both as cmark-gfm reads it (the item stays open while every blank line after it holds whitespace up to its content column; an item that holds only reference definitions is empty again after the blank line that ends them; a paragraph of only definitions in a list item counts toward the list's looseness unless a blank line closes it, so adding or removing that blank line is a structure change) and as CommonMark describes it (the item ends), and the same enclosing list items for each block inside a list, also across blockquotes (a list item that contains a quote still contains the blocks after the quote). Whatever follows a list marker on the same line (a heading, code, an HTML block, a quote, a definition, a table, or another item) is classified like any other block;
- byte-identical front matter, fenced and indented code (also when it starts on a list-marker line; a closing fence is indented at most three columns past its quote or list item, and a fence that is never closed ends where its quote or list item ends, with its trailing blank lines), HTML blocks (a `script`, `pre`, `style`, or `textarea` block or a comment runs to its closing tag, even across blank lines; every HTML block ends where its quote or list item ends; the tags that start a block are those of cmark-gfm, and a lone tag such as `<span>` or `</script>` starts one only where it does not interrupt a paragraph, and only when it is complete on its line: a tag whose quoted attribute value is still open there is raw inline HTML in a paragraph, where cmark-gfm keeps the whitespace at the start of a lazy line inside such a span, so which line of which code span, raw HTML element or inline link title is lazy is structure (read from left to right as CommonMark reads them, whichever starts first; rewrapping the prose around them keeps it), and in a list item, where such a span covers several lines, the item's content column is structure too (it decides how much indentation the renderers remove from those lines)), math blocks (the renderers read math as Markdown: where a fence or an HTML block that starts in a math block runs on past it, the lines from the math block on are kept byte for byte, and where the line right after one (or after math blocks that follow each other directly) continues the paragraph its last line ends while a code span, raw HTML, emphasis or a link text runs on into it, or looks like a setext underline, the lines from there are kept byte for byte up to the first line after a blank line that starts at the left margin with no quote or list marker), footnote definitions with their continuation lines, read as cmark-gfm reads them (lines indented four columns; an empty line, while a line of only spaces or a quote line with only its marker ends the definition unless it is indented four columns too; and, while the definition's content ends in an open paragraph, also inside a list, quote or nested definition within it, lines that continue that paragraph lazily, also with fewer quote markers, without starting a block of their own or leaving an enclosing list item; a fence or raw HTML block still open where the definition ends keeps its blank lines; a lazy line that would read differently as part of the content (one that looks like a setext underline, a table delimiter row, a quote marker or an indented block start, or a row with leading whitespace and a pipe) counts there as plain text with the same number of table cells; where the guard cannot tell whether a lazy line continues the definition (its content may hold a reference definition, or it is too long or too deeply nested to read), the definition and everything after it are kept byte for byte; markdown-it has no footnotes and reads a definition as a paragraph or a reference definition, so where the line right after one starts a block other than a paragraph to cmark-gfm but does not interrupt a paragraph to markdown-it (a lone tag such as `<span>`, a list item numbered other than 1 or an empty one, or indented code past a container the definition leaves), markdown-it may continue its paragraph there and open a fence or an HTML block that runs on past cmark-gfm's block, and where cmark-gfm starts a paragraph on that line while the definition holds a backtick, a `<`, an emphasis marker or a `[` it leaves open, or the line looks like a setext underline, markdown-it's code span, raw HTML, emphasis or link may run on into it, or markdown-it ends its paragraph there as a heading and may read the lines after it as code, so the lines from there are kept byte for byte up to the first line after a blank line that starts at the left margin with no quote or list marker, or to the end of the document when they hold a fence or an HTML block that may run on (the same holds from the paragraph right before a definition that ends it for cmark-gfm, when a code span, raw HTML, emphasis or a link text opened there runs on into the definition, which markdown-it reads as more of that paragraph; not after a blank line inside the definition, nor when the definition starts anew and markdown-it reads it as a reference definition followed by code: no paragraph is open there)), reference definitions (read from the start of a paragraph, as in CommonMark: to cmark-gfm a line after a definition continues that paragraph, so an indented line there is text and not code (a lazy line keeps its leading whitespace after the containers it reaches, none when it reaches an outer list item's content column exactly, so an indented lazy line starts no definition, and that whitespace is part of a title cmark-gfm keeps), a definition-like line inside a paragraph is text, and an underline below a line that only starts like a definition makes a heading; the label may contain escaped brackets or continue on the next line, also as a lazy continuation line in a quote at any depth, and holds at most 1000 bytes of UTF-8 and not only spaces, tabs or line ends (other whitespace, such as a vertical tab, a form feed or a no-break space, is text there and is not collapsed when labels are matched, as in cmark-gfm; a reference link's label follows the same rules; markdown-it trims and collapses every kind of whitespace, folds case its own way and has no length limit, so a reference the two resolve differently is checked both as a link and as text), the destination is read as cmark-gfm reads it (at most 32 parentheses open, also ones still open where it ends; a closing parenthesis with none open or a space ends it, also after a backslash) and may be on the next line, and a quoted title may continue over several lines (cmark-gfm takes the longest title it can match: one that runs past an escaped quote to a later quote followed by more text on its line is not a title, and the definition then has to end after its destination; cmark-gfm still keeps such a title, also one on the next line followed by more text, on the definition while it renders those lines as text, so changing them is rejected); a definition the guard cannot read is kept byte for byte up to the next definition or the end of its paragraph, unless it can only be text, such as a destination followed on its line by something other than a title; front matter is Markdown to a renderer that does not read it as metadata, so a definition in it possibly counts; a label in a protected region, front matter or footnote that continues on a quoted line counts with and without the quote markers, and so does one anywhere in the document where its labels decide how a paragraph's text reads; the labels either renderer may define, and which definition of a label comes first, must stay the same, so a change that moves a definition out of what markdown-it reads as one (for example into an indented code block) is rejected even when cmark-gfm reads it the same way; a definition in the lines above a table's header row is text to cmark-gfm and a definition to markdown-it, so adding or removing a blank line between them is a structure change; an underline right below definitions is text to cmark-gfm but, to markdown-it, an empty list item (`-`), text (`--`), a thematic break (`---` or longer) or a heading below a definition it does not take, so that reading is part of the structure; a definition-like line with a label over 1000 bytes, also over several lines, is text to cmark-gfm but a definition to markdown-it, so its paragraph is kept byte for byte; a definition whose destination leaves a parenthesis open or, once escapes and character references are decoded, is a `javascript:`, `vbscript:`, `file:` or `data:` link (data images excepted), or whose title ends in an escaped quote, or an empty title followed by more text, is cmark-gfm's only, and markdown-it reads the rest of that paragraph as text; markdown-it starts a new block after each definition it takes, where cmark-gfm continues the paragraph, so lines it reads there as indented code (with the blank lines inside that code after the paragraph, before a further indented line), a thematic break, an empty list item, an HTML block, or a further definition are kept byte for byte (a paragraph after them stays prose), a list markdown-it opens there (a list item numbered other than 1, which cmark-gfm reads as text of the paragraph), and the lines of the paragraph from the first one markdown-it reads outside the definition's quote or list item, are kept byte for byte, quote markers and indentation included, up to the first line after a blank line that starts at the left margin with no quote or list marker (where both renderers have closed every container), or to the end of the document when those lines hold a fence or an HTML block that may run on over blank lines; the two renderers read such lines too differently to compare them as prose; the header row of a table right after a definition is where markdown-it starts a block of its own, so the row and the lines after it are kept the same way (from the definition when its title runs onto the row), or only the lines after it when markdown-it reads the row as paragraph text (prose to both; the delimiter and body rows are text of that paragraph there); to decide which definitions count and what else is structure there, a lazy line after a definition is read outside its quote or list item, and the lines after it are read anew outside them (an underline there counts from the content column of the list item still open at that depth, so one short of it is lazy text, and an underline that follows the paragraph directly is part of its reading, since markdown-it makes the paragraph a heading there; where the guard cannot tell how markdown-it reads a line there, the lines after the paragraph that may continue it (up to a blank line or a line that interrupts it, read from the content column of the list item markdown-it still reads there, as is every paragraph markdown-it continues lazily; a line short of that column that starts a block, such as a heading, interrupts it at any indentation, and whether the line that ends such a paragraph, or the first line after the blank lines that end it, reaches that column, or is indented code there, is structure) are compared with it as one prose unit (also together with the paragraph markdown-it reads right before them, which it may continue into them), the blocks markdown-it reads after it in that list item are classified from that column (indented code, a fence or an HTML block there is kept byte for byte), and where markdown-it continues such a paragraph over later blocks, a setext underline (counted from that column) ends it, and the underline and what markdown-it reads after it before a paragraph starts (indented code, definitions, whose labels then possibly count, or an HTML block, to a blank line) are kept byte for byte, and which of the list items around it the line after the underline reaches is structure; a definition cmark-gfm may read at a setext underline below a lazy line counts as possible; where a quote marker opens a new quote, also one shallower than the paragraph's, and a following list item that cannot interrupt a paragraph and has as many quote markers continues that paragraph, so its definitions are text to markdown-it, and what cmark-gfm reads inside that list item is markdown-it's top level; the same holds after a setext underline that is lazy text to markdown-it), a list item or a thematic break ends the lines a definition may continue on, a destination that ends in a backslash ends the definition with its line, and a setext underline ends its paragraph there as a heading (an underline indented four columns from its line start, measured past the quote markers of markdown-it's paragraph, so a quote marker after the indentation is text, is lazy text to a paragraph markdown-it reads outside the list item, and so is one short of the content column of an outer list item markdown-it still reads that paragraph in); an HTML block that markdown-it opens inside such a paragraph also takes the blocks after it up to the next blank line or the end of its quote or list item, which are kept byte for byte, and a paragraph it keeps open past a cmark-gfm setext heading continues into the next one, whose definitions are then text to it, and lazily over the blocks after it, whose definitions then only possibly count; when markdown-it reads a line of a paragraph outside its list item or quote (after a definition, a line that does not reach the item's content column or lacks the quote marker), the blocks it starts in that paragraph's lines, the ones it reads outside the containers, how far it closes them and what follows the paragraph (a blank line, or the quote depth of the next line) are part of the structure, a range there it may read in any way keeps the quote depth of each line, and each paragraph it reads there is also compared as a prose unit of its own; it reads the rest of that container (the outermost list item whose content column that line does not reach) outside it too (with the lazy lines that continue a paragraph there, and the further list items cmark-gfm opens where markdown-it continues that paragraph, whose lines markdown-it measures from the column it reads that paragraph at), so definitions there only possibly count, and whether a blank line follows that container is part of the structure (adding one splits what markdown-it reads as one quote or paragraph), and from the first line it may read as a block of another kind (indented four columns past its quote markers, a fence or an HTML block) the rest is kept byte for byte, also past the container while a block markdown-it reads there runs on (a paragraph to a blank line or a line that interrupts it, an HTML block to a blank line, a fence or raw HTML element to its end, but not past a fence or raw HTML that closed, unless it was text inside an HTML block; a fence in such text that is still open after the HTML block's blank line may open again at its closing line); an HTML block markdown-it opens in a paragraph after it closed the paragraph's containers runs to a blank line (raw HTML to its end marker) whatever the list items of the lines after it, and ends with the quotes its own line opens or keeps; a list item cmark-gfm opens inside an HTML block markdown-it reads (one it opened in a paragraph or in lines kept byte for byte) stays open after it, where markdown-it reads the block's container; where cmark-gfm starts an HTML block on a lazy line (the container the line reaches is not a paragraph) and markdown-it continues its paragraph over it, what markdown-it reads from the first fence or raw HTML element in that block that interrupts its paragraph is kept byte for byte, also past the block while it runs on; wherever markdown-it continues a paragraph past cmark-gfm's (over such a block, or over a list item only cmark-gfm opens), the paragraph markdown-it reads (also that of a list item only markdown-it opens) is also compared as one unit of its own (with the whitespace at the start of its later lines and at its line ends, and also when it starts in a definition or a block cmark-gfm starts earlier; how many of cmark-gfm's blocks it spans is structure), so its code spans, raw HTML, emphasis and links must stay the same as markdown-it groups them across the lines it continues it on, while a list item outside the paragraph's own list item ends it; markdown-it ends raw HTML in a list item at a blank line that does not reach the item's content column, so the lines after that one are kept byte for byte and a definition after cmark-gfm's block only possibly counts; where the guard cannot tell how markdown-it reads the rest of a paragraph, the blocks after it are kept byte for byte up to a blank line; markdown-it measures a lazy line's indentation from the list item's content column, so a lazy line indented four columns but less than a wide item's content column that looks like a block start (a quote marker too) ends the item and is indented code to it, and the rest of the paragraph is kept byte for byte; markdown-it also ends nested quotes at a lazy line indented four columns that looks like a block start (a heading, a fence, a thematic break, a list item or an HTML block) and reads it as indented code, and continues a quote at a quote marker after any indentation, where cmark-gfm reads text or indented code (whether such indented code directly follows a quoted line is part of the structure; after a quoted HTML block, markdown-it continues that block over the code up to a blank line, and after a quoted fence that cmark-gfm ended with the quote, that fence; quote markers the parse moves into a list item count at their depth there), so such lines and the rest of their paragraph are kept byte for byte and a definition there or after such code only possibly counts; wherever markdown-it's reading keeps lines byte for byte, a blank line inside a fence or raw HTML that markdown-it reads keeps its whitespace, also without a block of its own, while blank lines after indented code are not part of it), and text between `<!-- polish:off -->` and `<!-- polish:on -->`. The markers work on their own lines (also inside quotes and list items) and inline within a paragraph; a region that is never closed protects everything after the marker. The region is compared byte for byte, including spaces and blank lines, also with `--format segments`, and it ends at the `polish:on` marker, so text after the marker on the same line can be reworded when other text comes before the marker on that line (a line that starts with the marker is an HTML block line to the renderers, so the text after the marker is raw HTML there), unless a raw block (a fence, an HTML block, indented code, a definition) that starts in the region, or on the marker's line before the marker, still runs at the marker as the renderers read it: the marker is text inside that block, so the region then runs to the block's end. To the renderers the markers are plain HTML comments, so a document with markers must also pass every check as they read it (the markers renamed to ordinary comments); a region cannot hide how they read the lines around it. A marker inside inline code or a code block (fenced or indented) does not count, also inside a footnote definition, whose content is read as cmark-gfm reads it (also that of a definition inside another). markdown-it has no footnotes and reads that text as a paragraph (which may go on into a definition right after it and the lines it continues, so that code, raw HTML or image text opened in it may run on there), a reference definition or indented code; it may also read lines otherwise elsewhere (the lines the guard keeps byte for byte for that reason, and those where markdown-it continues a paragraph over blocks cmark-gfm reads there). Where the two may disagree about code, a `polish:off` marker counts when either renderer reads it outside code, and a `polish:on` marker only when both do (never in a footnote's label, a footnote line the guard cannot place, such as one past an expanded tab or a lazy line that is not plain text, a reference definition, also in a list item, front matter or math, which hold no comment to cmark-gfm while markdown-it may read them as text, nor inside TeX math, an inline link's destination or title, an image's text, an explicit reference label (`[text][label]`), or a raw HTML tag, where it is not a comment, or not one to both; TeX math is text to the renderers, so code, raw HTML, links and image text that open inside it count too, and labels the document may define are read resolving and not resolving in every combination, up to three of them, past which no `polish:on` marker in that paragraph counts); a marker right after a backslash (`\<!-- polish:on -->`) is text to both and never counts; in a table, cmark-gfm splits each row into cells before it reads code spans while markdown-it reads the rows, with the paragraph right before them in the same quote or list item, as one paragraph, and code counts both ways (where markdown-it reads on past the table, the lines it continues are kept as above, and a `polish:on` marker there does not count). So a region only grows there. Indented code, HTML blocks, footnote definitions, and protected regions inside a list item are compared together with the item's content column, so moving the item's marker cannot shift them. Indented code whose lines start with a quote marker right after a quoted line, where markdown-it continues the quote, is kept byte for byte when the text after such a marker, at any indentation, looks like the start of a fence or an HTML block, together with the quoted lines after it up to the first blank line or line without a quote marker and the lines indented four or more columns after those. Inside a list item, the blank lines after a footnote definition are kept as written (their whitespace can make the list loose);
- the same protected tokens in each block, in the same order: inline code, inline math (`$...$` by the Pandoc rule: no space after the opening `$` or before the closing one, and no digit right after the closing one, so `$2 x + y$` is math but `$5 or $10` is not; both `$...$` and `$$...$$` may span lines within a paragraph, and `$$...$$` may have spaces inside; `\(...\)`, and `\[...\]`; code and math that span lines keep their exact whitespace; the renderers read TeX math as text, so a code span, raw HTML or a link destination that opens inside it and closes past it is kept too), backslash escapes (so `\*literal\*` cannot become emphasis, and escapes cannot be added or dropped), URLs and link targets (with balanced parentheses nested to any depth; a link nested deeper than 32 levels freezes its block), reference labels and any other bracketed text, file paths (including rooted `/etc` and home-relative `~/file`; `and/or`, `yes/no`, `read/write` and similar prose pairs excepted), identifiers (names with an underscore anywhere, such as `snake_case`, `_private`, or `tool_`, `::` (with the names after it, also joined by dots, and its `()` when it is called, so `config::module.run()` is one word), `()` (with the calls and member names after it, so `obj.load().value`, `factory()()`, `$factory()().value` and `$factory::make()` are one word), `()`, a leading `--` or `$` (with the member names and scopes after it, so `$config.timeout` is one word), internal capitals such as `XMLParser`, or dots; abbreviations such as `e.g.` excepted), numbers with their units (`30 ms` cannot become `30 s`, nor `30 s` become `30 h`, also with more spaces, a no-break or thin space, or a line break between them), numbers and IDs such as `AC-1` or `task3`, and any run of 80 or more ASCII letters, digits and path characters (a hash, encoded data, a long identifier), which is one protected word together with a `$` or `${` before it and `()` or `}` (with the calls, member names and scopes after them) or a unit after it. The links and images of each paragraph, in order, are compared too (kind, whether they resolve, and the reference label), and a paragraph with a reference that may resolve and a square bracket with no partner (outside code, autolinks and raw HTML) is kept byte for byte;
- the same inline markup: HTML tags (attribute values byte for byte, also when they contain `$` or backticks; a `>` inside a quoted attribute value does not end the tag, also for an HTML block that starts with such a tag), HTML comments, processing instructions (`<?...?>`), declarations (`<!...>`), and CDATA sections byte for byte, also across lines, link and image syntax, also for an image inside link text (link text and alt text may be reworded; a bracket inside inline code, an autolink, or raw HTML does not end the link text; a reference that only one of cmark-gfm and markdown-it resolves is a link in that renderer's reading only, a shortcut reference may stand before a `(` or `[` that starts no link, a label that may be defined directly before an inline link stays a label where a renderer that defines it reads the link's brackets as a label (cmark-gfm only without brackets inside them, markdown-it always, as it finds the end of the link's text), so a space added between them makes it a shortcut reference, a full reference may have empty text, link text that holds a link (in cmark-gfm also inside an image) or a reference that resolves is no link to the renderers, so the destination and title after it are text there and a code span or raw HTML that opens in them is kept, the `![` of an image is kept (also when its alt text holds brackets), and the end of link text ends a delimiter run in the markdown-it reading; a paragraph is kept byte for byte where the link structure depends on the renderer in ways the guard does not model: link text that holds a reference that may or may not resolve, a reference that may resolve directly before an inline link tail, a reference image before a `(` that starts no inline image, and an inline destination that leaves a parenthesis open, which only cmark-gfm takes), emphasis (the same emphasis, strong and strikethrough spans with the same delimiter characters and the same nesting, paired by the CommonMark rules, with markers inside link text paired only with each other, also for a reference link or image whose label the document defines (only in the reading of a renderer that takes the link: markdown-it refuses destinations such as `file:`, and link text that holds a link is no link, in cmark-gfm also when that link is inside an image there, as markdown-it reads an image as one token), and the same literal `*` and `_`; the renderers read TeX math as text, so markers inside it pair with those outside, and the emphasis must stay the same with math read either way, and with the destination and title of a link that a renderer does not take read as text there; so `*word*` cannot become `* word *` or `_word_`, but emphasis may move with its words; underscores and tildes inside protected words (identifiers such as `_private` or `__init__`, paths, long runs) still count as emphasis markers, as the renderers do not know these words (an underscore between letters never pairs), and markers inside a bare URL are checked both as markers and as part of the URL, since GitHub links bare URLs and other renderers do not; strikethrough is read both as cmark-gfm reads it (`~` or `~~`, paired only with a run of the same length, longer runs are text, and tildes are skipped when deciding whether a star or underscore next to them can open or close emphasis) and as markdown-it reads it (`~~` only, also inside longer runs), and a change in either reading is rejected; with `--format segments`, where definitions are not available, and for a definition inside a protected region, bracketed text that holds emphasis markers is checked both as a link and as plain text, together for all texts that share a reference label), hard line breaks (two or more spaces, or an odd number of backslashes, at the end of a line; an even number of backslashes is escaped backslashes, and line ends inside code, math, or HTML are not breaks), and backtick strings outside code (adding or removing one can pair the others differently; and where the text holds such a string, its brackets outside code count as markup too, since markdown-it's search for the end of link text from an unclosed `[` can turn later code spans into text); code spans, raw HTML, autolinks and inline link destinations and titles are read from left to right in CommonMark's precedence, so a backtick inside a tag's attribute, a comment or a link title opens no code span; markdown-it's reading of them comes from an emulation of its inline parser (it finds the end of link text by looking ahead, refuses images as well as links to such destinations as `file:`, reads an image as one token, matches raw HTML with its own patterns, and once a look-ahead over link text has passed a backtick string with no closer, it reads later backtick strings of that length as text even where a closer follows, so a marker or a star inside such a code span counts in its reading); link destinations and titles stay byte for byte as cmark-gfm reads them, also inside nested link text; a paragraph that holds a link inside TeX math and emphasis markers is kept byte for byte; where the text reads in two ways (parentheses after a full or collapsed reference link whose label may or may not be defined are text or a link tail; a link or autolink to a `javascript:`, `vbscript:`, `file:` or `data:` destination is a link to cmark-gfm and text to markdown-it), the code spans, raw HTML, autolinks and link tails of each reading must stay the same, and so must the lazy lines inside them, the backtick strings no code span of that reading takes and, next to one, its brackets; the label of a full reference link that is defined is a label, not code or HTML (a backtick in it opens no code span);
- the same writing scripts in each block (for example Latin, Han, Kana, Hangul, Cyrillic, Arabic), with similar shares;
- length ratios between 0.5 and 2.0 per block and between 0.6 and 1.8 for the whole document. A block under 40 characters may grow to at most twice its length or 12 more characters, whichever is larger. Set `HUMANIZE_POLISH_BLOCK_RATIO` or `HUMANIZE_POLISH_DOC_RATIO` (format `LOW:HIGH`) to change them.

The guard cannot prove that meaning is unchanged. It does not detect translation between two languages that use the same script (for example English to Spanish), changed negations, caveats, or obligation words, numbers that keep their order but move to other nouns (`2 workers and 5 retries` becoming `2 retries and 5 workers`), or conversion between Simplified and Traditional Chinese. That is why Claude reviews every polished result against a checklist (same claims, same negations and caveats, same obligation strength, same language and variant, glosses only explain existing terms, nothing added, nothing dropped) before delivering it.

The guard errs toward rejecting. A rewrite of a name written as `__word__` (treated as an identifier), a less common slash pair such as `black/white` reworded as `black and white` (treated as a path), a paragraph or segment whose bracketed texts that hold emphasis markers may be links under more than four different labels (also when they sit inside an inline `polish:off` region of that paragraph), or a cut that shortens a wordy document below the 0.6 document ratio is rejected even when it is harmless; the original is then delivered.

Documents that contain the text `@@HUMANIZE-POLISH-` are not sent (`reason=sentinel_collision`), because that prefix is reserved for the marker lines. Documents with mixed line endings or bare carriage returns are not sent either (`reason=unsupported_encoding`), and the guard rejects them too; files that use CRLF throughout are fine (the guard reads them as line feeds).

#### HTML pages

For `.html` and `.htm` files, the script polishes only visible text: text nodes inside `<body>` and `<title>`, and the values of `alt`, `title`, `aria-label`, and `placeholder`, quoted or unquoted, on any element that is not excluded (including `<html>`, `<body>`, and elements in `<head>` such as `<link title=...>`). A new unquoted value has its spaces, quotes, `=`, and a trailing `/` written as character references, so it stays one value. It skips `script`, `style`, `template`, `code`, `pre`, `kbd`, `samp`, `noscript`, `textarea`, `svg`, `math`, `iframe`, `xmp`, `listing`, `plaintext`, `noembed`, `noframes`, elements with an inline `white-space: pre` style (and everything nested in all of these), whitespace-only text, and text that contains template syntax (`{{`, `}}`, `{%`, `${`, `<%`). Text and attribute values between `<!-- polish:off -->` and `<!-- polish:on -->` comments are skipped as well. Only HTML whitespace is collapsed in the text sent to the model; non-breaking spaces are kept. Character references such as `&amp;` must come back unchanged. The polished strings are put back at their original offsets with `&`, `<`, `>`, and the attribute quote escaped, and the page is parsed again to confirm that tags, attributes, comments, scripts, and styles are unchanged. A page is skipped (`reason=unsupported_html`) when the parser cannot map it to source offsets, when a non-void element is written self-closing outside SVG or MathML (browsers ignore the slash, so `<script/>` still opens a script), when attribute syntax could be read two ways, or when eligible text has a character reference without its semicolon (such as `&copy 2026`). CSS rules in stylesheets that preserve whitespace are not detected.

#### Run records

Each run that sends a request writes `.humanize/skill/<timestamp>-<pid>-<hex>/` with `input.md`, a copy of the source, the raw `candidate.txt`, the delivered `output.md`, and `metadata.md` (`tool: gemini`, `mode: polish`, `backend: openrouter`, model, `effort_used`, status, outcome, reason, token counts, and cost). The cache directory under `~/.cache/humanize/` holds `gemini-run.cmd` (the request without the key), `gemini-run.out` (the response without reasoning text), and `gemini-run.log`. Polish runs appear in `humanize monitor gemini` and `humanize monitor skill`.

#### Privacy and cost

- **Privacy**: polishing is on by default, so in the three default scenarios the document text is sent to OpenRouter and on to Google. Local copies of each run are kept under `.humanize/skill/` (gitignored). Set `gemini_polish_enabled` to `false` to stop automatic polishing.
- **Cost and time**: reasoning effort `xhigh` is slow and costs money, and the amount of reasoning varies from run to run. In tests on 2026-11-18, short documents (one to three paragraphs) took 12 seconds to 2 minutes and cost $0.02 to $0.14 (about 1,700 to 18,000 reasoning tokens), and a six-section document took about 2 minutes and cost about $0.15 (about 17,000 reasoning tokens). With `max_tokens` at 8,000, one request ran out of tokens before answering, which is why the default is 131,072. Lowering `gemini_polish_reasoning_effort` (for example to `high` or `medium`) reduces both time and cost.

#### Environment variables

| Variable | Purpose |
|----------|---------|
| `OPENROUTER_API_KEY` | API key (takes precedence over `gemini_polish_api_key_file`) |
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
| `codex_effort` | `high` | Shared default reasoning effort (`xhigh`, `high`, `medium`, `low`) |
| `bitlesson_model` | `haiku` | Model used by the BitLesson selector agent |
| `provider_mode` | unset | Optional runtime mode hint such as `codex-only` |
| `agent_teams` | `false` | Project-level default for agent teams workflow |
| `alternative_plan_language` | `""` | Optional translated plan variant language; supported values include `Chinese`, `Korean`, `Japanese`, `Spanish`, `French`, `German`, `Portuguese`, `Russian`, `Arabic`, or ISO codes like `zh` |
| `gen_plan_mode` | `discussion` | Default plan-generation mode |
| `gemini_polish_enabled` | `true` | Whether automatic (`--auto`) readability polishing runs |
| `gemini_polish_model` | `google/gemini-4-hydrogen` | OpenRouter model used for polishing |
| `gemini_polish_reasoning_effort` | `xhigh` | Reasoning effort for polishing (`xhigh`, `high`, `medium`, `low`) |
| `gemini_polish_max_tokens` | `131072` | Completion budget for one polish request, reasoning included |
| `gemini_polish_timeout` | `900` | Overall deadline for one polish request, in seconds |
| `gemini_polish_max_bytes` | `262144` | Largest document that is sent for polishing |
| `gemini_polish_api_key_file` | `""` | Optional file that holds the OpenRouter API key |
| `gemini_polish_base_url` | `https://openrouter.ai/api/v1` | OpenRouter API base URL |

### Codex Model Configuration

All Codex-using features (RLCR loop, ask-codex) share the same model configuration:

| Key | Default | Description |
|-----|---------|-------------|
| `codex_model` | `gpt-5.5` | Model used for Codex operations (reviews, analysis, queries) |
| `codex_effort` | `high` | Reasoning effort (`xhigh`, `high`, `medium`, `low`) |

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

**Migration note**: If your `.humanize/config.json` contains the legacy keys
`loop_reviewer_model` or `loop_reviewer_effort`, they are silently ignored.
Use `codex_model` and `codex_effort` instead.


## Monitoring

Set up the monitoring helper for real-time progress tracking:

```bash
# Add to your .bashrc or .zshrc
source ~/.claude/plugins/cache/PolyArch/humanize/<LATEST.VERSION>/scripts/humanize.sh

# Monitor RLCR loop progress
humanize monitor rlcr

```

Progress data is stored in `.humanize/rlcr/<timestamp>/` for each loop session.

## Cancellation

- **RLCR loop**: `/humanize:cancel-rlcr-loop`

## Environment Variables

### HUMANIZE_CODEX_BYPASS_SANDBOX

**WARNING: This is a dangerous option that disables security protections. Use only if you understand the implications.**

- **Purpose**: Controls whether Codex runs with sandbox protection
- **Default**: Not set (uses `--full-auto` with sandbox protection)
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
