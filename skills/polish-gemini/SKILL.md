---
name: polish-gemini
description: Polish prose written for people so it is easier to read, using Gemini as a copy editor only (through agy on the user's Gemini subscription by default, or OpenRouter). Use on your own before delivering documentation for people (README files, docs/, guides, reports, release notes) and the visible text of web pages; use for anything else only when the user explicitly asks.
argument-hint: "--input <file|-> [--output <file>] [--format markdown|text|segments|html] [--auto] [--backend agy|openrouter] [--effort xhigh|high|medium|low] [--strict]"
allowed-tools: "Bash(${CLAUDE_PLUGIN_ROOT}/scripts/polish-gemini.sh:*)"
---

# Polish With Gemini

Send a finished human-facing document to Gemini for a readability-only polish, then deliver the result.

Gemini acts only as a copy editor. It gets no tool it can use: the default agy backend runs the Antigravity CLI from an empty temporary folder with every tool refused, and the OpenRouter backend sends no tools, so Gemini cannot read files, run commands, or search the web. It may reword prose and add brief glosses for terms already present. It must not translate, add or remove facts, or change code, identifiers, paths, URLs, numbers, or document structure. A local guard rejects any reply that changes what it can check mechanically. When polishing is skipped, rejected, or fails, the script delivers the exact original bytes and says why.

## When to Polish

### Default scenarios: polish on your own, with `--auto`

- **Documentation written for people**: README files, files under `docs/`, guides, reports, release notes, and other Markdown or text documents meant for human readers.
- **Web pages**: `.html` files are handled automatically by the HTML adapter. Component and template files (JSX, TSX, Vue, Svelte and similar) use the manual segments procedure below.

The RLCR finalize summary and the Plan Understanding Quiz are the other two default scenarios. The finalize prompt and the `start-rlcr-loop` command run them for you; you do not need this skill for them.

With `--auto`, the script respects `gemini_polish_enabled` in the humanize config and skips when it is `false`.

### Explicit request only: polish only when the user asks, without `--auto`

- chat replies;
- commit messages and PR descriptions;
- code comments;
- idea drafts;
- plans.

### Never polish automatically

These files are parsed by tools or reviewed as written:

- plan files and translated plan variants;
- gen-plan and refine-plan outputs;
- RLCR round summaries, round contracts, and the goal tracker;
- review results and QA ledgers;
- code and config files.

If the user explicitly asks to polish one of these, first warn them that tools parse the file and polishing may break that, then proceed only if they confirm.

## Cost and Time

On the default agy backend (Gemini 4 Neon, reasoning effort `medium`), a run uses the user's Gemini subscription quota and costs nothing per call. In testing, short documents took about 15 seconds and a six-section document about 30 seconds. On the OpenRouter backend every run costs money. Either way, polish each finished deliverable once, not after every intermediate edit.

## Procedure

1. Write the finished draft to its file (or to a scratch file).
2. Run the script on that file. A run can take several minutes, so run it in the background (for example with the Bash tool's `run_in_background` option) and wait for it to finish.
3. Read the last stderr line: `polish-gemini: outcome=<...> reason=<...> delivered=<...>`.
4. If the outcome is `polished`, review the result with the checklist below.
5. Write or keep the final file, then re-read it.
6. If the outcome is not `polished` or `unchanged`, tell the user that the original was kept and give the reason.

## Running the Script

Pass every path as its own quoted argument. Do not pass free-form user text to the shell unquoted: paths and text may contain spaces or shell metacharacters such as `(`, `)`, `;`, `#`, `*`, or `[`.

Polish a document in place (default scenario):

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/polish-gemini.sh" --auto --input "docs/guide.md" --output "docs/guide.md"
```

Polish a draft the user asked about and print the result:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/polish-gemini.sh" --input "/path/to/draft.md"
```

If the user supplied flags (for example `--effort high`), keep each flag and each value as separate shell arguments and quote every path.

Never run this unsafe form:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/polish-gemini.sh" $ARGUMENTS
```

because the shell would re-split the arguments and can fail before the script starts.

## Outcomes

| Outcome | Meaning | What to do |
|---------|---------|------------|
| `polished` | The guard accepted a rewrite and it was delivered | Review it with the checklist |
| `unchanged` | Gemini returned the same text | Nothing to review |
| `skipped` | Nothing was sent (for example `agy_not_found`, `no_api_key`, `disabled`, `too_large`, `empty_input`) | Tell the user the original was kept and why |
| `rejected` | The reply failed the guard (for example `protected_token`, `structure`, `script_changed`) | Tell the user the original was kept and why |
| `failed` | The request failed (for example `timeout`, `auth` (agy not signed in), `quota_exhausted`, `rate_limited`, `truncated`) | Tell the user the original was kept and why |

`delivered=no` means nothing was written (usage error, delivery failure, or an interruption before delivery). With exit code 130 or 143 and `delivered=yes`, the run was interrupted after delivery had started; the outcome still says what was delivered, so a `polished` result still needs the review below.

## Review Checklist

The guard cannot prove that meaning is unchanged. Before you deliver a `polished` result, compare it with your original and confirm:

- same claims;
- same negations and caveats;
- same obligation strength (must, should, may, never, only);
- same language and variant (no translation, no Simplified/Traditional Chinese conversion, English words inside Chinese, Japanese, or Korean text kept as written);
- every gloss only explains a term already present;
- nothing added that is not a gloss;
- nothing dropped.

If any item fails, deliver the original or a corrected version, and say so.

## Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| 0 | Content delivered (the polished text or the exact original bytes) |
| 3 | `--strict` only: the original was delivered because polishing was skipped, rejected, or failed |
| 1 | Usage error; nothing delivered |
| 4 | Delivery failed (for example an unwritable output); the destination is unchanged |
| 130 / 143 | Interrupted; nothing delivered if the signal arrived before delivery, otherwise the outcome line says what was delivered |

## Manual Segments Procedure (Component and Template Files)

For JSX, TSX, Vue, Svelte, and other component or template files, polish only the visible strings:

1. Extract the eligible visible strings into a segments file, one per line, as `[[ID]] text`, with stable IDs that you map to their source locations. Apply the same rules as the HTML adapter: take text nodes and the `alt`, `title`, `aria-label`, and `placeholder` values; skip code, `script`, `style`, `pre`, `code`, `textarea`, `svg`, `math`, and any text containing template syntax (`{{`, `}}`, `{%`, `${`, `<%`).
2. Run the script with `--format segments` on that file.
3. Put each polished string back at its source location, applying the file type's escaping rules.
4. Diff the original and the new file and confirm that only those strings changed.

## Notes

- **Backend**: `gemini_polish_backend` is `agy` by default. agy must be installed and signed in with the account that has the Gemini subscription; without it the script delivers the original with `reason=agy_not_found` or `reason=auth`. It never falls back to OpenRouter unless `gemini_polish_fallback_to_openrouter` is `true`. For the OpenRouter backend, set `OPENROUTER_API_KEY`, or set `gemini_polish_api_key_file` to a file that holds the key (mode 600); without a key it delivers the original with `reason=no_api_key`.
- **Privacy**: the document is sent to Google, through agy or through OpenRouter. agy also keeps its own conversation history under `~/.gemini/antigravity-cli/`. Local copies of each run are kept under `.humanize/skill/<id>/`.
- **Reserved markers**: documents that contain the text `@@HUMANIZE-POLISH-` are not sent (`reason=sentinel_collision`).
- **Protected regions**: text between `<!-- polish:off -->` and `<!-- polish:on -->` must come back byte-identical.
