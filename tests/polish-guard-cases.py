#!/usr/bin/env python3
"""Unit cases for scripts/lib/polish_guard.py.

Run by tests/test-polish-gemini-guard.sh. Prints one "PASS: name" or
"FAIL: name: detail" line per case and exits 1 if any case failed.

Multilingual fixtures use \\u escapes so this file stays ASCII-only.
"""

import os
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import polish_guard as g  # noqa: E402

FAILED = []


def report(name, ok, detail=""):
    if ok:
        print("PASS: %s" % name)
    else:
        print("FAIL: %s: %s" % (name, detail))
        FAILED.append(name)


# Rewrites inside a list markdown-it opens right after a definition (a list
# item numbered other than 1, which cmark-gfm reads as paragraph text), or in
# the lines of a paragraph that markdown-it reads outside the definition's
# quote or list item. The guard once compared these lines as prose through a
# line-by-line model of markdown-it's reading; the review rounds kept finding
# combinations that model missed, so these lines are now kept byte for byte up
# to a blank line followed by a line at the left margin (see docs/usage.md).
# The cases below were accepted before that change and must now be rejected.
KEPT_AFTER_DEFINITION = {
    'R3 prose after an empty list item below a definition reworded',
    'R3 the text of a list item after a definition reworded',
    'R3 prose after an HTML block in a quote reworded',
    'R3 prose after an indented lazy line that holds no definition reworded',
    'R3 a heading after inline HTML in list item text reworded',
    'R3 a heading in a list item after a definition reworded',
    'R3 a nested list item after a quoted definition markdown-it closed reworded',
    'R3 a list item after a quote markdown-it closed reworded',
    'R3 a quoted heading after a definition markdown-it closed reworded',
    'R3 an inline link next to a definition both renderers take after a closed item changed',
    'R3 a later paragraph in a list item markdown-it closed reworded',
    'R3 a heading in a list item markdown-it closed reworded',
    'R3 the next list item after one markdown-it closed reworded',
    'R3 a list item after a quote markdown-it closed, with an indented paragraph, reworded',
    'R3 prose after a closed quoted fence after a closed item reworded',
    'R3 a heading after an HTML block in a quote markdown-it reopened reworded',
    'R3 an indented paragraph in a list item both renderers open after definitions reworded',
    'R3 a heading after an HTML block that ends with its list item reworded',
    'R3 prose with an escaped backtick before a list item markdown-it continues reworded',
    'R3 prose with a bracket in a closed comment before a list item markdown-it continues reworded',
    'R3 prose with a bracket in a closed attribute before a list item markdown-it continues reworded',
    'R3 prose with a backtick in a closed comment before a list item markdown-it continues reworded',
    'R3 emphasis markdown-it reads across a list item reworded with its words',
    'R3 prose markdown-it reads outside the list item reworded',
    'R3 prose before the quote markdown-it reopens reworded',
    'R3 prose markdown-it reads outside the list item rewrapped',
    'R3 prose around a link markdown-it splits reworded',
    'R3 prose before a heading markdown-it reads across a list item reworded',
    'R3 prose in a nested list after a definition and a lazy underline reworded',
    'R3 prose in a list item only markdown-it opens reworded',
    'R3 the indentation of a prose line markdown-it continues changed',
    'R3 prose above an underline markdown-it reads as text reworded',
    'R3 a blank line added before a heading after a lazy paragraph',
    'R3 prose in list items only markdown-it opens reworded',
    'R3 prose around a code span over a lazy underline reworded',
    'R3 emphasis moved with its words over a numbered line markdown-it keeps in the item',
    'R3 prose before an underline after a definition reworded',
    'R3 prose of a heading markdown-it reads over a heading item reworded',
    'R3 prose after an unknown range reworded',
    'R3 prose after the underline of a lazy run reworded',
    'R3 prose under an underline in a surviving outer list item reworded',
    'R3 an indented continuation after prose under a lazy underline reworded',
    'R3 a paragraph in a list item only markdown-it opens rewrapped lazily',
    'R3 prose after a definition after the underline of a lazy run reworded',
    'R3 prose after a fence that leaves a list item only markdown-it opens, outside the outer item',
    'R3 a paragraph after a quoted paragraph in a list item only markdown-it opens reworded',
    'R3 a paragraph after a lazy underline reworded in its outer list item',
    'R3 prose after an HTML comment closed on its line in a list item only markdown-it opens',
    'R3 prose after a pre block closed on its line in a list item only markdown-it opens',
    'R3 prose after a script block closed on its line in a list item only markdown-it opens',
    'R3 prose in a quoted paragraph before a fence in a list item only markdown-it opens reworded',
    'R3 a quote marker indented one more column inside an outer list item, after a lazy line',
    'R3 a quote marker indented one more column inside an outer list item, before a definition',
    'R3 a quote marker indented one column on a fence line kept in a list item only markdown-it opens',
    'R3 a quote marker indented one column on an HTML line kept in a list item only markdown-it opens',
    'R3 whitespace added to a blank line after text markdown-it continues lazily over a fence-like line',
    'R3 whitespace added to a blank line after indented code markdown-it reads after a closed fence',
    'R3 prose rewrapped before a fence kept in a list item only markdown-it opens',
    'R3 definition-like prose in a quote rewrapped in a list item only markdown-it opens',
    'R3 a quote marker indented one more column inside an outer list item after a lazy run',
    'R3 a thematic break indented one more column after a lazy run in a nested list',
    'R3 prose after a lazy underline reworded in the surviving outer list item',
    'R3 prose rewrapped after a nested quote ends a fence in a list item only markdown-it opens',
    'R3 a list marker indented one column less after a lazy run in an outer list',
    'R3 prose reworded after a quoted definition with its title on the next lazy line',
    'R3 prose rewrapped after a quoted definition with a title over two lazy lines',
    'R3 prose rewrapped after a title-like paragraph in a deeper quote',
    'R3 prose reworded in a list item only markdown-it opens before an underline',
    'R3 prose reworded in a list item after an item that starts with a quote, in a list only markdown-it opens',
    'R3 prose reworded at the end of a long quoted paragraph that starts with a reference link',
    'R3 prose reworded in a quote markdown-it opens where a list item only it opens ends',
    'R3 prose reworded in a list item after an item that starts with a quote, after a paragraph',
    'R3 prose reworded in a long lazy paragraph after a complete quoted definition',
    'R3 prose reworded in a later list item after an item that starts with a definition',
    'R3 prose reworded in a quote before a quote markdown-it opens inside an outer list item',
}


def accepts(name, source, candidate):
    if name in KEPT_AFTER_DEFINITION:
        rejects(name + " (now kept byte for byte)", source, candidate)
        return
    try:
        g.check_document(source, candidate)
        report(name, True)
    except g.GuardReject as exc:
        report(name, False, "rejected with %s (%s)" % (exc.reason, exc.detail))


def rejects(name, source, candidate, reason=None):
    try:
        g.check_document(source, candidate)
        report(name, False, "candidate was accepted")
    except g.GuardReject as exc:
        if reason and exc.reason != reason:
            report(name, False, "expected %s, got %s (%s)" % (reason, exc.reason, exc.detail))
        else:
            report(name, True)


BASE = """---
title: Setup Guide
version: 2
---

# Setup Guide

The `polish-gemini.sh` runner calls OpenRouter with the `--auto` flag and sends 2 requests at most.
See [the usage docs](https://example.com/docs/usage) for details about config.json and AC-1.

## Steps

1. Install the plugin.
2. Run the setup command.

- First item mentions snake_case_name.
  - Nested item about the cache.
- [ ] Open task about logging.
- [x] Done task about records.

> A quoted note that explains why the deadline matters for long documents.
> > A nested quote about retries.

| Key | Default |
|-----|---------|
| `gemini_polish_timeout` | 900 seconds |

```bash
echo "keep me exactly"
```

<!-- polish:off -->
This text must never change, even if it is hard to read.
<!-- polish:on -->

<div class="note">Raw HTML block stays as it is.</div>

Use <strong>bold HTML</strong> and ![an image](img/chart.png) in this paragraph, with *emphasis* too.

$$
E = mc^2
$$

Footnote reference here[^1].

[^1]: The footnote text stays byte-identical.

[ref]: https://example.com/ref
"""

# ----------------------------------------------------------------------------
# Accepted rewrites
# ----------------------------------------------------------------------------

accepts("identical document", BASE, BASE)
accepts("prose rewording",
        BASE, BASE.replace("calls OpenRouter with", "sends a request to OpenRouter using"))
accepts("sentence split inside the same paragraph",
        BASE, BASE.replace("sends 2 requests at most.\nSee", "sends 2 requests at most. It never sends more.\nSee"))
accepts("brief parenthetical gloss of an existing term",
        BASE, BASE.replace("Nested item about the cache.", "Nested item about the cache (saved copies of results)."))
accepts("line rewrap inside a paragraph",
        BASE, BASE.replace("at most.\nSee [the usage docs]", "at most. See\n[the usage docs]"))
accepts("link text reworded, target kept",
        BASE, BASE.replace("[the usage docs](https://example.com/docs/usage)", "[the usage guide](https://example.com/docs/usage)"))
accepts("image alt text reworded",
        BASE, BASE.replace("![an image](img/chart.png)", "![a chart](img/chart.png)"))
accepts("table cell reworded",
        BASE, BASE.replace("| Key | Default |", "| Key | Default value |"))
rejects("table cell unit changed",
        BASE, BASE.replace("| 900 seconds |", "| 900 minutes |"), "protected_token")
accepts("heading reworded",
        BASE, BASE.replace("## Steps", "## How to Set It Up"))
accepts("abbreviation e.g. is not protected",
        "Pick a mode, e.g. the fast one, before you start the run.\n",
        "Pick a mode, for example the fast one, before you start the run.\n")
accepts("plain and/or is not a path",
        "Use the first and/or the second option when you run the setup step.\n",
        "Use the first option, the second option, or both when you run setup.\n")

ZH_SRC = u"\u8fd9\u4e2a\u5de5\u5177\u4f1a\u628a\u6587\u6863\u53d1\u9001\u7ed9\u6a21\u578b\uff0c\u7136\u540e\u68c0\u67e5\u7ed3\u679c\u662f\u5426\u4fdd\u7559\u4e86\u539f\u6765\u7684\u7ed3\u6784\u548c 3 \u4e2a\u6570\u5b57\u3002\n"
ZH_REWORD = u"\u8fd9\u4e2a\u5de5\u5177\u5148\u628a\u6587\u6863\u4ea4\u7ed9\u6a21\u578b\u6da6\u8272\uff0c\u518d\u786e\u8ba4\u7ed3\u679c\u662f\u5426\u4fdd\u7559\u4e86\u539f\u6709\u7ed3\u6784\u548c 3 \u4e2a\u6570\u5b57\u3002\n"
EN_SRC = "This tool sends the document to the model and then checks that the result keeps the structure and 3 numbers.\n"
accepts("Chinese rewording stays Chinese", ZH_SRC, ZH_REWORD)

# ----------------------------------------------------------------------------
# Rejected rewrites: code and protected tokens
# ----------------------------------------------------------------------------

rejects("changed fenced code", BASE, BASE.replace('echo "keep me exactly"', 'echo "changed"'), "region_changed")
rejects("protected identifier moved to another paragraph",
        BASE, BASE.replace("calls OpenRouter with the `--auto` flag", "calls OpenRouter with the flag")
        .replace("Footnote reference here", "Footnote reference `--auto` here"), "protected_token")
rejects("two numbers swapped within a paragraph",
        "Run 2 workers and 5 retries before the final step of the setup.\n",
        "Run 5 workers and 2 retries before the final step of the setup.\n", "protected_token")
rejects("changed URL", BASE, BASE.replace("https://example.com/docs/usage", "https://example.com/docs/other"), "inline_markup")
rejects("dropped link occurrence",
        BASE, BASE.replace("See [the usage docs](https://example.com/docs/usage) for", "See the usage docs for"), "inline_markup")
rejects("gloss that introduces a new number",
        BASE, BASE.replace("Nested item about the cache.", "Nested item about the cache (kept for 30 days)."), "protected_token")
rejects("gloss that introduces a new URL",
        BASE, BASE.replace("Nested item about the cache.", "Nested item about the cache (see https://cache.example)."), "protected_token")
rejects("changed identifier", BASE, BASE.replace("snake_case_name", "snake case name"), "protected_token")
rejects("changed dotted name", BASE, BASE.replace("config.json", "the config file"), "protected_token")
rejects("changed inline code", BASE, BASE.replace("`polish-gemini.sh`", "`polish.sh`"), "protected_token")
rejects("changed AC ID", BASE, BASE.replace("AC-1", "AC-2"), "protected_token")

# ----------------------------------------------------------------------------
# Rejected rewrites: structure
# ----------------------------------------------------------------------------

rejects("extra heading", BASE, BASE.replace("## Steps", "## Steps\n\n### Extra"), "structure")
rejects("heading level changed", BASE, BASE.replace("## Steps", "### Steps"), "structure")
rejects("paragraph split in two", BASE, BASE.replace("at most.\nSee", "at most.\n\nSee"), "structure")
rejects("list item dropped", BASE, BASE.replace("2. Run the setup command.\n", ""), "structure")
rejects("nested list flattened", BASE, BASE.replace("  - Nested item", "- Nested item"), "structure")
rejects("ordered list turned unordered", BASE, BASE.replace("1. Install", "- Install").replace("2. Run", "- Run"), "structure")
rejects("unordered marker style changed", BASE, BASE.replace("- First item", "* First item"), "structure")
rejects("task marker changed", BASE, BASE.replace("- [ ] Open task", "- [x] Open task"), "structure")
rejects("blockquote level removed", BASE, BASE.replace("> > A nested quote", "> A nested quote"), "structure")
rejects("changed frontmatter", BASE, BASE.replace("version: 2", "version: 3"), "region_changed")
rejects("changed polish:off region", BASE, BASE.replace("must never change, even if", "must never change even if"), "region_changed")
rejects("changed HTML block", BASE, BASE.replace("Raw HTML block stays", "Raw HTML block remains"), "region_changed")
rejects("changed math block", BASE, BASE.replace("E = mc^2", "E = m c^2"), "region_changed")
rejects("changed footnote definition", BASE, BASE.replace("The footnote text stays", "The footnote text remains"), "region_changed")
rejects("changed reference definition", BASE, BASE.replace("https://example.com/ref", "https://example.com/r2"), "region_changed")
rejects("table column added", BASE, BASE.replace("| 900 seconds |", "| 900 seconds | extra |"), "structure")
rejects("table separator changed", BASE, BASE.replace("|-----|---------|", "|:----|---------|"), "region_changed")

# ----------------------------------------------------------------------------
# Rejected rewrites: inline markup
# ----------------------------------------------------------------------------

rejects("strong changed to em", BASE, BASE.replace("<strong>bold HTML</strong>", "<em>bold HTML</em>"), "inline_markup")
rejects("image removed", BASE, BASE.replace(" and ![an image](img/chart.png) in", " in"), "inline_markup")
rejects("link turned into plain text",
        "Read [the guide](https://example.com/guide) before you start the setup.\n",
        "Read the guide at example dot com before you start the setup.\n", "inline_markup")
rejects("emphasis removed", BASE, BASE.replace("*emphasis*", "emphasis"), "inline_markup")
rejects("hard line break removed",
        "First line of the address  \nSecond line of the address\n",
        "First line of the address Second line of the address\n", "inline_markup")
rejects("character reference changed",
        "Tom &amp; Jerry are in this sentence about the show.\n",
        "Tom & Jerry are in this sentence about the show.\n", "protected_token")

# ----------------------------------------------------------------------------
# Rejected rewrites: language and length
# ----------------------------------------------------------------------------

rejects("English paragraph translated to Chinese", EN_SRC, ZH_SRC, "script_changed")
rejects("Chinese paragraph translated to English", ZH_SRC, EN_SRC, "script_changed")
rejects("block grows past the ratio bound",
        "This sentence is long enough to be checked for its length ratio by the guard.\n",
        "This sentence is long enough to be checked for its length ratio by the guard, and then it keeps "
        "going with many more words that were never in the original sentence at all, which is not allowed.\n",
        "length_ratio")
rejects("block shrinks past the ratio bound",
        "This sentence is long enough to be checked for its length ratio by the guard.\n",
        "Checked by the guard.\n", "length_ratio")

# ----------------------------------------------------------------------------
# Segments
# ----------------------------------------------------------------------------

SEG = "[[s1]] Click the button to start 2 jobs.\n[[s2]] Save your work before you leave.\n"
try:
    out = g.check_segments(SEG, "[[s1]] Press the button to start 2 jobs.\n[[s2]] Save what you did before you leave.")
    report("segments rewording passes", [s[0] for s in out] == ["s1", "s2"], repr(out))
except g.GuardReject as exc:
    report("segments rewording passes", False, exc.detail)

for name, cand in (
        ("segments missing ID", "[[s1]] Press the button to start 2 jobs."),
        ("segments reordered IDs", "[[s2]] Save your work.\n[[s1]] Click the button to start 2 jobs."),
        ("segments extra line", "[[s1]] Click the button to start 2 jobs.\n[[s2]] Save your work.\n[[s3]] More."),
        ("segments line without ID", "Click the button to start 2 jobs.\n[[s2]] Save your work."),
        ("segments emptied text", "[[s1]] \n[[s2]] Save your work before you leave.")):
    try:
        g.check_segments(SEG, cand)
        report(name, False, "accepted")
    except g.GuardReject as exc:
        report(name, exc.reason == "segment_mismatch", "%s %s" % (exc.reason, exc.detail))

try:
    g.check_segments(SEG, "[[s1]] Click the button to start 3 jobs.\n[[s2]] Save your work before you leave.")
    report("segments protected token changed", False, "accepted")
except g.GuardReject as exc:
    report("segments protected token changed", exc.reason == "protected_token", exc.reason)

try:
    g.parse_segments("no id here")
    report("malformed segments input is detected", False, "parsed")
except ValueError:
    report("malformed segments input is detected", True)

# ----------------------------------------------------------------------------
# HTML adapter
# ----------------------------------------------------------------------------

PAGE = """<!DOCTYPE html>
<html>
<head>
  <title>Usage Dashboard</title>
  <meta name="description" content="Not eligible text">
  <style>p { color: red; }</style>
  <script>var s = "<p>not text</p>";</script>
</head>
<body>
  <!-- a comment -->
  <h1>Welcome to the dashboard</h1>
  <p>
    Tom &amp; Jerry&nbsp;used it 3 times.
  </p>
  <button aria-label="Start the job" class="primary">Start</button>
  <img src="chart.png" alt="Chart of usage" title='Monthly "usage"'>
  <input placeholder="Type here" value="not eligible">
  <pre>preformatted text</pre>
  <code>code text</code>
  <kbd>Ctrl</kbd> <samp>sample</samp>
  <textarea>area text</textarea>
  <noscript>no script text</noscript>
  <template><p>template text</p></template>
  <svg><text>svg text</text></svg>
  <math><mi>x</mi></math>
  <p>Hello {{ name }}</p>
  <p>   </p>
</body>
</html>
"""

spans, segs = g.html_extract(PAGE)
seg_list = g.parse_segments(segs)
texts = [t for _, t in seg_list]
expected = ["Usage Dashboard", "Welcome to the dashboard", "Tom &amp; Jerry&nbsp;used it 3 times.",
            "Start the job", "Start", "Chart of usage", 'Monthly "usage"', "Type here", "Ctrl"]
# kbd is excluded; drop it from the expectation.
expected = [e for e in expected if e != "Ctrl"]
report("HTML extraction takes only eligible text and attributes", texts == expected, repr(texts))
excluded_words = ("Not eligible", "not text", "preformatted", "code text", "sample", "area text",
                  "no script", "template text", "svg text", "name", "not eligible", "color")
report("HTML extraction skips excluded elements, template syntax and other attributes",
       not any(w in segs for w in excluded_words), segs)

polished = list(texts)
polished[1] = "Welcome to your dashboard"
polished[2] = "Tom &amp; Jerry&nbsp;have used it 3 times & counting."
polished[6] = 'Monthly "usage" chart'
out = g.html_splice(PAGE, spans, polished)
try:
    g.html_verify(PAGE, out)
    report("HTML splice verifies", True)
except g.GuardReject as exc:
    report("HTML splice verifies", False, exc.detail)
report("HTML splice keeps surrounding whitespace and escapes a bare ampersand",
       "<p>\n    Tom &amp; Jerry&nbsp;have used it 3 times &amp; counting.\n  </p>" in out, out)
report("HTML splice escapes quotes inside an attribute value",
       "title='Monthly \"usage\" chart'" in out or "title='Monthly &quot;usage&quot; chart'" in out, out)
report("HTML splice leaves unchanged spans byte-identical",
       "<title>Usage Dashboard</title>" in out and 'aria-label="Start the job"' in out, out)

for name, mutate in (
        ("non-eligible attribute changed", lambda s: s.replace('class="primary"', 'class="secondary"')),
        ("tag changed", lambda s: s.replace("<h1>Welcome to your dashboard</h1>", "<h2>Welcome to your dashboard</h2>")),
        ("comment changed", lambda s: s.replace("a comment", "another comment")),
        ("script changed", lambda s: s.replace("not text", "changed")),
        ("excluded text changed", lambda s: s.replace("code text", "other code"))):
    try:
        g.html_verify(PAGE, mutate(out))
        report("HTML verify rejects: %s" % name, False, "accepted")
    except g.GuardReject as exc:
        report("HTML verify rejects: %s" % name, exc.reason == "html_mismatch", exc.reason)

try:
    g.check_segments(segs, segs.replace("Start the job", "Start the <b>job</b>"), html_mode=True)
    report("HTML segment with new markup is rejected", False, "accepted")
except g.GuardReject as exc:
    report("HTML segment with new markup is rejected", exc.reason == "markup_in_text", exc.reason)

try:
    g.check_segments(segs, segs.replace("Jerry&nbsp;used", "Jerry used"), html_mode=True)
    report("HTML character reference dropped is rejected", False, "accepted")
except g.GuardReject as exc:
    report("HTML character reference dropped is rejected", exc.reason == "protected_token", exc.reason)

for name, html_text in (
        ("truncated end tag at end of file", "<div><p>Some text</p></div"),
        ("truncated start tag at end of file", "<p>Some text</p><div class=")):
    try:
        g.html_extract(html_text)
        report("unsupported HTML: %s" % name, False, "extracted")
    except g.UnsupportedInput as exc:
        report("unsupported HTML: %s" % name, exc.reason == "unsupported_html", exc.reason)

frag_spans, frag_segs = g.html_extract("<p>Fragment paragraph text.</p>\n<button>Go</button>\n")
report("HTML fragment without body is eligible", frag_segs == "[[s1]] Fragment paragraph text.\n[[s2]] Go", frag_segs)

# ----------------------------------------------------------------------------
# Regression cases from the adversarial review of the guard
# ----------------------------------------------------------------------------

# Tokens that used to slip through.
rejects("slash path changed", "Open src/main now.\n", "Open src/test now.\n", "protected_token")
rejects("leading-underscore name changed", "Use _cache here.\n", "Use _store here.\n", "protected_token")
rejects("one-letter dotted name changed", "Call a.b now.\n", "Call a.c now.\n", "protected_token")
rejects("acronym-prefixed name changed", "Call XMLParser now.\n", "Call JSONParser now.\n", "protected_token")
rejects("collapsed reference target changed",
        "Read [safe][].\n\n[safe]: /safe\n[evil]: /evil\n",
        "Read [evil][].\n\n[safe]: /safe\n[evil]: /evil\n", "inline_markup")
rejects("shortcut reference turned into text",
        "Read [guide].\n\n[guide]: /safe\n", "Read guide.\n\n[guide]: /safe\n", "inline_markup")
rejects("digit-leading inline math changed", "Use $2x$ here.\n", "Use $2x + y$ here.\n")
rejects("whitespace inside an inline HTML attribute changed",
        'See <a href="some  page">this page</a>.\n', 'See <a href="some page">this page</a>.\n',
        "inline_markup")
rejects("unit changed", "Wait 30 ms.\n", "Wait 30 s.\n", "protected_token")
rejects("short block grows without bound", "Ready.\n", "Ready. Backups are erased automatically.\n",
        "length_ratio")
accepts("plain prose slash pair stays editable", "Use this and/or that.\n", "Use this one and/or that.\n")
accepts("abbreviation stays editable", "Use a tool, e.g. a linter.\n", "Use a tool, e.g. a code linter.\n")
accepts("underscore emphasis stays editable",
        "This is _really important_ guidance.\n", "This is _very important_ guidance.\n")
accepts("plural acronym stays editable", "Open two PRs today.\n", "Open two pull requests today.\n")
accepts("price text stays editable", "It costs $5 or $10 a month.\n", "It costs $5 or $10 per month.\n")

# Protected Markdown regions that used to be editable.
rejects("indented code changed", "Example:\n\n    echo alpha\n", "Example:\n\n    echo beta\n", "region_changed")
rejects("fence opened on a list marker changed",
        "- ```sh\n  echo alpha\n  ```\n", "- ```sh\n  echo beta\n  ```\n", "region_changed")
rejects("raw HTML block across blank lines changed",
        '<script>\n\nalert("alpha")\n\n</script>\n', '<script>\n\nalert("beta")\n\n</script>\n',
        "region_changed")
rejects("multi-line reference title changed",
        '[r]: /docs\n  "Old title"\n\nRead [r].\n', '[r]: /docs\n  "New title"\n\nRead [r].\n',
        "region_changed")
rejects("footnote continuation changed",
        "Text[^a].\n\n[^a]: first\n\n    second part\n", "Text[^a].\n\n[^a]: first\n\n    changed part\n",
        "region_changed")

# Structures that used to compare equal.
rejects("lazy thematic break turned into a quoted heading", "> Title\n---\n", "> Title\n> ---\n", "structure")
rejects("sibling list item nested", "- a\n - b\n", "- a\n  - b\n", "structure")
rejects("heading moved out of a list item", "- Parent\n\n  ## Heading\n", "- Parent\n\n## Heading\n",
        "structure")
rejects("pipe-free table row moved out of the table",
        "A | B\n--- | ---\ncell\n", "A | B\n--- | ---\n\ncell\n", "structure")
accepts("pipe-free table row padded with a pipe", "A | B\n--- | ---\ncell\n", "A | B\n--- | ---\ncell |\n")
rejects("bare carriage return adds a heading", "Read the setup guide.\n", "Read the setup\r# guide.\n",
        "structure")

# Equivalent forms that used to be rejected.
accepts("one-dash setext underline equals an ATX heading", "Title\n-\n", "## Title\n")
accepts("prose after a one-line raw HTML block stays editable",
        "<script></script>\nRead the old docs.\n", "<script></script>\nRead the new docs.\n")

# HTML adapter holes.
for name, html_text in (
        ("self-closing script", '<script/>alert("alpha")</script><p>Read docs.</p>'),
        ("attribute syntax the parser reads differently", "<div a\"b=c title=\"x\">Docs</div>"),
        ("character reference without a semicolon", "<p>&copy old docs</p>")):
    try:
        g.html_extract(html_text)
        report("unsupported HTML: %s" % name, False, "extracted")
    except g.UnsupportedInput as exc:
        report("unsupported HTML: %s" % name, exc.reason == "unsupported_html", exc.reason)

inv_spans, inv_segs = g.html_extract("<div data-x=foo\"title='old'>Docs</div>")
report("HTML unquoted value is not split into an invented attribute", inv_segs == "[[s1]] Docs", inv_segs)
pre_spans, pre_segs = g.html_extract('<p style="white-space:pre">Read\n    old docs</p><p>Other text.</p>')
report("HTML text with preserved whitespace is not eligible", pre_segs == "[[s1]] Other text.", pre_segs)
nbsp_spans, nbsp_segs = g.html_extract("<p>Read\u00a0\u00a0old docs</p>")
report("HTML extraction keeps NBSP", nbsp_segs == "[[s1]] Read\u00a0\u00a0old docs", repr(nbsp_segs))
lt_page = "<p>Use the old form.</p>"
lt_spans, _ = g.html_extract(lt_page)
lt_out = g.html_splice(lt_page, lt_spans, ["Use the 1 > 0 form."])
report("HTML splice escapes angle brackets", lt_out == "<p>Use the 1 &gt; 0 form.</p>", lt_out)
nested_spans, nested_segs = g.html_extract("<pre><span>a</span> still pre</pre><p>Prose.</p>")
report("HTML excluded region ends at its own closing tag", nested_segs == "[[s1]] Prose.", nested_segs)

# ----------------------------------------------------------------------------
# Round 1 regression cases (review findings M1-M4 and M8)
# ----------------------------------------------------------------------------

# M1: blocks that start on a list-marker line.
for prefix, label in (("- ", "bullet"), ("1. ", "ordered"), ("> - ", "quoted bullet")):
    rejects("%s: indented code on the marker line changed" % label,
            prefix + "    echo hello\n", prefix + "    echo goodbye\n", "region_changed")
    rejects("%s: HTML block on the marker line changed" % label,
            prefix + "<div>Keep this sentence.</div>\n", prefix + "<div>Change this sentence.</div>\n",
            "region_changed")
    rejects("%s: heading level on the marker line changed" % label,
            prefix + "# First section\n", prefix + "## First section\n", "structure")
    rejects("%s: reference definition on the marker line changed" % label,
            prefix + '[ref]: /foo "Keep title"\n', prefix + '[ref]: /foo "Changed title"\n',
            "region_changed")
    accepts("%s: prose on the marker line stays editable" % label,
            prefix + "Install the plugin before you start.\n",
            prefix + "Install the plugin before starting.\n")
rejects("quote on the marker line removed", "- > Quoted message\n", "- Quoted message\n", "structure")
rejects("quote moved out of a list item", "- Item.\n\n  > Quoted message\n", "- Item.\n\n> Quoted message\n",
        "structure")
rejects("nested item on the marker line flattened", "- - inner item\n", "- inner item\n", "structure")
rejects("blank line added between list items", "- One item.\n- Other item.\n",
        "- One item.\n\n- Other item.\n", "structure")
rejects("blank line removed between list items", "- One item.\n\n- Other item.\n",
        "- One item.\n- Other item.\n", "structure")
rejects("thematic break after a list turned into a setext heading in the item",
        "- Item text\n---\n", "- Item text\n  ---\n", "structure")
accepts("loose list keeps its blank lines", "- One item.\n\n- Other item.\n",
        "- One item here.\n\n- Other item here.\n")
rejects("task marker line content turned into a heading", "- [ ] Write the docs\n",
        "- [ ] # Write the docs\n", "structure")
accepts("task item reworded", "- [ ] Write the docs\n", "- [ ] Write the documentation\n")

# M2: polish:off regions inside containers and inline.
QUOTED_OFF = "> <!-- polish:off -->\n> Never change this sentence.\n> <!-- polish:on -->\n"
rejects("quoted polish:off region changed", QUOTED_OFF, QUOTED_OFF.replace("Never", "Always"),
        "region_changed")
LIST_OFF = "- Item.\n\n  <!-- polish:off -->\n  Keep this exact text.\n  <!-- polish:on -->\n"
rejects("list-contained polish:off region changed", LIST_OFF, LIST_OFF.replace("exact", "precise"),
        "region_changed")
INLINE_OFF = "Read <!-- polish:off -->keep this text<!-- polish:on --> carefully today.\n"
rejects("inline polish:off region changed", INLINE_OFF, INLINE_OFF.replace("keep", "edit"),
        "region_changed")
accepts("text outside an inline polish:off region stays editable", INLINE_OFF,
        INLINE_OFF.replace("carefully today", "with care today"))
UNCLOSED = "Read <!-- polish:off -->keep this text\n\nAnd keep this paragraph too.\n"
rejects("unterminated inline polish:off protects later blocks", UNCLOSED,
        UNCLOSED.replace("keep this paragraph", "change this paragraph"), "region_changed")
rejects("unterminated inline polish:off protects the rest of its block", UNCLOSED,
        UNCLOSED.replace("keep this text", "edit this text"), "region_changed")
UNCLOSED_LINE = "Intro paragraph.\n\n<!-- polish:off -->\nKeep this.\n\nAnd this.\n"
rejects("unterminated polish:off line protects to the end", UNCLOSED_LINE,
        UNCLOSED_LINE.replace("And this", "Also this"), "region_changed")

# M3: paired math.
rejects("digit-leading dollar math with spaces changed", "Use $2 x + y$ here.\n", "Use $2 x - y$ here.\n",
        "protected_token")
rejects("TeX inline math changed", "Compute \\(x + y\\) carefully.\n", "Compute \\(x - y\\) carefully.\n",
        "protected_token")
rejects("TeX display math in a paragraph changed", "Then \\[a = b + c\\] holds.\n",
        "Then \\[a = b - c\\] holds.\n", "protected_token")
rejects("inline double-dollar math changed", "So $$a + b$$ holds.\n", "So $$a - b$$ holds.\n",
        "protected_token")
accepts("prices with a space before the second dollar stay prose", "It costs $5 or $10 a month.\n",
        "It costs $5 or $10 every month.\n")
for name, cand in (("segments digit-leading math changed", "[[s1]] Use $2 x - y$ here."),
                   ("segments TeX math changed", "[[s1]] Use \\(x - y\\) here.")):
    src_seg = "[[s1]] Use $2 x + y$ here." if "digit" in name else "[[s1]] Use \\(x + y\\) here."
    try:
        g.check_segments(src_seg, cand)
        report(name, False, "accepted")
    except g.GuardReject as exc:
        report(name, exc.reason == "protected_token", exc.reason)

# M4: escaped punctuation.
rejects("escaped emphasis turned into emphasis", "This is \\*literal\\* text.\n", "This is *literal* text.\n",
        "inline_markup")
rejects("escaped link turned into a link", "Read \\[the guide](guide.md) carefully.\n",
        "Read [the guide](guide.md) carefully.\n", "inline_markup")
rejects("escaped HTML turned into HTML", "Use \\<span>hello</span> safely.\n",
        "Use <span>hello</span> safely.\n", "inline_markup")
rejects("escape added to emphasis", "This is *bold* text.\n", "This is \\*bold\\* text.\n", "inline_markup")
rejects("escaped backslash before emphasis made odd", "Keep \\\\*this* word.\n", "Keep \\*this* word.\n",
        "inline_markup")
accepts("escaped backslash before emphasis reworded", "Keep \\\\*this* word.\n", "Keep \\\\*that* word.\n")
accepts("escaped text reworded around the escapes", "This is \\*literal\\* text.\n",
        "This is \\*literal\\* wording.\n")
rejects("backslash inside a code span is literal", "Run `a\\*b` now.\n", "Run `a*b` now.\n",
        "protected_token")
rejects("escaped backtick does not open a code span", "Use \\`tick and `code` here.\n",
        "Use `tick and `code` here.\n")

# M8: eligible attributes on body and unquoted values.
ATTR_PAGE = '<body aria-label="Page overview"><input placeholder=Search><p>Read the guide.</p></body>'
attr_spans, attr_segs = g.html_extract(ATTR_PAGE)
report("HTML body attribute and unquoted value are extracted",
       attr_segs == "[[s1]] Page overview\n[[s2]] Search\n[[s3]] Read the guide.", attr_segs)
attr_out = g.html_splice(ATTR_PAGE, attr_spans, ["Overview of the page", 'Search "docs" = fast/', "Read the guide."])
try:
    g.html_verify(ATTR_PAGE, attr_out)
    report("HTML unquoted value with spaces and quotes verifies", True)
except g.GuardReject as exc:
    report("HTML unquoted value with spaces and quotes verifies", False, exc.detail)
report("HTML unquoted value is escaped into one value",
       "placeholder=Search&#32;&quot;docs&quot;&#32;&#61;&#32;fast&#47;>" in attr_out, attr_out)
report("HTML bytes outside the attribute values are unchanged",
       attr_out.startswith('<body aria-label="Overview of the page"><input placeholder=')
       and attr_out.endswith("><p>Read the guide.</p></body>"), attr_out)
_, excl_segs = g.html_extract('<body><code title="Not eligible">x</code><pre><abbr title=Hidden>y</abbr></pre>'
                              '<p title=Shown>Text.</p></body>')
report("HTML attributes under excluded elements are not extracted",
       excl_segs == "[[s1]] Shown\n[[s2]] Text.", excl_segs)
# AC-7: eligible attributes count on any element that is not excluded,
# including <html> and elements in <head>; only text nodes are limited to
# <body> and <title>.
SCOPE_PAGE = ('<html title="Page title"><head><link rel="alternate" title="Feed title"></head>'
              '<body><p>Visible text.</p></body></html>')
scope_spans, scope_segs = g.html_extract(SCOPE_PAGE)
report("HTML attributes on <html> and in <head> are extracted",
       scope_segs == "[[s1]] Page title\n[[s2]] Feed title\n[[s3]] Visible text.", scope_segs)
scope_out = g.html_splice(SCOPE_PAGE, scope_spans, ["Title of the page", "Title of the feed", "Text you can see."])
try:
    g.html_verify(SCOPE_PAGE, scope_out)
    scope_ok = scope_out == ('<html title="Title of the page"><head><link rel="alternate" title="Title of the feed">'
                             '</head><body><p>Text you can see.</p></body></html>')
except g.GuardReject as exc:
    scope_ok = False
    scope_out = exc.reason
report("HTML attributes outside the body splice back and verify", scope_ok, scope_out)
_, head_excl = g.html_extract('<html><head><script title="x">var a;</script><style title="y">p{}</style>'
                              '<meta name="d" content="c"><noscript><img alt="No"></noscript></head>'
                              '<body><code title="Code">x</code><p>Hi there.</p></body></html>')
report("HTML attributes on or inside excluded elements in <head> stay excluded",
       head_excl == "[[s1]] Hi there.", head_excl)
_, head_off = g.html_extract('<html><head><!-- polish:off --><link title="Keep"><!-- polish:on -->'
                             '<link title="Feed"></head><body><p>Hi.</p></body></html>')
report("HTML attributes in a polish:off region in <head> stay excluded",
       head_off == "[[s1]] Feed\n[[s2]] Hi.", head_off)

# Round 1 re-review follow-ups.
rejects("a tab inside inline code changed to spaces", "Use `a\tb` carefully.\n", "Use `a  b` carefully.\n",
        "protected_token")
accepts("rewording before inline code that holds a tab", "Use `a\tb` carefully.\n", "Read `a\tb` carefully.\n")
rejects("a tab inside a fence on a list marker changed", "- ```sh\n  printf 'a\tb'\n  ```\n",
        "- ```sh\n  printf 'a    b'\n  ```\n", "region_changed")
rejects("link target after an escape changed", "Read [guide](folder\\*old) carefully.\n",
        "Read [guide](folder\\*new) carefully.\n", "inline_markup")
rejects("URL after an escape changed", "Visit https://example.com/a\\?old carefully.\n",
        "Visit https://example.com/a\\?new carefully.\n")
rejects("double-dollar math with spaces changed", "So $$ a + b $$ holds.\n", "So $$ a - b $$ holds.\n",
        "protected_token")
rejects("dollar math followed by a letter changed", "Use $2 x + y$th term.\n", "Use $2 x - y$th term.\n",
        "protected_token")
SPAN_OFF = "Read <!-- polish:off -->keep.\n\nKeep too. <!-- polish:on -->\n"
rejects("blank line added inside a polish:off region that spans blocks", SPAN_OFF,
        SPAN_OFF.replace("keep.\n\n", "keep.\n\n\n"), "region_changed")
TRAIL_OFF = "Read <!-- polish:off -->keep this  \ntext here.\n"
rejects("trailing spaces removed inside an unterminated region", TRAIL_OFF,
        TRAIL_OFF.replace("this  \n", "this\n"), "region_changed")
accepts("prose after polish:on in the closing block stays editable",
        "Read <!-- polish:off -->keep.\n\nKeep too. <!-- polish:on --> Read carefully.\n",
        "Read <!-- polish:off -->keep.\n\nKeep too. <!-- polish:on --> Read with care.\n")
accepts("prose before polish:off in a list item stays editable",
        "- Read <!-- polish:off -->keep.\n\n  Keep too. <!-- polish:on -->\n",
        "- View <!-- polish:off -->keep.\n\n  Keep too. <!-- polish:on -->\n")
accepts("a marker inside inline code is just text", "Use `<!-- polish:off -->` carefully.\n",
        "Use `<!-- polish:off -->` with care.\n")
accepts("a marker inside a fenced block is just text",
        "```html\n<!-- polish:off -->\n```\n\nRead the notes carefully.\n",
        "```html\n<!-- polish:off -->\n```\n\nRead the notes with care.\n")
try:
    g.check_segments("[[s1]] <!-- polish:off -->keep\n[[s2]] Keep exact text.\n[[s3]] <!-- polish:on -->",
                     "[[s1]] <!-- polish:off -->keep\n[[s2]] Keep other text.\n[[s3]] <!-- polish:on -->")
    report("segments inside a polish:off region that spans segments", False, "accepted")
except g.GuardReject as exc:
    report("segments inside a polish:off region that spans segments", exc.reason == "region_changed", exc.reason)
_, off_segs = g.html_extract("<body><!-- polish:off --><p title=\"Keep\">Keep exact text.</p><!-- polish:on -->"
                             "<p>Polish this.</p></body>")
report("HTML text and attributes inside polish:off comments are not eligible",
       off_segs == "[[s1]] Polish this.", off_segs)
rejects("blank line added after a quoted list item", "- > Quoted text.\n- Next item.\n",
        "- > Quoted text.\n\n- Next item.\n", "structure")
accepts("quoted prose in a numbered item stays editable", "10. > Read the guide carefully.\n",
        "10. > Read the guide with care.\n")
accepts("an item after a quoted sibling stays editable",
        "- Parent.\n  - > Read the quote.\n  - Read the guide carefully.\n",
        "- Parent.\n  - > Read the quote.\n  - Read the guide with care.\n")

# Round 1 second re-review.
# (The destination belongs to the link, so its escapes are not TeX math:
# the change is a link change, as for any other destination.)
rejects("link destination suffix after TeX-like escapes changed", "Read [guide](folder\\(old\\)tail) carefully.\n",
        "Read [guide](folder\\(old\\)evil) carefully.\n", "inline_markup")
rejects("link destination suffix after dollar signs changed",
        "Read [guide](https://example.com/$token$old) carefully.\n",
        "Read [guide](https://example.com/$token$new) carefully.\n", "protected_token")
STRAY_TICKS = ("A literal ` here.\n\nRead <!-- polish:off -->Keep.\n\nKeep this protected sentence.\n\n"
               "End <!-- polish:on --> with another `.\n")
rejects("backticks in other paragraphs do not hide a polish:off region", STRAY_TICKS,
        STRAY_TICKS.replace("Keep this protected", "Change this protected"), "region_changed")
try:
    g.check_segments("[[a]] A literal ` here.\n[[b]] Read <!-- polish:off -->Keep.\n"
                     "[[c]] Keep this protected sentence.\n[[d]] End <!-- polish:on --> with another `.",
                     "[[a]] A literal ` here.\n[[b]] Read <!-- polish:off -->Keep.\n"
                     "[[c]] Change this protected sentence.\n[[d]] End <!-- polish:on --> with another `.")
    report("backticks in other segments do not hide a polish:off region", False, "accepted")
except g.GuardReject as exc:
    report("backticks in other segments do not hide a polish:off region", exc.reason == "region_changed",
           exc.reason)
rejects("indentation inside a code span that spans lines changed", "Use `a\n\tb` carefully.\n",
        "Use `a\n    b` carefully.\n", "protected_token")
rejects("a trailing space inside a code span that spans lines removed", "Use `a \nb` carefully.\n",
        "Use `a\nb` carefully.\n", "protected_token")
rejects("indentation inside TeX math that spans lines changed", "Use \\(a +\n  b\\) carefully.\n",
        "Use \\(a +\nb\\) carefully.\n", "protected_token")
rejects("display math written inside a paragraph changed", "Use $$\na + b\n$$ here.\n",
        "Use $$\na - b\n$$ here.\n", "protected_token")
accepts("prose around display math inside a paragraph stays editable",
        "The formula:\n$$\nE = mc^2\n$$\nholds for all cases here.\n",
        "The formula:\n$$\nE = mc^2\n$$\nholds in every case here.\n")
accepts("a paragraph may be wrapped differently", "This paragraph is long and it\nwraps across several lines of\n"
        "text in the source.\n", "This paragraph is long, and it wraps\nacross several lines of text in the source.\n")
accepts("continuation indentation outside tokens may change", "- First item reads\n  like this one.\n- Second item.\n",
        "- First item reads\n    like this.\n- Second item.\n")
rejects("blank line added after a quoted list item inside a quote", "> - > Quoted.\n> - Next item.\n",
        "> - > Quoted.\n>\n> - Next item.\n", "structure")
rejects("blank line removed before the first list item", "Para.\n\n- item one here\n",
        "Para.\n- item one here\n", "structure")
# (A line that starts with the polish:on marker is an HTML block line to the
# renderers, so the text after the marker there is raw HTML; text after a
# marker that follows other text on its line is paragraph text.)
rejects("text after a polish:on marker that starts its line (raw HTML to the renderers)",
        "Intro.\n\n<!-- polish:off -->\nKeep.\n<!-- polish:on --> Read carefully.\n",
        "Intro.\n\n<!-- polish:off -->\nKeep.\n<!-- polish:on --> Read with care.\n")
accepts("prose after a polish:on marker that follows other text on its line stays editable",
        "Intro.\n\n<!-- polish:off -->\nKeep.\nAlso keep. <!-- polish:on --> Read carefully.\n",
        "Intro.\n\n<!-- polish:off -->\nKeep.\nAlso keep. <!-- polish:on --> Read with care.\n")
rejects("the closing line of a standalone region before its marker is protected",
        "Intro.\n\n<!-- polish:off -->\nKeep.\nAlso keep. <!-- polish:on --> Read carefully.\n",
        "Intro.\n\n<!-- polish:off -->\nKeep.\nAlso held. <!-- polish:on --> Read carefully.\n", "region_changed")
accepts("a marker inside indented code is just text", "    <!-- polish:off -->\n\nRead carefully.\n",
        "    <!-- polish:off -->\n\nRead with care.\n")
accepts("a marker inside a fence behind two list markers is just text",
        "- - ```html\n    <!-- polish:off -->\n    ```\n\nRead carefully.\n",
        "- - ```html\n    <!-- polish:off -->\n    ```\n\nRead with care.\n")

# Round 2: list ancestry across blockquotes (a list item that contains a quote
# still contains the blocks after it).
for name, src, cand in [
        ("nested item after a quoted item flattened", "- > Quoted message.\n  - Child item.\n",
         "- > Quoted message.\n- Child item.\n"),
        ("paragraph after a quoted item moved out of the item", "- > Quoted message.\n\n  Following paragraph.\n",
         "- > Quoted message.\n\nFollowing paragraph.\n"),
        ("heading after a quoted item moved out of the item", "- > Quoted message.\n\n  # Heading\n",
         "- > Quoted message.\n\n# Heading\n"),
        ("nested item after a quoted item inside a quote flattened", "> - > Quoted message.\n>   - Child item.\n",
         "> - > Quoted message.\n> - Child item.\n"),
        ("ordered nested item after a quoted item flattened", "1. > Quoted message.\n   1. Child item.\n",
         "1. > Quoted message.\n1. Child item.\n"),
        ("nested item after a blank line and a quoted item flattened", "- > Quoted message.\n\n  - Child item.\n",
         "- > Quoted message.\n\n- Child item.\n"),
        ("grandchild after a quoted child flattened", "- Parent.\n  - > Quoted.\n    - Grandchild.\n",
         "- Parent.\n  - > Quoted.\n  - Grandchild.\n")]:
    rejects(name, src, cand, "structure")
accepts("prose rewrites inside a quoted item and its child", "- > Quoted message here.\n  - Child item here.\n",
        "- > Quoted message is here.\n  - Child item is here.\n")
accepts("prose rewrite of a paragraph that stays in the quoted item",
        "- > Quoted message.\n\n  Following paragraph here.\n", "- > Quoted message.\n\n  The following paragraph here.\n")
accepts("prose rewrite of a nested item inside a quote", "> - > Quoted message.\n>   - Child item here.\n",
        "> - > Quoted message.\n>   - The child item here.\n")
accepts("prose rewrites around a quote after a list", "- Item one.\n\n> A note after the list.\n\nNext paragraph here.\n",
        "- Item one.\n\n> A note that follows the list.\n\nThe next paragraph here.\n")

# Round 2: balanced link destinations.
for name, src, cand in [
        ("two-level destination changed", "Read [guide](folder(alpha(beta))tail) carefully.\n",
         "Read [guide](folder(alpha(beta))evil) carefully.\n"),
        ("two-level image destination changed", "See ![photo](folder(alpha(beta))tail) carefully.\n",
         "See ![photo](folder(alpha(beta))evil) carefully.\n"),
        ("three-level destination changed", "Read [guide](a(b(c(d)))e) carefully.\n",
         "Read [guide](a(b(c(d)))f) carefully.\n"),
        ("destination with escaped parentheses changed", "Read [guide](a\\(b\\)c) carefully.\n",
         "Read [guide](a\\(b\\)d) carefully.\n"),
        ("title with parentheses changed", "Read [guide](/x \"Old (title)\") carefully.\n",
         "Read [guide](/x \"New (title)\") carefully.\n"),
        ("nested-destination link turned into text", "Read [guide](folder(alpha(beta))tail) carefully.\n",
         "Read guide carefully.\n")]:
    rejects(name, src, cand)
accepts("label of a two-level destination link reworded", "Read [the guide](folder(alpha(beta))tail) carefully.\n",
        "Read [the full guide](folder(alpha(beta))tail) with care.\n")
accepts("alt text of a nested-destination image reworded", "See ![a photo](a(b(c))d) here today.\n",
        "See ![the photo](a(b(c))d) here now.\n")
try:
    g.check_segments("[[s1]] Read [guide](folder(alpha(beta))tail) carefully.",
                     "[[s1]] Read [guide](folder(alpha(beta))evil) carefully.")
    report("segments: two-level destination changed", False, "accepted")
except g.GuardReject as exc:
    report("segments: two-level destination changed", True, exc.reason)
DEEP = "Read [x](" + "(" * 40 + "a" + ")" * 40 + ") now.\n"
rejects("a link nested beyond the scanner limit freezes its block", DEEP, DEEP.replace("now", "today"))
accepts("a link nested beyond the scanner limit is accepted unchanged", DEEP, DEEP)

# Round 2: quote-aware HTML tags.
for name, src, cand in [
        ("quoted > in an inline tag attribute changed", "Read <span title=\"a > old\">the guide</span> carefully.\n",
         "Read <span title=\"a > new\">the guide</span> carefully.\n"),
        ("single-quoted > in an inline tag attribute changed", "Read <span title='a > old'>the guide</span> carefully.\n",
         "Read <span title='a > new'>the guide</span> carefully.\n"),
        ("multi-line inline tag attribute changed", "Read <span\n  title=\"a > old\">the guide</span> carefully.\n",
         "Read <span\n  title=\"a > new\">the guide</span> carefully.\n"),
        ("HTML block after a custom tag with a quoted > changed", "<custom title=\"a > b\">\nKeep text.\n\nRead more.\n",
         "<custom title=\"a > b\">\nEdit text.\n\nRead more.\n"),
        ("HTML block after a hyphenated tag with a single-quoted > changed",
         "<custom-el data-x='a > b'>\nKeep text.\n\nRead more.\n",
         "<custom-el data-x='a > b'>\nEdit text.\n\nRead more.\n")]:
    rejects(name, src, cand)
accepts("text around a tag with a quoted > reworded", "Read <span title=\"a > old\">the guide</span> carefully.\n",
        "Read <span title=\"a > old\">the full guide</span> with care.\n")
accepts("paragraph after a custom HTML block reworded", "<custom title=\"a > b\">\nKeep text.\n\nRead more of it.\n",
        "<custom title=\"a > b\">\nKeep text.\n\nRead more of this.\n")
accepts("comparison signs in prose stay prose", "If a < b and c > d holds, stop.\n",
        "If a < b and c > d holds, then stop.\n")

# Round 2: reference definitions across lines.
for name, src, cand in [
        ("destination on the line after the label changed", "[ref]:\n  /old \"Title\"\n\nRead [ref].\n",
         "[ref]:\n  /new \"Title\"\n\nRead [ref].\n"),
        ("title on the line after the label changed", "[ref]:\n  /guide \"Old title\"\n\nRead [ref].\n",
         "[ref]:\n  /guide \"New title\"\n\nRead [ref].\n"),
        ("unindented title continuation changed", "[ref]: /guide \"Old\ntitle here\"\n\nRead [ref].\n",
         "[ref]: /guide \"Old\nother text\"\n\nRead [ref].\n"),
        ("title on its own unindented line changed", "[ref]: /guide\n\"Old title\"\n\nRead [ref].\n",
         "[ref]: /guide\n\"New title\"\n\nRead [ref].\n"),
        ("definition inside a quote changed", "> [ref]:\n> /old \"Title\"\n", "> [ref]:\n> /new \"Title\"\n"),
        ("definition inside a list item changed", "- [ref]:\n  /old \"Title\"\n", "- [ref]:\n  /new \"Title\"\n")]:
    rejects(name, src, cand, "region_changed")
accepts("prose after a multi-line definition reworded", "[ref]:\n  /old \"Title\"\n\nRead [ref] for the details.\n",
        "[ref]:\n  /old \"Title\"\n\nRead [ref] for more details.\n")
accepts("paragraph right after a definition stays editable",
        "[ref]: /guide \"Old\ntitle here\"\nThe paragraph after it goes on.\n",
        "[ref]: /guide \"Old\ntitle here\"\nThe paragraph after it continues.\n")

# Round 2: single-dollar math across lines, paths and identifiers.
rejects("operator in single-dollar math across lines changed", "Use $x +\ny$ carefully.\n", "Use $x -\ny$ carefully.\n",
        "protected_token")
rejects("continuation whitespace in single-dollar math changed", "Use $x +\n  y$ carefully.\n",
        "Use $x +\ny$ carefully.\n", "protected_token")
accepts("prose around unchanged single-dollar math across lines reworded", "Use $x +\ny$ carefully in the end.\n",
        "Use $x +\ny$ with care in the end.\n")
accepts("prices on different lines stay prose", "It costs $5 a month, and\nthe big plan costs $10 a month.\n",
        "It costs $5 a month, while\nthe big plan costs $10 a month.\n")
for name, src, cand in [
        ("rooted path changed", "Read /etc carefully.\n", "Read /var carefully.\n"),
        ("home-relative path changed", "Use ~/file today.\n", "Use ~/other today.\n"),
        ("identifier with a trailing underscore changed", "Run tool_ here.\n", "Run other_ here.\n"),
        ("multi-component rooted path changed", "Read /etc/hosts carefully.\n", "Read /etc/passwd carefully.\n"),
        ("multi-component home path changed", "Use ~/a/b today.\n", "Use ~/a/c today.\n"),
        ("relative script path changed", "Open ./run.sh now.\n", "Open ./go.sh now.\n"),
        ("identifier with two trailing underscores changed", "Set x__ there.\n", "Set y__ there.\n")]:
    rejects(name, src, cand, "protected_token")
for name, src, cand in [
        ("prose around a rooted path reworded", "Read /etc carefully now.\n", "Read /etc with care now.\n"),
        ("prose around a home path reworded", "Use ~/file today please.\n", "Use ~/file today, please.\n"),
        ("prose around a trailing-underscore identifier reworded", "Run tool_ here and now.\n",
         "Run tool_ right here and now.\n"),
        ("underscore emphasis reworded", "This is _really_ important to know.\n", "This is _truly_ important to know.\n"),
        ("and/or stays prose", "Read it and/or skim it today.\n", "Read it and/or skim it now.\n"),
        ("a tilde before a number stays prose", "It takes ~5 minutes to finish.\n",
         "It takes about ~5 minutes to finish.\n")]:
    accepts(name, src, cand)
for name, src, cand in [
        ("segments: rooted path changed", "[[a]] Read /etc carefully.", "[[a]] Read /var carefully."),
        ("segments: home path changed", "[[a]] Use ~/file today.", "[[a]] Use ~/other today."),
        ("segments: trailing-underscore identifier changed", "[[a]] Run tool_ here.", "[[a]] Run other_ here.")]:
    try:
        g.check_segments(src, cand)
        report(name, False, "accepted")
    except g.GuardReject as exc:
        report(name, exc.reason == "protected_token", exc.reason)

# Round 2 re-review: nested quotes keep their columns inside list items.
for name, src, cand in [
        ("quote inside an ordered item in a quote moved out", "> 1. Parent.\n>    > Quoted text.\n",
         "> 1. Parent.\n> > Quoted text.\n"),
        ("quote inside a bullet item in a quote moved out", "> - Parent.\n>   > Quoted text.\n",
         "> - Parent.\n> > Quoted text.\n"),
        ("quote inside a nested item moved to the outer item", "- Parent.\n  - Child.\n    > Quoted text.\n",
         "- Parent.\n  - Child.\n  > Quoted text.\n"),
        ("quote opened on an ordered marker line moved out", "> 1.  > Quoted text.\n>     > More text.\n",
         "> 1.  > Quoted text.\n> > More text.\n")]:
    rejects(name, src, cand, "structure")
accepts("prose in a quote inside an ordered item in a quote reworded", "> 1. Parent.\n>    > Quoted text.\n",
        "> 1. Parent.\n>    > Quoted words.\n")
accepts("paragraph after a sibling quote at the item column reworded",
        "- Parent.\n\n> Quote.\n\n  Read the useful guide.\n", "- Parent.\n\n> Quote.\n\n  Read the helpful guide.\n")
accepts("quote after a list at column zero reworded", "- Item one.\n\n> Quoted text here.\n",
        "- Item one.\n\n> Quoted words here.\n")

# Round 2 re-review: links and images inside link labels.
for name, src, cand in [
        ("image destination inside a link changed", "Read [![photo](old)](folder(alpha(beta))tail) carefully.\n",
         "Read [![photo](new)](folder(alpha(beta))tail) carefully.\n"),
        ("image destination inside a plain link changed", "Read [![photo](old.png)](page) now.\n",
         "Read [![photo](new.png)](page) now.\n"),
        ("image title inside a link changed", "Read [![photo](a.png \"Old\")](page) now.\n",
         "Read [![photo](a.png \"New\")](page) now.\n"),
        ("outer destination around an image changed", "Read [![photo](a.png)](old) now.\n",
         "Read [![photo](a.png)](new) now.\n")]:
    rejects(name, src, cand, "inline_markup")
accepts("prose around an image inside a link reworded", "Read [![photo](a.png)](page) carefully.\n",
        "Read [![photo](a.png)](page) with care.\n")

# Round 2 re-review: reference definition labels with escapes or line breaks.
for name, src, cand in [
        ("definition with an escaped bracket in its label: title changed",
         "[a\\]b]: old \"Old title\"\n\nRead [a\\]b].\n", "[a\\]b]: old \"New title\"\n\nRead [a\\]b].\n"),
        ("definition with an escaped bracket in its label: destination changed",
         "[a\\]b]: old\n\nRead [a\\]b].\n", "[a\\]b]: new\n\nRead [a\\]b].\n"),
        ("definition with a label over two lines: destination changed",
         "[a\nb]: old \"Title\"\n\nRead [a b].\n", "[a\nb]: new \"Title\"\n\nRead [a b].\n"),
        ("definition with a label over two lines: title changed",
         "[a\nb]: /x \"Old\"\n\nRead [a b].\n", "[a\nb]: /x \"New\"\n\nRead [a b].\n")]:
    rejects(name, src, cand, "region_changed")
accepts("a bracketed sentence that is not a definition stays prose", "[Note] This is the useful part.\n",
        "[Note] This is the helpful part.\n")
accepts("a bracket over two lines that is not a definition stays prose",
        "[a\nb] is the useful part.\n", "[a\nb] is the helpful part.\n")

# Round 2 re-review: math or code characters inside tag attributes.
for name, src, cand in [
        ("quoted > after dollar signs in attributes changed",
         "Read <span title=\"$a\" data-x='$b > old'>the guide</span>.\n",
         "Read <span title=\"$a\" data-x='$b > new'>the guide</span>.\n"),
        ("backtick in an attribute value changed", "Read <span title=\"`a\" data-x='b > old`'>the guide</span>.\n",
         "Read <span title=\"`a\" data-x='b > new`'>the guide</span>.\n")]:
    rejects(name, src, cand, "inline_markup")
accepts("prose around a tag with dollar signs in attributes reworded",
        "Read <span title=\"$a\">the guide</span> carefully.\n", "Read <span title=\"$a\">the guide</span> with care.\n")

# Round 2 re-review: emphasis markers keep their opening and closing sides.
for name, src, cand in [
        ("emphasis turned into literal asterisks", "Read *useful* words today.\n", "Read * useful * words today.\n"),
        ("strong emphasis turned into literal asterisks", "Read **useful** words.\n", "Read ** useful ** words.\n"),
        ("underscore emphasis turned into literal underscores", "Read _useful_ words.\n", "Read _ useful _ words.\n"),
        ("strikethrough turned into literal tildes", "Old ~~text~~ here.\n", "Old ~~ text ~~ here.\n"),
        ("emphasis around a link removed", "Read *[guide](x)* today.\n", "Read [guide](x) today.\n"),
        ("strong emphasis made regular", "Read **useful** words.\n", "Read *useful* words.\n")]:
    rejects(name, src, cand, "inline_markup")
for name, src, cand in [
        ("emphasis moved with its words", "Read *useful* words today.\n", "Today, read *helpful* words.\n"),
        ("emphasis inside parentheses", "Read *useful* words.\n", "Read words (*useful* ones).\n"),
        ("underscore emphasis reworded around", "Read _useful_ words.\n", "Read _helpful_ words now.\n"),
        ("an underscore inside a word stays text", "Use snake_case names.\n", "Prefer snake_case names.\n")]:
    accepts(name, src, cand)
try:
    g.check_segments("[[a]] Read *useful* words.", "[[a]] Read * useful * words.")
    report("segments: emphasis turned into literal asterisks", False, "accepted")
except g.GuardReject as exc:
    report("segments: emphasis turned into literal asterisks", exc.reason == "inline_markup", exc.reason)

# Round 2 second re-review: quote continuation lines, lazy definitions,
# backslashes in labels, and the emphasis structure.
NESTED = "- Parent.\n  - Child.\n    - Grandchild.\n"
for name, src, cand in [
        ("quote continuation line moved out of an ordered item",
         "> 1. Parent.\n>    > Quoted words.\n>    > More words.\n",
         "> 1. Parent.\n>    > Quoted words.\n> > More words.\n"),
        ("quote after a nested item moved to the outer item", NESTED + "      > Quote text.\n",
         NESTED + "    > Quote text.\n"),
        ("quote after a blank line moved to the outer item", NESTED + "\n      > Quote text.\n",
         NESTED + "\n    > Quote text.\n")]:
    rejects(name, src, cand, "structure")
for name, src, cand in [
        ("definition with a lazy label line in a quote: destination changed",
         "> [a\nb]: old\n\nRead [a b].\n", "> [a\nb]: new\n\nRead [a b].\n"),
        ("definition with a backslash before the label line break: destination changed",
         "[a\\\nb]: old\n\nRead [a\\\nb].\n", "[a\\\nb]: new\n\nRead [a\\\nb].\n"),
        ("the same definition in a quote", "> [a\\\n> b]: old\n\nRead.\n", "> [a\\\n> b]: new\n\nRead.\n"),
        ("the same definition in a list item", "- [a\\\n  b]: old\n\nRead.\n", "- [a\\\n  b]: new\n\nRead.\n")]:
    rejects(name, src, cand, "region_changed")
for name, src, cand in [
        ("emphasis regrouped into nested spans", "Read *one* and **two** carefully.\n",
         "Read *one and **two* carefully**.\n"),
        ("strong emphasis split from its emphasis", "Read ***key*** words.\n", "Read **key** words.\n"),
        ("nested emphasis taken apart", "Read **a *b* c**.\n", "Read **a** *b* **c**.\n"),
        ("a literal asterisk removed", "Compute 2 * 3 here.\n", "Compute 2 times 3 here.\n")]:
    rejects(name, src, cand, "inline_markup")
for name, src, cand in [
        ("quote continuation line inside an ordered item reworded",
         "> 1. Parent.\n>    > Quoted words.\n>    > More words.\n",
         "> 1. Parent.\n>    > Quoted words.\n>    > More text.\n"),
        ("extra space between nested quote markers", "> > Read the useful guide.\n",
         ">  > Read the helpful guide.\n"),
        ("lazy paragraph line in a quote reworded", "> Read the useful\nguide today.\n",
         "> Read the helpful\nguide today.\n"),
        ("punctuation inside emphasis dropped", "Read *\u201cthe useful guide\u201d*.\n", "Read *the helpful guide*.\n"),
        ("nested emphasis closing together", "Read **the *useful* guide**.\n",
         "Read **the guide that is *helpful***.\n"),
        ("nested underscore emphasis closing together", "Read **the _useful_ guide**.\n",
         "Read **the guide that is _helpful_**.\n"),
        ("emphasis spans swapped with their words", "Use *a* and **b** here.\n", "Use **b** and *a* here.\n"),
        ("strikethrough moved with its words", "Old ~~text~~ here.\n", "Here is ~~old text~~.\n"),
        ("yes/no reworded as prose", "The yes/no choice is useful.\n", "The yes or no choice is helpful.\n")]:
    accepts(name, src, cand)
rejects("a real path next to the prose pairs still protected", "Use src/main here.\n", "Use src/other here.\n",
        "protected_token")

# Round 2 third re-review: lazy lines at any depth, tab columns after quote
# markers, table rows, quotes inside list items, and emphasis in link labels.
N = "- Parent.\n  - Child.\n"
for name, src, cand in [
        ("definition with a lazy line at an intermediate quote depth: destination changed",
         "> > [a\n> b]: old\n\nRead [a b].\n", "> > [a\n> b]: new\n\nRead [a b].\n"),
        ("definition with a lazy title line at an intermediate quote depth: title changed",
         "> > [a]: old \"The\n> title\"\n", "> > [a]: old \"The\n> heading\"\n"),
        ("code in a quote inside a nested item changed", N + "    > ```\n    > x = 1\n    > ```\n",
         N + "    > ```\n    > x = 2\n    > ```\n")]:
    rejects(name, src, cand, "region_changed")
for name, src, cand in [
        ("a tab after a quote marker at another column changes the list nesting",
         "> - Parent.\n>\t- > Quoted words.\n", "> - Parent.\n >\t- > Quoted words.\n"),
        ("a table row moved out of the list item", "- Parent.\n  > | Name | Value |\n  > | --- | --- |\n"
         "  > | Clear | Words |\n", "- Parent.\n  > | Name | Value |\n  > | --- | --- |\n> | Clear | Words |\n"),
        ("a quote inside a nested item moved to the parent item", N + "    > Quoted words.\n",
         N + "  > Quoted words.\n"),
        ("a quote inside a nested item moved out of the list", N + "    > Quoted words.\n", N + "> Quoted words.\n"),
        ("a quote inside a wide ordered item moved out", "10. Parent.\n\n    > Quoted words.\n",
         "10. Parent.\n\n> Quoted words.\n"),
        ("list nesting inside a quote inside an item changed", N + "    > - a item\n    >   - b item\n",
         N + "    > - a item\n    > - b item\n")]:
    rejects(name, src, cand, "structure")
for name, src, cand in [
        ("emphasis paired across a link label", "Read [*the guide](guide) carefully*.\n",
         "Read [the *guide*](guide) carefully.\n"),
        ("asterisk emphasis turned into underscores", "Read *the guide* carefully.\n", "Read _the guide_ carefully.\n"),
        ("asterisk strong emphasis turned into underscores", "Read **the guide** carefully.\n",
         "Read __the guide__ carefully.\n")]:
    rejects(name, src, cand, "inline_markup")
for name, src, cand in [
        ("a quote inside a nested item reworded", N + "    > Quoted words.\n", N + "    > Clear words.\n"),
        ("a two-line quote inside a nested item rewrapped", N + "    > Quoted words here.\n    > More words.\n",
         N + "    > Quoted words here and more words.\n"),
        ("a quote inside a wide ordered item reworded", "10. Parent.\n\n    > Quoted words.\n",
         "10. Parent.\n\n    > Clear words.\n"),
        ("a list inside a quote inside an item reworded", N + "    > - a item\n    > - b item\n",
         N + "    > - a thing\n    > - b thing\n"),
        ("a lazy line at an intermediate quote depth rewrapped", "> > Read this long\n> sentence carefully.\n",
         "> > Read this sentence carefully.\n"),
        ("prose after a tab after a quote marker reworded", "> - Parent.\n>\t- > Quoted words.\n",
         "> - Parent.\n>\t- > Quoted text.\n"),
        ("a quote opened with a tab after the first marker reworded", ">\t> Quoted words.\n", ">\t> Quoted text.\n"),
        ("a table inside a list item reworded", "- Parent.\n  | Name | Value |\n  | --- | --- |\n  | Clear | Words |\n",
         "- Parent.\n  | Name | Value |\n  | --- | --- |\n  | Plain | Words |\n"),
        ("emphasis inside link text reworded", "Read [the *useful* guide](x) now.\n",
         "Read [the *helpful* guide](x) now.\n"),
        ("emphasis around a link moved", "Read *[the guide](x)* now.\n", "Now read *[the guide](x)*.\n")]:
    accepts(name, src, cand)

# Round 2 fourth re-review: tabs in structural positions, overindented table
# rows, and original bytes for raw blocks after quote relocation.
LEAF = "> - Parent.\n>   - Child.\n>     - Leaf.\n>       >\t  OLD\n"
QFENCE = "- Parent.\n  - Child.\n    > ```\n    > keep\n    > ```\n"
for name, src, cand in [
        ("indented code after a tab in a relocated quote changed", LEAF, LEAF.replace("OLD", "NEW")),
        ("the prefix bytes of a fence in a relocated quote changed", QFENCE, QFENCE.replace("    >", "\t>")),
        ("an indented code line written with a tab instead of spaces", "Text.\n\n\tcode\n", "Text.\n\n    code\n")]:
    rejects(name, src, cand, "region_changed")
for name, src, cand in [
        ("a tab after a list marker inside a quote: sibling made a child", "> -\tParent.\n> - Child.\n",
         "> -\tParent.\n>   - Child.\n"),
        ("a table row indented into code", "> | Name |\n> | --- |\n> | Words |\n",
         "> | Name |\n> | --- |\n>     | Words |\n"),
        ("a table separator indented into code", "> | Name |\n> | --- |\n> | Words |\n",
         "> | Name |\n>     | --- |\n> | Words |\n")]:
    rejects(name, src, cand, "structure")
for name, src, cand in [
        ("quoted prose after a tab inside a nested item reworded", "- Parent.\n  - Child.\n    >\t Quoted words.\n",
         "- Parent.\n  - Child.\n    >\t Clear words.\n"),
        ("a list item after a tab inside a quote reworded", "> -\tParent.\n> - Child.\n",
         "> -\tParent item.\n> - Child.\n")]:
    accepts(name, src, cand)

# Round 2 fifth re-review: relocated quote continuation lines, raw blocks
# after a polish:on cut, and quotes a few columns past a list item.
for name, src, cand, reason in [
        ("an HTML attribute on a continuation line of a relocated quote changed",
         '- Parent.\n  - Child.\n    > Read <a\n    > href="OLD">guide</a>.\n',
         '- Parent.\n  - Child.\n    > Read <a\n    > href="NEW">guide</a>.\n', "inline_markup"),
        ("pre content after a polish:on cut changed from a tab to spaces",
         '<!-- polish:off -->\nKeep.\n<!-- polish:on --> <pre>\n\tOLD\n</pre>\n',
         '<!-- polish:off -->\nKeep.\n<!-- polish:on --> <pre>\n    OLD\n</pre>\n', "region_changed"),
        ("HTML in a quote two columns past a list item changed", '- Parent.\n    > <div>OLD</div>\n',
         '- Parent.\n    > <div>NEW</div>\n', "region_changed"),
        ("a quote two columns past a list item removed", '- Parent.\n    > Quoted words.\n',
         '- Parent.\nQuoted words.\n', "structure")]:
    rejects(name, src, cand, reason)
for name, src, cand in [
        ("emphasis rewrapped inside a relocated quote", '- Parent.\n  - Child.\n    >Read *the *"useful guide"* carefully*.\n',
         '- Parent.\n  - Child.\n    >Read *the\n    >*"useful guide"* carefully*.\n'),
        ("a quote two columns past a list item reworded", '- Parent.\n    > Quoted words.\n',
         '- Parent.\n    > Clear words.\n')]:
    accepts(name, src, cand)

# Round 3 (Round 2 review R2-M1 to R2-M8).


def seg_check(name, source, candidate, expect_reject):
    try:
        g.check_segments(source, candidate)
        report(name, not expect_reject, "candidate was accepted")
    except g.GuardReject as exc:
        report(name, expect_reject, "rejected with %s (%s)" % (exc.reason, exc.detail))


# R2-M1: a fence closes only on a fence line indented at most three columns
# past its container, and an unclosed fence ends where its container ends.
for name, src, cand, reason in [
        ("text after an overindented backtick closer edited", "```\nalpha\n    ```\nKeep text.\n```\n",
         "```\nalpha\n    ```\nEdit text.\n```\n", "region_changed"),
        ("text after an overindented tilde closer edited", "~~~\nalpha\n    ~~~\nKeep text.\n~~~\n",
         "~~~\nalpha\n    ~~~\nEdit text.\n~~~\n", "region_changed"),
        ("text after a tab-indented closer edited", "```\nalpha\n\t```\nKeep text.\n```\n",
         "```\nalpha\n\t```\nEdit text.\n```\n", "region_changed"),
        ("text after a closer four columns into a list item edited",
         "- Item.\n\n  ```\n  alpha\n      ```\n  Keep text.\n  ```\n",
         "- Item.\n\n  ```\n  alpha\n      ```\n  Edit text.\n  ```\n", "region_changed"),
        ("text after an overindented closer in a quote edited", "> ```\n> alpha\n>     ```\n> Keep text.\n> ```\n",
         "> ```\n> alpha\n>     ```\n> Edit text.\n> ```\n", "region_changed"),
        ("text after a shorter closer edited", "````\nalpha\n```\nKeep text.\n````\n",
         "````\nalpha\n```\nEdit text.\n````\n", "region_changed"),
        ("text after a closer with an info string edited", "```\nalpha\n``` x\nKeep text.\n```\n",
         "```\nalpha\n``` x\nEdit text.\n```\n", "region_changed"),
        ("an unclosed fence in a list item edited", "- ```\n  alpha\n  Keep text.\n",
         "- ```\n  alpha\n  Edit text.\n", "region_changed"),
        ("an unclosed fence in a list item edited after a blank line", "- ```\n  alpha\n\n  Keep text.\n",
         "- ```\n  alpha\n\n  Edit text.\n", "region_changed"),
        ("an unclosed fence in a quote edited after a quoted blank line", "> ```\n> alpha\n>\n> Keep text.\n",
         "> ```\n> alpha\n>\n> Edit text.\n", "region_changed"),
        ("code in a fence inside a quoted list item edited",
         "> - Item.\n>\n>   ```\n>   alpha\n>       ```\n>   Keep text.\n>   ```\n",
         "> - Item.\n>\n>   ```\n>   alpha\n>       ```\n>   Edit text.\n>   ```\n", "region_changed")]:
    rejects("R2-M1 " + name, src, cand, reason)
for name, src, cand in [
        ("text after a closer indented three columns reworded", "```\nalpha\n   ```\nKeep text.\n",
         "```\nalpha\n   ```\nEdit text.\n"),
        ("text after a closer three columns into a list item reworded",
         "- Item.\n\n  ```\n  alpha\n     ```\n  Keep text.\n",
         "- Item.\n\n  ```\n  alpha\n     ```\n  Edit text.\n"),
        ("text after a fence its quote closed reworded", "> ```\n> alpha\n\nKeep text.\n",
         "> ```\n> alpha\n\nEdit text.\n"),
        ("text after a fence its list item closed reworded", "- ```\n  alpha\nKeep text.\n",
         "- ```\n  alpha\nEdit text.\n"),
        ("a line without a marker after a quoted fence reworded", "> ```\n> alpha\nKeep text.\n> ```\n",
         "> ```\n> alpha\nEdit text.\n> ```\n")]:
    accepts("R2-M1 " + name, src, cand)

# R2-M2: code spans, autolinks and raw HTML are opaque while a link label's
# closing bracket is found.
M2_LINKS = [
    ("a bracket in an HTML attribute", 'Read [a <span title="]">label</span>](old) today.'),
    ("an opening bracket in an HTML attribute", 'Read [a <span title="[">label</span>](old) today.'),
    ("a bracket in an HTML comment of an image", "See ![a <!-- ] -->label](old) today."),
    ("an opening bracket in an HTML comment", "See [a <!-- [ -->label](old) today."),
    ("a bracket in a code span", "Read [a `]` label](old) today."),
    ("a bracket in an autolink", "Read [a <https://example.com/]> label](old) today."),
    ("a bracket in a processing instruction", "Read [a <?x ] ?>label](old) today."),
    ("a nested image with a bracket in its tag", 'Read [![a <b title="]">x</b>](img.png)](old) today.'),
]
for name, text in M2_LINKS:
    rejects("R2-M2 link target after " + name + " changed", text + "\n", text.replace("(old)", "(new)") + "\n",
            "inline_markup")
    seg_check("R2-M2 segment link target after " + name + " changed", "[[a]] " + text,
              "[[a]] " + text.replace("(old)", "(new)"), True)
rejects("R2-M2 nested image target after a bracket in its tag changed",
        'Read [![a <b title="]">x</b>](img.png)](old) today.\n',
        'Read [![a <b title="]">x</b>](other.png)](old) today.\n', "inline_markup")
accepts("R2-M2 link text around a bracket in an HTML attribute reworded",
        'Read [a <span title="]">label</span>](old) today.\n',
        'Read [the <span title="]">label</span>](old) now.\n')
seg_check("R2-M2 segment link text around a bracket in an HTML attribute reworded",
          '[[a]] Read [a <span title="]">label</span>](old) today.',
          '[[a]] Read [the <span title="]">label</span>](old) now.', False)
accepts("R2-M2 link text around a bracket in a code span reworded",
        "Read [a `]` label](old) today.\n", "Read [the `]` label](old) now.\n")

# R2-M3: prose units keep the original bytes after a quote marker that was
# moved for parsing.
for name, src in [
        ("in an ordered item", "10. Item.\n\n    > Read `one\n    > \ttwo` today.\n"),
        ("as math in an ordered item", "10. Item.\n\n    > Read $one\n    > \ttwo$ today.\n"),
        ("in a nested list item", "- Parent.\n  - Child.\n\n      > Read `one\n      > \ttwo` today.\n"),
        ("as math in a nested list item", "- Parent.\n  - Child.\n\n      > Read $one\n      > \ttwo$ today.\n"),
        ("in a list inside a quote", "> 10. Parent.\n>\n>     > Read `one\n>     > \ttwo` today.\n"),
        ("as math in a list inside a quote", "> 10. Parent.\n>\n>     > Read $one\n>     > \ttwo$ today.\n")]:
    rejects("R2-M3 a tab inside multiline code changed to equivalent spaces " + name, src,
            "\n".join(line.expandtabs(4) for line in src.split("\n")), "protected_token")
    accepts("R2-M3 prose around multiline code reworded " + name, src,
            src.replace("Read ", "Now read ").replace(" today.", " again."))

# R2-M4: blockquote boundaries and empty blockquotes are structure.
for name, src, cand in [
        ("two quotes merged into one", "> First paragraph.\n\n> Second paragraph.\n",
         "> First paragraph.\n>\n> Second paragraph.\n"),
        ("one quote split into two", "> First paragraph.\n>\n> Second paragraph.\n",
         "> First paragraph.\n\n> Second paragraph.\n"),
        ("an empty quote removed", "Read the guide.\n\n>\n", "Read the guide.\n\n"),
        ("an empty quote added", "Read the guide.\n", "Read the guide.\n\n>\n"),
        ("two nested quotes merged", "> > First.\n>\n> > Second.\n", "> > First.\n> >\n> > Second.\n"),
        ("two quotes in a list item merged", "- Item.\n\n  > First.\n\n  > Second.\n",
         "- Item.\n\n  > First.\n  >\n  > Second.\n"),
        ("a quote moved out of its list item", "- Item.\n  > First.\n  >\n  > Second.\n",
         "- Item.\n  > First.\n>\n> Second.\n"),
        ("an empty nested quote removed", "> Note.\n>\n> >\n", "> Note.\n>\n")]:
    rejects("R2-M4 " + name, src, cand, "structure")
for name, src, cand in [
        ("prose in two quotes reworded", "> First paragraph.\n\n> Second paragraph.\n",
         "> First part.\n\n> Second part.\n"),
        ("prose in one quote reworded", "> First paragraph.\n>\n> Second paragraph.\n",
         "> First part.\n>\n> Second part.\n"),
        ("prose next to an empty quote reworded", "Read the guide.\n\n>\n", "Read this guide.\n\n>\n"),
        ("a lazy line given its marker", "> First paragraph\ncontinues here.\n",
         "> First paragraph\n> continues here.\n"),
        ("prose in quotes in a list item reworded", "- Item.\n\n  > First.\n\n  > Second.\n",
         "- Item.\n\n  > The first.\n\n  > The second.\n")]:
    accepts("R2-M4 " + name, src, cand)

# R2-M5: resolved reference links and images are emphasis boundaries.
for name, src, cand in [
        ("emphasis made across a full reference label", "*first [inside*][ref] last\n\n[ref]: /url\n",
         "*first* [inside][ref] last\n\n[ref]: /url\n"),
        ("emphasis made across a full reference image label", "*first ![inside*][ref] last\n\n[ref]: /url\n",
         "*first* ![inside][ref] last\n\n[ref]: /url\n"),
        ("emphasis made across a collapsed reference", "*first [inside*][] last\n\n[inside*]: /url\n",
         "*first* [inside*][] last\n\n[inside*]: /url\n"),
        ("emphasis made across a shortcut reference", "*first [inside*] last\n\n[inside*]: /url\n",
         "*first* [inside*] last\n\n[inside*]: /url\n"),
        ("emphasis made across a reference defined in a protected region",
         "*first [inside*][ref] last\n\n<!-- polish:off -->\n[ref]: /url\n<!-- polish:on -->\n",
         "*first* [inside][ref] last\n\n<!-- polish:off -->\n[ref]: /url\n<!-- polish:on -->\n"),
        ("emphasis made across a reference defined in a quote", "*first [inside*][ref] last\n\n> [ref]: /url\n",
         "*first* [inside][ref] last\n\n> [ref]: /url\n"),
        ("an emphasis marker moved past unlinked brackets", "*a [b*] c\n", "a [b*] c*\n"),
        ("emphasis closed by a marker after a resolved full reference undone",
         "*a [t][x](* b)\n\n[x]: /u\n", "a [t][x](* b)*\n\n[x]: /u\n"),
        ("emphasis closed inside an unresolved reference label undone", "*a [t][*] b\n", "a* [t][*] b\n")]:
    rejects("R2-M5 " + name, src, cand, "inline_markup")
for name, src, cand in [
        ("a label reworded inside a full reference", "*first [inside*][ref] last\n\n[ref]: /url\n",
         "*first [within*][ref] last\n\n[ref]: /url\n"),
        ("emphasis moved around an unresolved full reference", "*first [inside*][nope] last\n",
         "*first* [inside][nope] last\n"),
        ("emphasis moved around a reference that holds a link",
         "*a [b [c](/u) d*][ref] e\n\n[ref]: /url\n", "*a* [b [c](/u) d][ref] e\n\n[ref]: /url\n")]:
    accepts("R2-M5 " + name, src, cand)
seg_check("R2-M5 segment emphasis made across a reference label", "[[a]] *first [inside*][ref] last",
          "[[a]] *first* [inside][ref] last", True)
seg_check("R2-M5 segment label reworded inside a reference", "[[a]] *first [inside*][ref] last",
          "[[a]] *first [within*][ref] last", False)

# R2-M6: hard breaks follow backslash parity and skip code and HTML.
for name, src, cand in [
        ("two spaces added after an escaped backslash", "Text with an escaped backslash\\\\\nnext line.\n",
         "Text with an escaped backslash\\\\  \nnext line.\n"),
        ("two spaces added after four backslashes", "Text\\\\\\\\\nnext line.\n",
         "Text\\\\\\\\  \nnext line.\n"),
        ("a third backslash added", "Text\\\\\nnext line.\n", "Text\\\\\\\nnext line.\n"),
        ("a break after a tag removed", "Read <b>bold</b>\\\nnext line.\n", "Read <b>bold</b>\nnext line.\n"),
        ("a break after a code span removed", "Read `code`  \nnext line.\n", "Read `code`\nnext line.\n")]:
    rejects("R2-M6 " + name, src, cand, "inline_markup")
for name, src, cand in [
        ("a backslash break changed to two spaces", "Line one\\\nline two.\n", "Line one  \nline two.\n"),
        ("prose before a two-space break reworded", "Line one  \nline two.\n", "First line  \nline two.\n"),
        ("prose before an odd backslash run reworded", "Line one\\\\\\\nline two.\n",
         "First line\\\\\\\nline two.\n"),
        ("spaces inside a tag that spans lines changed", 'Read <span  \ntitle="x">word</span> now.\n',
         'Read <span \ntitle="x">word</span> now.\n')]:
    accepts("R2-M6 " + name, src, cand)

# R2-M8: processing instructions, declarations and CDATA are raw HTML.
M8_RAW = [
    ("a processing instruction", "Read <?php echo 'old'; ?> today."),
    ("a declaration", "Read <!ELEMENT old EMPTY> today."),
    ("a CDATA section", "Read <![CDATA[one] old]]> today."),
    ("a processing instruction with emphasis markers", "Read <?x *old* ?> today."),
    ("a CDATA section with brackets", "Read <![CDATA[a [old](b)]]> today."),
]
for name, text in M8_RAW:
    rejects("R2-M8 payload of " + name + " changed", text + "\n", text.replace("old", "new") + "\n",
            "inline_markup")
    seg_check("R2-M8 segment payload of " + name + " changed", "[[a]] " + text,
              "[[a]] " + text.replace("old", "new"), True)
    accepts("R2-M8 prose around " + name + " reworded", text + "\n",
            text.replace("Read ", "Now read ").replace(" today.", " carefully.") + "\n")
for name, src in [
        ("a processing instruction over lines", "Read <?php\necho 'old';\n?> today.\n"),
        ("a CDATA section over lines", "Read <![CDATA[one\n] old]]> today.\n"),
        ("a declaration over lines", "Read <!DOCTYPE\nold> today.\n")]:
    rejects("R2-M8 payload of " + name + " changed", src, src.replace("old", "new"), "inline_markup")
rejects("R2-M8 whitespace inside a comment changed", "Read <!-- a  b --> today.\n",
        "Read <!-- a b --> today.\n", "inline_markup")

# Round 3 re-review: quote markers inside list items continue a fence, a
# paragraph or a table; closing an outer item closes the lists inside it;
# lazy lines are read past the list items they reach; empty or non-1
# ordered items do not interrupt a paragraph; trailing blank lines of an
# unclosed fence belong to it.
for name, src, cand in [
        ("a code line in a quoted fence inside a list item edited",
         "- > ~~~\n    > Keep this text.\n", "- > ~~~\n    > Edit this text.\n"),
        ("a code line in a quoted fence inside a list item, marker past four columns, edited",
         "1. > ```\n     > keep = 1\n     > ```\n", "1. > ```\n     > edit = 1\n     > ```\n"),
        ("a trailing quoted blank line of an unclosed fence removed",
         "> ~~~\n> keep\n>\n\nRead this prose.\n", "> ~~~\n> keep\n\nRead this prose.\n"),
        ("whitespace of a trailing blank line of a fence in a list item changed",
         "- ~~~\n  keep\n   \n\nRead this prose.\n", "- ~~~\n  keep\n  \n\nRead this prose.\n"),
        ("indented code after an outer item closes edited",
         "- > - Item.\n>     keep\n", "- > - Item.\n>     edit\n"),
        ("a nested list after a lazy line removed",
         "- > Read the prose.\n    code\n    > - Next item.\n", "- > Read the prose.\n    code\n"),
        ("a heading after a lazy quote line merged into the paragraph",
         "   \n- # head\n  > text two\n\t# head\n>   ~~~\n", "   \n- # head\n  > text two\n    \t# head\n>   ~~~\n"),
        ("a blank code line after an empty item that cannot interrupt changed",
         "   text two\n1. \n   ~~~\n    \n1. \n    text two\n", "   text two\n1. \n   ~~~\n     \n1. \n    text two\n"),
        ("a code line after an empty item that cannot interrupt edited",
         "   text two\n1. \n   ~~~\n    \n1. \n    text two\n", "   text two\n1. \n   ~~~\n    \n1. \n    edit two\n"),
        ("a code line after an ordered item that does not start at 1 edited",
         "Read this\n2. item\n~~~\nkeep\n~~~\n", "Read this\n2. item\n~~~\nedit\n~~~\n")]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ("prose in a quote continued by a marker inside the list item reworded",
         "- > *Read the\n    > prose.*\n", "- > *See the\n    > prose.*\n"),
        ("five emphasized references to one possible definition reworded",
         "Read [*guide*][ref] and [*guide*][ref] and [*guide*][ref] and [*guide*][ref] and [*guide*][ref].\n\n"
         "<!-- polish:off -->\n[ref]: /url\n<!-- polish:on -->\n",
         "See [*guide*][ref] and [*guide*][ref] and [*guide*][ref] and [*guide*][ref] and [*guide*][ref].\n\n"
         "<!-- polish:off -->\n[ref]: /url\n<!-- polish:on -->\n"),
        ("an empty item after a list item, not a paragraph interruption, kept",
         "- Read this.\n-\n- Then that.\n", "- Read it.\n-\n- Then that.\n"),
        ("a lazy line that continues a paragraph inside a list item reworded",
         "- > Read the\n    prose here.\n", "- > See the\n    prose here.\n")]:
    accepts("R3 " + name, src, cand)
# Round 3 second re-review: a table that starts on a list-marker line is
# inside the list item.
for name, src, cand in [
        ("a nested item after a table on a list-marker line made a sibling",
         "- | A | B |\n  |---|---|\n  - Item.\n", "- | A | B |\n  |---|---|\n- Item.\n"),
        ("the marker of an item that starts with a table changed",
         "- | A | B |\n  |---|---|\n  - Item.\n", "+ | A | B |\n  |---|---|\n  - Item.\n"),
        ("a column dropped from a table on an ordered marker line",
         "1. | Name | Note |\n   |---|---|\n   | a | Read this. |\n",
         "1. | Name | Note |\n   |---|---|\n   | a Read this. |\n")]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ("a body row of a table on a list-marker line reworded",
         "- | A | B |\n  |---|---|\n    Read this prose.\n", "- | A | B |\n  |---|---|\n    See this prose.\n"),
        ("a cell of a table on an ordered marker line reworded",
         "1. | Name | Note |\n   |---|---|\n   | a | Read this. |\n",
         "1. | Name | Note |\n   |---|---|\n   | a | See this. |\n")]:
    accepts("R3 " + name, src, cand)
# A table needs a header row and a delimiter row with the same number of
# cells, and the delimiter row must match the containers of the paragraph
# above it; a lazy header row keeps the table in that paragraph's list item.
for name, src, cand in [
        ("an empty sibling item turned into a setext underline after a mismatched delimiter row",
         "  > ~~~\na | b\n- |---|---|\n- \n", "  > ~~~\na | b\n- |---|---|\n  - \n"),
        ("a delimiter row indented into a list item, turning paragraph text into a table",
         "- item text\n| a | b |\n|---|---|\n", "- item text\n| a | b |\n  |---|---|\n"),
        ("a delimiter row moved out of a list item, turning a table into paragraph text",
         "1. Read this.\n   | c | d |\n   |---|---|\n", "1. Read this.\n   | c | d |\n  |---|---|\n"),
        ("a lazy header row of a table in a list item indented",
         "- item text\n| a | b |\n  |---|---|\n", "- item text\n  | a | b |\n  |---|---|\n"),
        ("a lazy header row of a table in a quote given its marker",
         "> quoted text\n| a | b |\n> |---|---|\n", "> quoted text\n> | a | b |\n> |---|---|\n")]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ("pipe text after a list item, not a table, reworded",
         "- item text\n| a | b |\n|---|---|\n", "- item words\n| a | b |\n|---|---|\n"),
        ("a cell of a table with a lazy header row reworded",
         "- item text\n| Read | b |\n  |---|---|\n", "- item text\n| See | b |\n  |---|---|\n"),
        ("pipe text above a delimiter row with more cells reworded",
         "Read a | b\n|---|---|---|\n", "See a | b\n|---|---|---|\n")]:
    accepts("R3 " + name, src, cand)
seg_check("R3 five emphasized references with one label in a segment reworded",
          "[[a]] Read [*guide*][ref] and [*guide*][ref] and [*guide*][ref] and [*guide*][ref] and [*guide*][ref].",
          "[[a]] See [*guide*][ref] and [*guide*][ref] and [*guide*][ref] and [*guide*][ref] and [*guide*][ref].",
          False)
rejects("R3 emphasis moved across five references with one possible label",
        "Read [*guide*][ref] and [*guide*][ref] and [*guide*][ref] and [*guide*][ref] and [*guide*][ref].\n\n"
        "<!-- polish:off -->\n[ref]: /url\n<!-- polish:on -->\n",
        "Read [*guide][ref] and [guide*][ref] and [*guide*][ref] and [*guide*][ref] and [*guide*][ref].\n\n"
        "<!-- polish:off -->\n[ref]: /url\n<!-- polish:on -->\n")
# (Front matter definitions only possibly count. Definitions inside a
# polish:off region are read as the renderers read them, as definitions.)
rejects("R3 emphasis inside references with more than four possible labels",
        "---\n[r1]: /1\n[r2]: /2\n[r3]: /3\n[r4]: /4\n[r5]: /5\n---\n\n"
        "Read [*a*][r1] [*b*][r2] [*c*][r3] [*d*][r4] [*e*][r5].\n",
        "---\n[r1]: /1\n[r2]: /2\n[r3]: /3\n[r4]: /4\n[r5]: /5\n---\n\n"
        "See [*a*][r1] [*b*][r2] [*c*][r3] [*d*][r4] [*e*][r5].\n", "inline_markup")
accepts("R3 emphasis inside references defined in a polish:off region reworded",
        "Read [*a*][r1] [*b*][r2] [*c*][r3] [*d*][r4] [*e*][r5].\n\n<!-- polish:off -->\n"
        "[r1]: /1\n[r2]: /2\n[r3]: /3\n[r4]: /4\n[r5]: /5\n<!-- polish:on -->\n",
        "See [*a*][r1] [*b*][r2] [*c*][r3] [*d*][r4] [*e*][r5].\n\n<!-- polish:off -->\n"
        "[r1]: /1\n[r2]: /2\n[r3]: /3\n[r4]: /4\n[r5]: /5\n<!-- polish:on -->\n")

# cmark-gfm block rules found with a cmark-gfm reference fuzz: an HTML block
# ends where its blockquote or list item ends; raw text inside a list item is
# read from the item's content column; a footnote definition holds lines
# indented four columns and lazy lines that start no block; the lines after a
# reference definition continue its paragraph; a table needs one try per
# paragraph, and a header row or delimiter row may lack pipes or be indented.
# Where markdown-it reads a table differently, the change is rejected too.
for name, src, cand in [
        ('a blank code line of a fence after an HTML block that its list item ends changed',
         '  - > Alpha prose.\n    </div>\n~~~\n    \n',
         '  - > Alpha prose.\n    </div>\n~~~\n\n'),
        ('an item marker moved so an ordered item joins a raw HTML block',
         '  -\n    <pre>\n    ===\n  2. Alpha prose.\n',
         '-\n    <pre>\n    ===\n  2. Alpha prose.\n'),
        ('an item marker moved so a paragraph joins an HTML block',
         '  # Title\n- Item prose.\n    </div>\n  *Read [inside*][ref]\n',
         '  # Title\n  - Item prose.\n    </div>\n  *Read [inside*][ref]\n'),
        ('an empty item marker indented, shifting the indented code inside it',
         '-\n        codewords\n    *Read [inside*][ref]\n',
         ' -\n        codewords\n    *Read [inside*][ref]\n'),
        ('an empty item marker indented, shifting the raw HTML inside it',
         '-\n    <pre>\n    [t][ref] prose\n',
         '  -\n    <pre>\n    [t][ref] prose\n'),
        ('a code line of a fence that ends a footnote definition indented',
         '[^1]: note\n  ```\n*Read [inside*][ref]\n  [t][ref] prose\n',
         '[^1]: note\n  ```\n*Read [inside*][ref]\n     [t][ref] prose\n'),
        ('a line of an HTML block after a footnote definition indented',
         '[^1]: note\n  </script>\n===\n      codewords\n  <span>\n  Read prose.\n',
         '[^1]: note\n  </script>\n===\n        codewords\n  <span>\n  Read prose.\n'),
        ('a code line of a fence inside a footnote after lazy lines edited',
         '  > Read prose.\n[^1]: note\n===\n*Read [inside*][ref]\n    ~~~\n        codewords\n',
         '  > Read prose.\n[^1]: note\n===\n*Read [inside*][ref]\n    ~~~\n        codeother\n'),
        ('a blank code line at the end of a fence inside a footnote changed',
         '  [^1]: note\n    ~~~\n    \n  # Read prose.\n',
         '  [^1]: note\n    ~~~\n      \n  # Read prose.\n'),
        ('a paragraph after an indented line under a definition turned into code',
         '[ref]: /url\n    Read prose.\n    ===\n-\n    Beta prose.\n*Read [inside*][ref]\n---\n',
         '[ref]: /url\n    Read prose.\n    ===\n-\n    Beta prose.\n    *Read [inside*][ref]\n---\n'),
        ('an item after a definition-like lazy line indented into the first item',
         '1. Alpha.\n[ref]: /url\n2. Beta.\n',
         '1. Alpha.\n[ref]: /url\n   2. Beta.\n'),
        ('code after an inline tag that cannot interrupt a paragraph edited',
         'Intro.\n<span>\n```\n\nKeep code.\n```\n',
         'Intro.\n<span>\n```\n\nKeep text.\n```\n'),
        ('a line of an HTML block opened by a closing script tag edited',
         'Text.\n\n</script>\nraw line\n',
         'Text.\n\n</script>\nraw text\n'),
        ('a line of an HTML block that a lazy tag line opens after a quote edited',
         '> Quoted text.\n<span>\nraw line\n',
         '> Quoted text.\n<span>\nraw text\n'),
        ('a line of an HTML block opened by a source tag edited',
         'Intro.\n<source src="a">\nraw line\n',
         'Intro.\n<source src="a">\nraw text\n'),
        ('an HTML line in a list item kept open by a whitespace line indented',
         '-\n  \n  *Read [inside*][ref]\n    <div>\n    -\n',
         '-\n  \n  *Read [inside*][ref]\n        <div>\n    -\n'),
        ('a code line after an empty item and a whitespace line edited',
         '-\t\n\t\n    text two\n',
         '-\t\n\t\n    edit two\n'),
        ('a header row indented after a failed delimiter row, making a table',
         '  ===\n  |---|---|\n  |---|---|\n',
         '  ===\n     |---|---|\n  |---|---|\n'),
        ('the delimiter row of a one-column table removed',
         'Name\n:---\nRead this.\n',
         'Name\nRead this.\n'),
        ('code after a table whose header row is indented edited',
         '===\n    |---|---|\n|---|---|\n    Beta prose.\n        codewords\n',
         '===\n    |---|---|\n|---|---|\n    Beta prose.\n        codeother\n'),
        ('a header row indented four columns',
         '  a | b\n    | c | d |\na | b\n|---|---|\n',
         '  a | b\n    | c | d |\n    a | b\n|---|---|\n'),
        ('a row of a table that only markdown-it reads moved out of it',
         'text one\n   |---|---|\n|---|---|\n| a | b |\n  | c | d |\n',
         'text one\n   |---|---|\n|---|---|\n    | a | b |\n  | c | d |\n'),
        ('a pipe added to the header row of a pipe-less table',
         'Name\n:---\n',
         'Name |\n:---\n'),
        ('a quote after an empty quote in a list item turned into paragraph text',
         '\n  >\n1. Read prose.\n    >\n[ref]: /url\n> Read prose.\n',
         '\n  >\n1. Read prose.\n    >\n[ref]: /url\n     > Read prose.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('a paragraph after a definition reworded',
         '[ref]: /url\nRead this.\n',
         '[ref]: /url\nSee this.\n'),
        ('a paragraph after a raw HTML block in a list item reworded',
         '- Item.\n\n  <pre>\n\n  x\n\nRead more.\n',
         '- Item.\n\n  <pre>\n\n  x\n\nSee more.\n'),
        ('a cell of a one-column table reworded',
         'Name\n:---\nRead this.\n',
         'Name\n:---\nSee this.\n'),
        ('text after a search tag, which does not start an HTML block, reworded',
         'Intro.\n<search>\nRead this.\n',
         'Intro.\n<search>\nSee this.\n'),
        ('a paragraph after an empty item and a whitespace line reworded',
         '-\n  \n  Read this.\n',
         '-\n  \n  See this.\n'),
        ('an underline below a definition read as text, reworded around',
         '[foo]: /url\n===\nRead this.\n',
         '[foo]: /url\n===\nSee this.\n'),
        ('emphasis moved after text that only looks like a definition',
         'Intro.\n[ref]: /url\n\n*first [inside*][ref] last\n',
         'Intro.\n[ref]: /url\n\n*first [inside][ref]* last\n')]:
    accepts("R3 " + name, src, cand)

# Final re-review of e62269d: an underline below an unreadable definition makes a
# heading; a quote ends after an HTML block line; a table header found inside a
# paragraph is read as one even when it looks like a list item; a footnote's
# lazy lines may have fewer quote markers, need an open paragraph, and stop where
# a quote marker leaves the enclosing list item.
for name, src, cand in [
        ('code after a heading whose text only starts like a definition edited',
         '[ref]:\n===\n    codewords\n',
         '[ref]:\n===\n    codeother\n'),
        ('paragraph text after an HTML block in a quoted list item turned into a quote',
         '- Item.\n    > <div></div>\nOutside.\n    > Next.\n',
         '- Item.\n    > <div></div>\nOutside.\n  > Next.\n'),
        ('code after a one-column table whose header looks like an ordered item edited',
         'Intro.\n2. Header.\n:---\n    codewords\n',
         'Intro.\n2. Header.\n:---\n    codeother\n'),
        ("a list after a footnote's lazy line outside its quote absorbed into the footnote",
         'See[^1].\n\n> [^1]: note\nTail.\n2. Item.\n',
         'See[^1].\n\n> [^1]: note\nTail.\n      2. Item.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a heading inside a footnote reworded',
         'See[^1].\n\n[^1]: note\n    # Heading\nRead prose.\n',
         'See[^1].\n\n[^1]: note\n    # Heading\nSee prose.\n'),
        ('prose after a closed fence inside a footnote reworded',
         'See[^1].\n\n[^1]: note\n    ```\n    code\n    ```\nRead prose.\n',
         'See[^1].\n\n[^1]: note\n    ```\n    code\n    ```\nSee prose.\n'),
        ('a quote outside the list that holds a quoted footnote reworded',
         '- Item.\n\n  > [^1]: note\n> Read prose.\n',
         '- Item.\n\n  > [^1]: note\n> See prose.\n')]:
    accepts("R3 " + name, src, cand)

# cmark-gfm keeps the leading whitespace of a lazy line: a lazy header row that
# starts with whitespace and a pipe has an empty first cell there.
for name, src, cand in [
        ("a delimiter row moved out of an item under a lazy header with a leading space",
         '2. Header.\n  | a |\n    |---|---|\n  <img src="x">\n', '2. Header.\n  | a |\n|---|---|\n  <img src="x">\n'),
        ("the leading space of a lazy header row removed",
         "- x\n | a |\n  |---|---|\n", "- x\n| a |\n  |---|---|\n"),
        ("the leading space of a lazy header row in a quote removed, making a table",
         "> x\n | a | b\n> |---|---|\n", "> x\n| a | b\n> |---|---|\n")]:
    rejects("R3 " + name, src, cand)
accepts("R3 a lazy header row with a leading space reworded",
        "- x\n | Read |\n  |---|---|\n", "- x\n | See |\n  |---|---|\n")

rejects("R3 a delimiter row indented under a lazy header that only markdown-it reads as a table",
        "  - a | b\n  - | a | b |\n  | a | b |\n  |---|---|\n  - | text two |\na | b\n",
        "  - a | b\n  - | a | b |\n  | a | b |\n    |---|---|\n  - | text two |\na | b\n")

# Re-review of a6e43fe: a footnote definition's extent comes from parsing its
# content (lazy lines need an open paragraph there; only an empty line, or one
# indented four columns, continues it); quote relocation stops at the first
# line without a marker; destinations may hold balanced parentheses and a
# backslash before a space ends them; table cells split at pipes inside
# backticks, as in GFM.
for name, src, cand in [
        ('a destination with nested parentheses above an underline changed',
         '[ref]: a(b(c)d)e\n===\n\n[ref]\n',
         '[ref]: a(b(x)d)e\n===\n\n[ref]\n'),
        ('a lazy line in a list inside a footnote reworded (footnotes are kept byte for byte)',
         'See[^1].\n\n[^1]: - # Heading\n        Body.\nRead prose.\n',
         'See[^1].\n\n[^1]: - # Heading\n        Body.\nSee prose.\n'),
        ('paragraph text after an HTML block inside a quoted list item turned into a quote',
         '- Item.\n    > <div></div>\n    > Body.\nOutside.\n    > Next.\n',
         '- Item.\n    > <div></div>\n    > Body.\nOutside.\n  > Next.\n'),
        ('code after a heading whose definition-like line has a backslash before a space edited',
         '[ref]: /a\\ b\n===\n    codewords\n',
         '[ref]: /a\\ b\n===\n    codeother\n'),
        ('a lazy line after a fence opened and closed in a footnote reworded',
         'See[^1].\n\n[^1]: ```\n    ```\n    Body.\nRead prose.\n',
         'See[^1].\n\n[^1]: ```\n    ```\n    Body.\nSee prose.\n'),
        ('code after a table whose header has a pipe inside backticks edited',
         'Intro.\n2. `x|y`\n|---|---|\n    codewords\n',
         'Intro.\n2. `x|y`\n|---|---|\n    codeother\n'),
        ('code after a lazy table header with a pipe inside backticks in a quote edited',
         '> Intro.\n`x|y`\n> |---|---|\n>     codewords\n',
         '> Intro.\n`x|y`\n> |---|---|\n>     codeother\n'),
        ('a whitespace line that ends a footnote inside a fence changed',
         'See[^1].\n\n[^1]: note\n    ```\n    code\n\n    more\n',
         'See[^1].\n\n[^1]: note\n    ```\n    code\n\n    other\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a setext heading in a quoted footnote reworded',
         'See[^1].\n\n> [^1]: Header\n>     ===\nRead prose.\n',
         'See[^1].\n\n> [^1]: Header\n>     ===\nSee prose.\n'),
        ('prose after a table in a quoted footnote reworded',
         'See[^1].\n\n> [^1]: Name\n>     :---\nRead prose.\n',
         'See[^1].\n\n> [^1]: Name\n>     :---\nSee prose.\n'),
        ('prose after an unclosed fence in a quoted footnote reworded',
         'See[^1].\n\n> [^1]: ```\n>     Body.\nRead prose.\n',
         'See[^1].\n\n> [^1]: ```\n>     Body.\nSee prose.\n'),
        ('prose after closed raw HTML in a quoted footnote reworded',
         'See[^1].\n\n> [^1]: <pre>\n>     words\n>     </pre>\nRead prose.\n',
         'See[^1].\n\n> [^1]: <pre>\n>     words\n>     </pre>\nSee prose.\n'),
        ('prose after a quoted footnote that a marker-only line ends reworded',
         'See[^1].\n\n> [^1]: note\n>\n>     Body.\nRead prose.\n',
         'See[^1].\n\n> [^1]: note\n>\n>     Body.\nSee prose.\n'),
        ('a cell with a pipe inside backticks reworded',
         '| a | `x|y` |\n|---|---|---|\n| Read | b | c |\n',
         '| a | `x|y` |\n|---|---|---|\n| See | b | c |\n')]:
    accepts("R3 " + name, src, cand)

rejects("R3 an HTML line after a nested footnote's lazy line indented into it",
        '  [^1]: note\n    1. Alpha prose.\n    [^1]: note\n  Alpha prose.\n  <img src="x">\n',
        '  [^1]: note\n    1. Alpha prose.\n    [^1]: note\n  Alpha prose.\n        <img src="x">\n')

# A footnote definition reads its content with a bounded number of inner
# parses: plain text lines need none, and past the bound the definition keeps
# lazy lines and trailing blank lines byte for byte.
LONG_NOTE = "See[^1].\n\n[^1]: x\n" + "    a\nb\n" * 3000
accepts("R3 a long footnote with alternating lazy lines unchanged", LONG_NOTE, LONG_NOTE)
rejects("R3 the last lazy line of a long footnote reworded",
        LONG_NOTE, LONG_NOTE[:-2] + "c\n")
MANY_PARSES = "See[^1].\n\n[^1]: x\n" + "    - a\nb\n" * 60
rejects("R3 trailing blank lines of a footnote past the parse bound changed",
        MANY_PARSES + "    ```\n    code\n\n\nRead prose.\n",
        MANY_PARSES + "    ```\n    code\n\nRead prose.\n")
rejects("R3 a lazy line of a footnote past the parse bound reworded",
        MANY_PARSES + "    # Head\nRead prose.\n",
        MANY_PARSES + "    # Head\nSee prose.\n")
for name, src, cand in [
        ('prose after a setext underline that follows plain footnote lines reworded',
         'See[^1].\n\n[^1]: Title\n    more\n    ===\nRead prose.\n',
         'See[^1].\n\n[^1]: Title\n    more\n    ===\nSee prose.\n'),
        ('prose after a fence that follows plain footnote lines reworded',
         'See[^1].\n\n[^1]: Title\n    more\n    ```\n    code\n    ```\nRead prose.\n',
         'See[^1].\n\n[^1]: Title\n    more\n    ```\n    code\n    ```\nSee prose.\n')]:
    accepts("R3 " + name, src, cand)
rejects("R3 a lazy line after plain footnote lines reworded",
        'See[^1].\n\n[^1]: Title\n    more\n    words\nRead prose.\n',
        'See[^1].\n\n[^1]: Title\n    more\n    words\nSee prose.\n')

# Re-review of e769075: destinations follow cmark-gfm (32 levels of
# parentheses, ASCII whitespace; a line that can only be text is text), a
# lazy line that would read differently inside a footnote's content makes the
# definition unread, blank lines keep their whitespace in the content, a fence
# records its closing fence, and one budget bounds nested content parses.
for name, src, cand in [
        ('a destination nested nine parentheses deep changed',
         '[ref]: a(((((((((word)))))))))\n===\n\n[ref]\n',
         '[ref]: a(((((((((other)))))))))\n===\n\n[ref]\n'),
        ('a destination nested 32 parentheses deep changed',
         '[ref]: a((((((((((((((((((((((((((((((((word))))))))))))))))))))))))))))))))\n\n[ref]\n',
         '[ref]: a((((((((((((((((((((((((((((((((other))))))))))))))))))))))))))))))))\n\n[ref]\n'),
        ('a lazy line after a lazy setext-like line in a footnote reworded',
         'See[^1].\n\n[^1]: Body.\n===\n        # Head\nRead prose.\n',
         'See[^1].\n\n[^1]: Body.\n===\n        # Head\nSee prose.\n'),
        ('a lazy line after a lazy delimiter-like line in a footnote reworded',
         'See[^1].\n\n[^1]: Body.\n|---|\n        # Head\nRead prose.\n',
         'See[^1].\n\n[^1]: Body.\n|---|\n        # Head\nSee prose.\n'),
        ('a lazy line after an indented lazy fence-like line in a quoted footnote reworded',
         'See[^1].\n\n> [^1]: Body.\n    ```\n>     more\nRead prose.\n',
         'See[^1].\n\n> [^1]: Body.\n    ```\n>     more\nSee prose.\n'),
        ('a lazy line after a lazy header row with leading whitespace in a footnote reworded',
         'See[^1].\n\n[^1]: Body.\n | a |\n    |---|\nRead prose.\n',
         'See[^1].\n\n[^1]: Body.\n | a |\n    |---|\nSee prose.\n'),
        ('a lazy line after a whitespace line that keeps an empty item open in a footnote reworded',
         'See[^1].\n\n[^1]: -\n      \n      Body.\n    ===\nRead prose.\n',
         'See[^1].\n\n[^1]: -\n      \n      Body.\n    ===\nSee prose.\n'),
        ('blank lines after an over-indented closing fence in a footnote changed',
         'See[^1].\n\n[^1]: ```\n        ```\n\n\nRead prose.\n',
         'See[^1].\n\n[^1]: ```\n        ```\n\nRead prose.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a definition-like line with a backslash before a space reworded',
         '[ref]: /a\\ b\nRead prose.\n',
         '[ref]: /a\\ b\nSee prose.\n'),
        ('prose after a definition-like line nested 33 parentheses deep reworded',
         '[ref]: a(((((((((((((((((((((((((((((((((w)))))))))))))))))))))))))))))))))\nRead prose.\n',
         '[ref]: a(((((((((((((((((((((((((((((((((w)))))))))))))))))))))))))))))))))\nSee prose.\n'),
        ('prose after a definition-like line with an unbalanced parenthesis reworded',
         '[ref]: /a)b\nRead prose.\n',
         '[ref]: /a)b\nSee prose.\n'),
        ('prose after a whitespace line that ends a nested footnote reworded',
         'See[^1][^2].\n\n[^1]: [^2]: note\n    \n        Body.\nRead prose.\n',
         'See[^1][^2].\n\n[^1]: [^2]: note\n    \n        Body.\nSee prose.\n'),
        ('prose after a closed fence in a footnote reworded',
         'See[^1].\n\n[^1]: ```\n    ```\n\nRead prose.\n',
         'See[^1].\n\n[^1]: ```\n    ```\n\nSee prose.\n')]:
    accepts("R3 " + name, src, cand)
accepts("R3 prose after a lazy quote-marker-like line ends a quoted nested footnote reworded",
        "See[^1][^2].\n\n> [^1]: [^2]: note\n    >\n    [ref]: /url\n>     ---\nRead prose.\n",
        "See[^1][^2].\n\n> [^1]: [^2]: note\n    >\n    [ref]: /url\n>     ---\nSee prose.\n")
NESTED = "[^z]: x\n"
for depth in range(20):
    NESTED = ("[^n%d]: x\n" % depth + "".join("    " + line + "\n" for line in NESTED.splitlines())
              + "lazy\n    - a\nlazy\n")
CHAIN = "[^1]: " * 3000 + "note\n"
for name, doc in (("twenty nested footnotes", NESTED), ("a chain of 3000 footnote labels", CHAIN)):
    started = time.time()
    accepts("R3 " + name + " unchanged", doc, doc)
    report("R3 " + name + " checked within two seconds", time.time() - started < 2.0,
           "%.2fs" % (time.time() - started))

# Found by a footnote-content fuzz against cmark-gfm: an empty item stays open
# only while every blank line after it reaches its content column, and a
# definition above a table header is text in cmark-gfm (markdown-it reads it).
for name, src, cand in [
        ('a blank line that closes an empty item added after a whitespace line',
         '>\n-\n    \n  \n    Alpha body.\nTail.\n          Beta body.\n',
         '>\n-\n    \n  \n \n    Alpha body.\nTail.\n          Beta body.\n'),
        ('a second whitespace line after an empty item narrowed',
         '-\n  \n  \n  Alpha body.\n',
         '-\n  \n \n  Alpha body.\n'),
        ('a blank line added between a definition and a table header',
         '[ref]: /url\nTail.\n  |---|\n',
         '[ref]: /url\n\nTail.\n  |---|\n'),
        ('a blank line removed between a definition and a table header',
         '[ref]: /url\n\nTail.\n|---|\n',
         '[ref]: /url\nTail.\n|---|\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose in an empty item kept open by whitespace lines reworded',
         '-\n  \n  \n  Alpha body.\n',
         '-\n  \n  \n  Delta body.\n'),
        ('a header cell below a definition reworded',
         '[ref]: /url\nRead prose.\n|---|\n',
         '[ref]: /url\nSee prose.\n|---|\n')]:
    accepts("R3 " + name, src, cand)

# Re-review of 61a5db8: destinations read with cmark-gfm's scanner (open
# parentheses may stay open, a title may end in a backslash), lazy lines enter
# footnote content as plain stand-ins, an unread definition runs to the end of
# the text, an item that held only definitions closes as in cmark-gfm, and a
# long run of word characters is one protected word.
for name, src, cand in [
        ('a destination with an unbalanced parenthesis changed',
         '[ref]: a(word\n\n[ref]\n',
         '[ref]: a(other\n\n[ref]\n'),
        ('a title ending in a backslash changed',
         '[ref]: /u (\\)\n\n[ref]\n',
         '[ref]: /u (x\\)\n\n[ref]\n'),
        ('code after a heading that follows a footnote with a lazy setext-like line edited',
         'See[^1].\n\n[^1]: Body.\n===\n    ```\nHeading\n-\n    Alpha body.\n',
         'See[^1].\n\n[^1]: Body.\n===\n    ```\nHeading\n-\n    Delta body.\n'),
        ('code after a footnote that may hold a definition and has a lazy block-like line edited',
         'See[^1].\n\n[^1]: [ref]:\n    <div>\nHeading\n-\n    Alpha body.\n',
         'See[^1].\n\n[^1]: [ref]:\n    <div>\nHeading\n-\n    Delta body.\n'),
        ('code after a list item that holds only a definition edited',
         '- [ref]: /url\n\n\n    Alpha body.\n',
         '- [ref]: /url\n\n\n    Delta body.\n'),
        ('the blank line after an item that holds only a definition widened',
         '- [ref]: /url\n\n\n    Alpha body.\n',
         '- [ref]: /url\n\n  \n    Alpha body.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a footnote with a lazy delimiter-like line and a heading reworded',
         'See[^1].\n\n[^1]: Body.\n:---\n    ===\nAlpha body.\n',
         'See[^1].\n\n[^1]: Body.\n:---\n    ===\nDelta body.\n'),
        ('prose in a list item after a definition and one blank line reworded',
         '- [ref]: /url\n\n  Alpha body.\n',
         '- [ref]: /url\n\n  Delta body.\n'),
        ('prose in a list item after a definition and whitespace lines reworded',
         '- [ref]: /url\n\n  \n  Alpha body.\n',
         '- [ref]: /url\n\n  \n  Delta body.\n'),
        ('a long word with a closing parenthesis left unchanged around a reworded sentence',
         '[ref]: ' + 'a' * 20000 + ')word\nRead prose.\n',
         '[ref]: ' + 'a' * 20000 + ')word\nSee prose.\n')]:
    accepts("R3 " + name, src, cand)
for name, doc in (("a 20000-character word", "Read " + "a" * 20000 + ")word now.\n"),
                  ("runs of 47 word characters", ("a:" * 23 + "a ") * 3000 + "\n")):
    started = time.time()
    accepts("R3 " + name + " unchanged", doc, doc)
    report("R3 " + name + " checked within two seconds", time.time() - started < 2.0,
           "%.2fs" % (time.time() - started))

# Re-review of 556b052: a long run carries the token syntax next to it and keeps
# its hyphens, hyphenated prose under 80 characters stays editable, a title
# fails in linear time, and a label of only whitespace is no label.
for name, src, cand in [
        ('the parentheses after a long function name removed',
         'Call load_application_configuration_from_environment_variables() before starting.\n',
         'Call load_application_configuration_from_environment_variables before starting.\n'),
        ('the parentheses after a function name of 80 characters removed',
         'Call load_application_configuration_from_environment_variables_and_settings_files_now() before starting.\n',
         'Call load_application_configuration_from_environment_variables_and_settings_files_now before starting.\n'),
        ('the dollar sign before a long variable removed',
         'Set $A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_B first.\n',
         'Set A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_A_B first.\n'),
        ('the unit after a long number changed',
         'Wait 111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111 ms here.\n',
         'Wait 111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111 s here.\n'),
        ('the trailing hyphen of a long flag removed',
         'Pass --a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a- now.\n',
         'Pass --a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a-a now.\n'),
        ('code after a heading whose definition-like line has a whitespace label edited',
         '[ ]: a(word\n===\n    Alpha body.\n',
         '[ ]: a(word\n===\n    Delta body.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('long hyphenated prose reworded',
         'Follow an-easy-to-follow-step-by-step-troubleshooting-guide today.\n',
         'Follow a-simple-step-by-step-troubleshooting-guide today.\n'),
        ('prose after a definition-like line with text after its title reworded',
         '[ref]: a(word "title" extra\nRead prose.\n',
         '[ref]: a(word "title" extra\nSee prose.\n')]:
    accepts("R3 " + name, src, cand)
for name, doc in (("a title of 5000 backslashes that never closes", '[ref]: /u "' + "\\" * 5000 + "x\n"),
                  ("runs of 79 letters", ("a" * 79 + " ") * 500 + "\n")):
    started = time.time()
    accepts("R3 " + name + " unchanged", doc, doc)
    report("R3 " + name + " checked within three seconds", time.time() - started < 3.0,
           "%.2fs" % (time.time() - started))

# Re-review of e134e90: labels are at most 1000 UTF-8 bytes and only ASCII
# whitespace counts as whitespace in them, long runs are found after emphasis
# underscores are hidden, underscore emphasis may hold intraword underscores,
# scoped calls keep their parentheses, and a one-letter unit may follow a space.
for name, src, cand in [
        ('a destination below a label of 1000 bytes changed',
         '[' + 'a' * 1000 + ']: alpha\n\n[link][' + 'a' * 1000 + ']\n',
         '[' + 'a' * 1000 + ']: delta\n\n[link][' + 'a' * 1000 + ']\n'),
        ('code after a heading whose label of escapes is too long edited',
         '[' + '\\!' * 501 + ']: a(word\n===\n    Alpha body.\n',
         '[' + '\\!' * 501 + ']: a(word\n===\n    Delta body.\n'),
        ('code after a heading whose label of wide characters is too long edited',
         '[' + '\u00e9' * 501 + ']: a(word\n===\n    Alpha body.\n',
         '[' + '\u00e9' * 501 + ']: a(word\n===\n    Delta body.\n'),
        ('a destination below a label of a no-break space changed',
         '[\u00a0]: alpha\n\n[link][\u00a0]\n',
         '[\u00a0]: delta\n\n[link][\u00a0]\n'),
        ('emphasis around a long word lost',
         'Read _' + 'a' * 80 + '_ \u00e9 here.\n',
         'Read _' + 'a' * 80 + '_\u00e9 here.\n'),
        ('the parentheses after a scoped call removed',
         'Call config::load_application_configuration_from_environment_variables() now.\n',
         'Call config::load_application_configuration_from_environment_variables now.\n'),
        ('a spaced single-letter unit changed',
         'Wait 30 s now.\n',
         'Wait 30 h now.\n'),
        ('a spaced percent sign removed',
         'Use 30 % of it.\n',
         'Use 30 of it.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('the space inside a spaced unit removed',
         'Wait 30 s now.\n',
         'Wait 30s now.\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of b196e95: a lone underscore is not paired across words, labels
# may hold a vertical tab or form feed, reference uses follow the same label
# rules as definitions, single and double tildes are read both the cmark-gfm
# way and the markdown-it way, dunder names keep their strong emphasis, and
# scoped names with dots and units across spaces or a line break are whole.
for name, src, cand in [
        ('an identifier after a lone underscore changed',
         'Use _private and _emphasis_ here.\n',
         'Use _public and _emphasis_ here.\n'),
        ('a path with an underscore changed',
         'See /_private and _word_ here.\n',
         'See /_public and _word_ here.\n'),
        ('a destination below a label of a vertical tab changed',
         '[\x0b]: alpha\n\n[link][\x0b]\n',
         '[\x0b]: delta\n\n[link][\x0b]\n'),
        ('a destination below a label of a form feed changed',
         '[\x0c]: alpha\n\n[link][\x0c]\n',
         '[\x0c]: delta\n\n[link][\x0c]\n'),
        ('emphasis moved into a reference link with a label of 1000 bytes',
         '[*a][' + 'a' * 1000 + '] b*\n\n[' + 'a' * 1000 + ']: /u\n',
         '[*a*][' + 'a' * 1000 + '] b\n\n[' + 'a' * 1000 + ']: /u\n'),
        ('emphasis added after a reference link with a no-break space label',
         '[*a][\u00a0] b**\n\n[\u00a0]: /u\n',
         '[*a][\u00a0] *b*\n\n[\u00a0]: /u\n'),
        ('single-tilde strikethrough lost',
         'Read ~word~ now.\n',
         'Read ~ word ~ now.\n'),
        ('single-tilde strikethrough turned into a double one',
         'Read ~word~ now.\n',
         'Read ~~word~~ now.\n'),
        ('emphasis before a tilde after a long word lost',
         'Read _' + 'a' * 80 + '_~ here.\n',
         'Read _' + 'a' * 80 + '_~here.\n'),
        ('emphasis that starts before a tilde lost (cmark-gfm reading)',
         'Read x*~a* now.\n',
         'Read x*~ a* now.\n'),
        ('strikethrough inside a run of three tildes lost (markdown-it reading)',
         'Read ~~~word~~~ now.\n',
         'Read ~~~ word~~~ now.\n'),
        ('strong emphasis of a dunder name lost',
         'Read __init__ \u00e9 here.\n',
         'Read __init__\u00e9 here.\n'),
        ('the dot in a scoped member call removed',
         'Call config::module.run() now.\n',
         'Call config::module run() now.\n'),
        ('strikethrough after a run of 101 tildes lost (cmark-gfm reading)',
         'Read ' + '~' * 101 + 'word~ now.\n',
         'Read ' + '~' * 101 + 'word ~ now.\n'),
        ('emphasis closed by the underscore of an identifier lost',
         'Read ~~__*(word_ now.\n',
         'Read~~__*(word_ now.\n'),
        ('emphasis closed by an underscore inside a bare URL lost',
         'Read ~__https://x.com/~utextword\\~_ now.\n',
         'Read~__https://x.com/~utextword\\~_ now.\n'),
        ('a unit after two spaces changed',
         'Wait 30  s now.\n',
         'Wait 30  h now.\n'),
        ('a unit after a line break changed',
         'Wait 30\ns now.\n',
         'Wait 30\nh now.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose in emphasis after a lone underscore reworded',
         'Keep _private and _clear wording_ here.\n',
         'Keep _private and _plain wording_ here.\n'),
        ('the text of a reference link with a no-break space label reworded',
         '[Read the manual][\u00a0]\n\n[\u00a0]: /u\n',
         '[Consult the manual][\u00a0]\n\n[\u00a0]: /u\n'),
        ('prose around single-tilde strikethrough reworded',
         'Read ~word~ now.\n',
         'See ~word~ today.\n'),
        ('prose around strikethrough and emphasis reworded',
         'Keep ~~old~~ *new* text.\n',
         'Keep ~~old~~ *new* words.\n'),
        ('prose around an identifier and emphasis reworded',
         'Use _private and _emphasis_ here.\n',
         'Pass _private with _emphasis_ now.\n'),
        ('prose around a dunder name reworded',
         'Read __init__ first.\n',
         'Open __init__ first.\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of 8ab2ac4: references resolve the markdown-it way too, deep
# strikethrough nesting is described without recursion, member names after
# a call are part of it, and a unit may follow a no-break or thin space.
for name, src, cand in [
        ('emphasis lost where markdown-it does not resolve a no-break space label',
         'Read [*a][\u00a0] b* now.\n\n[\u00a0]: /u\n',
         'Read [*a][\u00a0] *b now.\n\n[\u00a0]: /u\n'),
        ('emphasis lost where markdown-it does not resolve a vertical tab label',
         'Read [*a][\x0b] b* now.\n\n[\x0b]: /u\n',
         'Read [*a][\x0b] *b now.\n\n[\x0b]: /u\n'),
        ('emphasis lost where only markdown-it matches a label with a no-break space',
         'Read [*a][a b] b* now.\n\n[a\u00a0b]: /u\n',
         'Read [*a][a b] *b now.\n\n[a\u00a0b]: /u\n'),
        ('emphasis lost where only markdown-it takes a label over 1000 bytes',
         'Read [*a][' + 'a' * 1001 + '] b* now.\n\n[' + 'a' * 1001 + ']: /u\n',
         'Read [*a][' + 'a' * 1001 + '] *b now.\n\n[' + 'a' * 1001 + ']: /u\n'),
        ('the member name after a scoped call changed',
         'Call config::module.run().field now.\n',
         'Call config::module.run().other now.\n'),
        ('the member name after a call changed',
         'Call obj.load().parse().value now.\n',
         'Call obj.load().parse().other now.\n'),
        ('a unit after a no-break space changed',
         'Wait 30\u00a0ms now.\n',
         'Wait 30\u00a0ns now.\n'),
        ('a unit after a narrow no-break space changed',
         'Wait 30\u202fms now.\n',
         'Wait 30\u202fns now.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose around 4096 tildes on each side of a word reworded',
         'Read ' + '~' * 4096 + 'word' + '~' * 4096 + ' now.\n',
         'See ' + '~' * 4096 + 'word' + '~' * 4096 + ' now.\n'),
        ('prose around deeply nested strikethrough reworded',
         'Read ' + '~~a ' * 3000 + 'b' + ' a~~' * 3000 + ' now.\n',
         'See ' + '~~a ' * 3000 + 'b' + ' a~~' * 3000 + ' now.\n'),
        ('the space before a unit turned into a no-break space',
         'Wait 30 ms now.\n',
         'Wait 30\u00a0ms now.\n'),
        ('prose after a call ending a sentence reworded',
         'Call run(). Then stop.\n',
         'Call run(). Then halt.\n')]:
    accepts("R3 " + name, src, cand)
started = time.time()
accepts("R3 a paragraph of 16000 reference links unchanged",
        "[x][a b] and [y][c] " * 8000 + "\n\n[a b]: /u\n[c]: /v\n",
        "[x][a b] and [y][c] " * 8000 + "\n\n[a b]: /u\n[c]: /v\n")
report("R3 a paragraph of 16000 reference links checked within three seconds",
       time.time() - started < 3.0, "%.2fs" % (time.time() - started))


# Own probes on d6af219: block readings that only markdown-it has. An
# underline right below definitions is text to cmark-gfm but a thematic
# break or heading to markdown-it, and a definition with a label over 1000
# bytes is text to cmark-gfm but a definition to markdown-it.
for name, src, cand in [
        ('the underline below a definition changed from = to -',
         '[a]: /u\n===\n',
         '[a]: /u\n---\n'),
        ('the underline below a no-break space definition changed',
         '[\u00a0]: /u\n===\n',
         '[\u00a0]: /u\n---\n'),
        ('prose below a definition turned into an underline',
         '[a]: /u\nRead prose.\n',
         '[a]: /u\n---\n'),
        ('the destination of a definition only markdown-it reads changed',
         '[' + 'a' * 1001 + ']: alpha\n\n[link][' + 'a' * 1001 + ']\n',
         '[' + 'a' * 1001 + ']: delta\n\n[link][' + 'a' * 1001 + ']\n'),
        ('the destination of a later definition only markdown-it reads changed',
         '[a]: /u\n[' + '\u00e9' * 501 + ']: alpha\n\n[x][' + '\u00e9' * 501 + ']\n',
         '[a]: /u\n[' + '\u00e9' * 501 + ']: delta\n\n[x][' + '\u00e9' * 501 + ']\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('an underline below a definition lengthened',
         '[a]: /u\n===\n',
         '[a]: /u\n====\n'),
        ('prose after an underline below a definition reworded',
         '[a]: /u\n===\nRead prose.\n',
         '[a]: /u\n===\nSee prose.\n'),
        ('prose after a definition only markdown-it reads reworded',
         '[' + 'a' * 1001 + ']: /u\n\nRead prose.\n',
         '[' + 'a' * 1001 + ']: /u\n\nSee prose.\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of d6af219: references that only one renderer resolves are
# boundaries in that renderer's reading only, a reference before an inline
# link tail that depends on the renderer freezes its unit, definitions with
# an unbalanced destination are cmark-gfm's only, labels have no length
# limit for markdown-it, call chains continue after "::", shortcut
# references may precede "(" or an unclosed "[", a full reference may have
# empty text, link text ends a delimiter run for markdown-it, and a
# destination that leaves a parenthesis open freezes its unit.
for name, src, cand in [
        ('the label before an inline link tail changed where the readings differ',
         'Read [text][\u00a0](/v) now.\n\n[\u00a0]: /u\n',
         'Read [text][\u2009](/v) now.\n\n[\u00a0]: /u\n'),
        ('emphasis lost next to a reference whose definition only cmark-gfm takes',
         'Read [*a][r] b* now.\n\n[r]: foo(bar\n',
         'Read [*a][r] *b now.\n\n[r]: foo(bar\n'),
        ('emphasis gained next to a reference with a label over 1000 bytes',
         'Read a*[,**][' + 'a' * 1001 + ']** now.\n\n[' + 'a' * 1001 + ']: /u\n',
         'Read a *[,**][' + 'a' * 1001 + ']** now.\n\n[' + 'a' * 1001 + ']: /u\n'),
        ('a scoped name after a call changed',
         'Call run().field::value now.\n',
         'Call run().field::other now.\n'),
        ('the member after a long call changed',
         'Call ' + 'a' * 80 + '().field now.\n',
         'Call ' + 'a' * 80 + '().other now.\n'),
        ('a shortcut reference before a failed inline link changed',
         'Read [word](oops now.\n\n[word]: /u\n',
         'Read [term](oops now.\n\n[word]: /u\n'),
        ('a shortcut reference before an unclosed bracket removed',
         'Read [r][! now.\n\n[r]: /u\n',
         'Read [][! now.\n\n[r]: /u\n'),
        ('emphasis lost around a label that becomes a shortcut link',
         'Read *[[r] x][a*]** now.\n\n[a*]: /u\n[r]: /v\n',
         'Read *[[r] x][a*]**now.\n\n[a*]: /u\n[r]: /v\n'),
        ('emphasis lost around a reference link with empty text',
         'Read *[][a*]** now.\n\n[a*]: /u\n',
         'Read *[][a*]**now.\n\n[a*]: /u\n'),
        ('emphasis gained at the end of link text (markdown-it reading)',
         'Read [__!_][r] now.\n\n[r]: /u\n',
         'Read [ __!_][r] now.\n\n[r]: /u\n'),
        ('a destination that leaves a parenthesis open changed',
         'Read [word](a(b ) now.\n',
         'Read [word](a(c ) now.\n'),
        ('a reference image before a failed inline tail turned into a link',
         'Read word![r]a(b now.\n\n[r]: /u\n',
         'Read word![r](b now.\n\n[r]: /u\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose around five references that only markdown-it resolves reworded',
         'Read ' + ' and '.join('[*word*][' + x + ' b]' for x in 'abcde') + ' now.\n\n'
         + ''.join('[' + x + '\u00a0b]: /u\n' for x in 'abcde'),
         'See ' + ' and '.join('[*word*][' + x + ' b]' for x in 'abcde') + ' now.\n\n'
         + ''.join('[' + x + '\u00a0b]: /u\n' for x in 'abcde')),
        ('prose after a shortcut reference before a failed inline link reworded',
         'Read [word](oops now.\n\n[word]: /u\n',
         'See [word](oops today.\n\n[word]: /u\n'),
        ('prose around a reference whose text holds brackets reworded',
         'Read [a [b] c][r] now.\n\n[r]: /u\n',
         'See [a [b] c][r] today.\n\n[r]: /u\n'),
        ('prose around a reference link with empty text reworded',
         'Read [][r] now.\n\n[r]: /u\n',
         'See [][r] today.\n\n[r]: /u\n')]:
    accepts("R3 " + name, src, cand)
started = time.time()
accepts("R3 a paragraph of 8000 emphasized reference links unchanged",
        "Read " + " ".join("[*w*][r]" for _ in range(8000)) + " now.\n\n[r]: /u\n",
        "Read " + " ".join("[*w*][r]" for _ in range(8000)) + " now.\n\n[r]: /u\n")
report("R3 a paragraph of 8000 emphasized reference links checked within three seconds",
       time.time() - started < 3.0, "%.2fs" % (time.time() - started))


# Re-review of 6610945: markdown-it's title rule decides whether it takes a
# definition, labels over 1000 bytes may span lines, the underline below
# definitions keeps markdown-it's reading, the "![" of a reference image is
# protected, and two false rejections.
for name, src, cand in [
        ('emphasis lost next to a reference whose title ends in a backslash',
         'Read [*the guide][r] carefully* now.\n\n[r]: /guide "C:\\"\n',
         'Read [*the guide][r] *carefully now.\n\n[r]: /guide "C:\\"\n'),
        ('the destination below a long label over two lines changed',
         '[' + 'a' * 600 + '\n' + 'b' * 500 + ']: alpha\n\n[guide][' + 'a' * 600 + '\n' + 'b' * 500 + ']\n',
         '[' + 'a' * 600 + '\n' + 'b' * 500 + ']: delta\n\n[guide][' + 'a' * 600 + '\n' + 'b' * 500 + ']\n'),
        ('a thematic break below a definition shortened to two dashes',
         '[ref]: /u\n---\nRead prose.\n',
         '[ref]: /u\n--\nRead prose.\n'),
        ('a thematic break below a definition shortened to one dash',
         '[ref]: /u\n---\nRead prose.\n',
         '[ref]: /u\n-\nRead prose.\n'),
        ('a reference image with brackets in its alt text turned into a link',
         'See ![Architecture [draft]][diagram].\n\n[diagram]: /diagram.svg\n',
         'See [Architecture [draft]][diagram].\n\n[diagram]: /diagram.svg\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose around image-shaped text in an HTML attribute reworded',
         'Read <span data-template="![alt](image.png)">the guide</span> now.\n',
         'See <span data-template="![alt](image.png)">the guide</span> now.\n'),
        ('prose before a parenthetical after a reference reworded',
         'Read [guide][r](call(a, b)) now.\n\n[r]: /guide\n',
         'See [guide][r](call(a, b)) now.\n\n[r]: /guide\n'),
        ('the alt text of a reference image with brackets reworded',
         'See ![Architecture [draft]][diagram].\n\n[diagram]: /diagram.svg\n',
         'See ![System [draft]][diagram].\n\n[diagram]: /diagram.svg\n'),
        ('a thematic break below a definition lengthened',
         '[ref]: /u\n---\nRead prose.\n',
         '[ref]: /u\n----\nRead prose.\n'),
        ('prose next to a reference with an ordinary title reworded',
         'Read [*the guide][r] carefully* now.\n\n[r]: /guide "Guide"\n',
         'See [*the guide][r] carefully* today.\n\n[r]: /guide "Guide"\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of 1ffae14: markdown-it reads definitions one by one from the
# start of a paragraph and stops at the first it does not take, it rejects
# script and data destinations, the underline below definitions is read
# relative to its container, frozen long-label paragraphs and headings
# define every label markdown-it reads there, and calls may follow calls.
LONG2 = 'a' * 600 + '\n' + 'b' * 500
for name, src, cand in [
        ('an inline link after a definition markdown-it does not take changed',
         'Read [guide][r](alpha) now.\n\n[a]: /guide "C:\\"\n[r]: /reference\n',
         'Read [guide][r](delta) now.\n\n[a]: /guide "C:\\"\n[r]: /reference\n'),
        ('an inline link next to a data definition changed',
         'Read [sample][r](alpha) now.\n\n[r]: data:text/plain,hello\n',
         'Read [sample][r](delta) now.\n\n[r]: data:text/plain,hello\n'),
        ('an inline link next to a script definition changed',
         'Read [sample][r](alpha) now.\n\n[r]: javascript:alert(1)\n',
         'Read [sample][r](delta) now.\n\n[r]: javascript:alert(1)\n'),
        ('a thematic break below a definition in a nested list shortened',
         '- Outer.\n  - [r]: /guide\n    ---\n    Read prose.\n',
         '- Outer.\n  - [r]: /guide\n    --\n    Read prose.\n'),
        ('emphasis moved into a reference defined after a long label',
         'Read [*the guide][r] carefully* now.\n\n[' + LONG2 + ']: /unused\n[r]: /guide\n',
         'Read [*the guide*][r] carefully now.\n\n[' + LONG2 + ']: /unused\n[r]: /guide\n'),
        ('emphasis moved into a reference defined above an underline after a long label',
         'Read [*the guide][r] carefully* now.\n\n[' + LONG2 + ']: /unused\n[r]: /guide\n---\n',
         'Read [*the guide*][r] carefully now.\n\n[' + LONG2 + ']: /unused\n[r]: /guide\n---\n'),
        ('the second call of a call removed',
         'Call factory()() to create the object.\n',
         'Call factory() to create the object.\n'),
        ('the member after two calls changed',
         'Read factory()().value now.\n',
         'Read factory()().other now.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose before a parenthetical with an indented continuation definition reworded',
         'Read [guide][r](see examples) now.\n\n- [a]: /intro\n    [r]: /guide\n',
         'See [guide][r](see examples) now.\n\n- [a]: /intro\n    [r]: /guide\n'),
        ('prose next to a reference with a data image definition reworded',
         'Read [*the logo][r] here* now.\n\n[r]: data:image/png;base64,AAAA\n',
         'See [*the logo][r] here* today.\n\n[r]: data:image/png;base64,AAAA\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of 7eb0f50: markdown-it starts a new block after each
# definition (indented code, a thematic break, a list item that cannot
# interrupt a paragraph, an HTML block of the seventh kind, another
# definition), decodes a destination before it validates it, does not go
# back after an empty title, and ends a definition's lines at a list item or
# a thematic break; calls on "$" variables are one token.
for name, src, cand in [
        ('an indented line after a definition reworded (markdown-it code)',
         '[ref]: /url\n    Read this.\n',
         '[ref]: /url\n    See this.\n'),
        ('code after a definition edited',
         '[a]: /guide\n    echo hello\n',
         '[a]: /guide\n    echo world\n'),
        ('code in a list item after a definition edited',
         '- [a]: /guide\n      echo hello\n',
         '- [a]: /guide\n      echo world\n'),
        ('code in a quote after a definition edited',
         '> [a]: /guide\n>     echo hello\n',
         '> [a]: /guide\n>     echo world\n'),
        ('an inline link after an indented definition changed',
         'Read [guide][r](alpha) now.\n\n[a]: /guide\n    [r]: /reference\n',
         'Read [guide][r](delta) now.\n\n[a]: /guide\n    [r]: /reference\n'),
        ('an inline link after a rolled-back title changed',
         'Read [guide][r](alpha) now.\n\n[a]: /guide\n"C:\\"\n[r]: /reference\n',
         'Read [guide][r](delta) now.\n\n[a]: /guide\n"C:\\"\n[r]: /reference\n'),
        ('an inline link after a definition with an empty label changed',
         'Read [guide][r](alpha) now.\n\n[\u00a0]: /guide\n[r]: /reference\n',
         'Read [guide][r](delta) now.\n\n[\u00a0]: /guide\n[r]: /reference\n'),
        ('a definition after a thematic break below a definition changed',
         'Read [guide][r] now.\n\n[a]: /guide\n---\n[r]: guide\n',
         'Read [guide][r] now.\n\n[a]: /guide\n---\n[r]: other\n'),
        ('a list number after a definition moved into prose',
         '[r]: /guide\n3. Install the package.\n',
         '[r]: /guide\nThen 3. Install the package.\n'),
        ('an empty list item added after a definition',
         '[r]: /guide\nRead it.\n',
         '[r]: /guide\n+\nRead it.\n'),
        ('prose in an HTML block after a definition reworded',
         '[r]: /guide\n<span class="x">\nRead the guide now.\n',
         '[r]: /guide\n<span class="x">\nSee the guide now.\n'),
        ('an inline link next to a definition with an encoded data link changed',
         'Read [guide][r](alpha) now.\n\n[r]: data&#58;text/plain,hello\n',
         'Read [guide][r](delta) now.\n\n[r]: data&#58;text/plain,hello\n'),
        ('an inline link next to a definition with an escaped script link changed',
         'Read [sample][r](alpha) now.\n\n[r]: javascript\\:alert(1)\n',
         'Read [sample][r](delta) now.\n\n[r]: javascript\\:alert(1)\n'),
        ('an inline link next to a definition with an empty title and more text changed',
         'Read [sample][r](alpha) now.\n\n[r]: /guide\n"" x\n',
         'Read [sample][r](delta) now.\n\n[r]: /guide\n"" x\n'),
        ('an inline link next to a definition whose title meets a list number changed',
         'Read [sample][r](alpha) now.\n\n[r]: /guide "multi\n2. line"\n',
         'Read [sample][r](delta) now.\n\n[r]: /guide "multi\n2. line"\n'),
        ('an inline link after a destination ending in a backslash and a title line changed',
         'Read [x][r](alpha) now.\n\n[b]: \\\\srv\\share\\\n"Share"\n[r]: /guide\n',
         'Read [x][r](delta) now.\n\n[b]: \\\\srv\\share\\\n"Share"\n[r]: /guide\n'),
        ('code after a setext underline below a definition markdown-it does not take edited',
         '> [r]: /guide "C:\\"\n> --\n>     echo hello\n',
         '> [r]: /guide "C:\\"\n> --\n>     echo world\n'),
        ('an inline link defined after a heading markdown-it reads differently changed',
         'Read [x][r](alpha) now.\n\n[a]: javascript:x\n--\n--\n[r]: /guide\n',
         'Read [x][r](delta) now.\n\n[a]: javascript:x\n--\n--\n[r]: /guide\n'),
        ('an inline link defined after an HTML line and a heading underline changed',
         'Read [x][r](alpha) now.\n\n[b]: /guide \'Guide\'\n<span class="x">\n---\n[r]: /reference\n',
         'Read [x][r](delta) now.\n\n[b]: /guide \'Guide\'\n<span class="x">\n---\n[r]: /reference\n'),
        ('a definition read at an underline before a later quote changed',
         'Read [x][r] now.\n\n[r]: /alpha "C:\\"\n===\nSay "" here.\n---\n',
         'Read [x][r] now.\n\n[r]: /delta "C:\\"\n===\nSay "" here.\n---\n'),
        ('the second call of a "$" call removed',
         'Call $factory()() to create the object.\n',
         'Call $factory() to create the object.\n'),
        ('the member after two "$" calls changed',
         'Read $factory()().value now.\n',
         'Read $factory()().other now.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose next to a data image definition with an encoded semicolon reworded',
         'Read [logo][r](see examples) now.\n\n[r]: data:image/png&#59;base64,AAAA\n',
         'See [logo][r](see examples) now.\n\n[r]: data:image/png&#59;base64,AAAA\n'),
        ('prose next to a data image definition with an escaped semicolon reworded',
         'Read [logo][r](see examples) now.\n\n[r]: data:image/png\\;base64,AAAA\n',
         'See [logo][r](see examples) now.\n\n[r]: data:image/png\\;base64,AAAA\n'),
        ('prose after a thematic break below a definition reworded',
         '[a]: /guide\n---\nRead the guide now.\n',
         '[a]: /guide\n---\nSee the guide now.\n'),
        ('prose after an empty list item below a definition reworded',
         '[a]: /guide\n+\nRead the guide now.\n',
         '[a]: /guide\n+\nSee the guide now.\n'),
        ('prose after code below a definition reworded',
         '[a]: /guide\n    echo hello\nRead the guide now.\n',
         '[a]: /guide\n    echo hello\nSee the guide now.\n'),
        ('a lazy dash line in a quoted list item reindented',
         '> - item\n  > |---|---|\n    ---\n|---|---|\n   | text two |\n',
         '> - item\n  > |---|---|\n     ---\n|---|---|\n   | text two |\n'),
        ('a word after a destination ending in a backslash reworded',
         'Read [share][r] now.\n\n[r]: \\\\server\\share\\\nnotes\n',
         'Read [share][r] now.\n\n[r]: \\\\server\\share\\\nfiles\n'),
        ('a "$" variable in prose kept while the prose is reworded',
         'Set $HOME. Then run $build() now.\n',
         'First set $HOME. Then run $build() today.\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of 425fbc4: cmark-gfm keeps a title it rolled back from the
# paragraph text, markdown-it reads a lazy line after a definition outside
# its quote or list item (a quote marker reopens a quote; a list item that
# cannot interrupt a paragraph continues it), tab columns after quote
# markers, labels behind list and quote markers in any order, "$" scoped
# calls and long braced variables with calls; a list item with text after a
# definition keeps its text editable, and an HTML block in a quote ends with
# the quote.
LONGVAR = '${' + 'createCachedAuthenticatedDatabaseConnectionForTenantWithFallbackAndAutomaticRetry' + '}'
for name, src, cand in [
        ('a title cmark-gfm keeps from the text after a definition changed',
         'Read [r].\n\n[r]: /guide\n"Read the guide" extra.\n',
         'Read [r].\n\n[r]: /guide\n"See the guide" extra.\n'),
        ('a title cmark-gfm keeps over two lines changed',
         'Read [r].\n\n[r]: /guide\n"multi\nline" extra\n',
         'Read [r].\n\n[r]: /guide\n"multi\nrow" extra\n'),
        ('code in a quote reopened after a lazy line edited',
         '> [a]: /guide\nRead the guide.\n>     echo hello\n',
         '> [a]: /guide\nRead the guide.\n>     echo world\n'),
        ('an inline link next to a definition in a reopened quote changed',
         'Read [x][r](alpha) now.\n\n> [a]: /guide\nRead the guide.\n> [r]: /target\n',
         'Read [x][r](delta) now.\n\n> [a]: /guide\nRead the guide.\n> [r]: /target\n'),
        ('an inline link next to a definition in a list item markdown-it reads as text changed',
         'Read [guide][r](alpha) now.\n\n1. [a]: /guide\nRead the guide.\n2. [r]: /reference\n',
         'Read [guide][r](delta) now.\n\n1. [a]: /guide\nRead the guide.\n2. [r]: /reference\n'),
        ('code after a tab in a quoted list item edited',
         '> - [a]: /guide\n>   \techo hello\n',
         '> - [a]: /guide\n>   \techo world\n'),
        ('emphasis around a reference defined behind a list and a quote marker added',
         'Read [*guide][r]* now.\n\n[a]: /guide\n2. > [r]: /reference\n',
         'Read *[guide][r]* now.\n\n[a]: /guide\n2. > [r]: /reference\n'),
        ('the scope of a "$" call removed',
         'Call $factory::make() now.\n',
         'Call $factory make() now.\n'),
        ('the member after calls on a long braced variable changed',
         'Call ' + LONGVAR + '()().value now.\n',
         'Call ' + LONGVAR + '()().other now.\n'),
        ('the marker of a list item after a definition changed',
         '[a]: /guide\n2. Install the package.\n',
         '[a]: /guide\n2) Install the package.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('the text of a list item after a definition reworded',
         '[a]: /guide\n2. Install the package.\n',
         '[a]: /guide\n2. Set up the package.\n'),
        ('prose after an HTML block in a quote reworded',
         '> [a]: /guide\n> <img src="logo.png">\nRead the guide.\n',
         '> [a]: /guide\n> <img src="logo.png">\nSee the guide.\n'),
        ('prose after a definition whose next line holds no title reworded',
         'Read [r].\n\n[r]: /guide\nRead the "guide" today.\n',
         'Read [r].\n\n[r]: /guide\nSee the "guide" today.\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of 746ec63: list item text after a definition is classified
# (indented code, fences and headings are not prose), markdown-it's quote
# depth is tracked per line, a lazy line keeps its leading whitespace for
# cmark-gfm, markdown-it reads lines anew once it closed a list item or a
# quote, front matter may hold definitions, and "$" words keep their
# members and scopes.
for name, src, cand in [
        ('indented code in a list item after a definition edited',
         '[a]: /guide\n2.     echo hello\n',
         '[a]: /guide\n2.     echo world\n'),
        ('a fence in a list item after a definition edited',
         '[a]: /guide\n2. FFF\n   echo hello\n   FFF\n',
         '[a]: /guide\n2. FFF\n   echo world\n   FFF\n'),
        ('the heading marker in a list item after a definition removed',
         '[a]: /guide\n2. # Install the package.\n',
         '[a]: /guide\n2. Install the package.\n'),
        ('code in a quote reopened at a shallower depth edited',
         '> > [a]: /guide\nRead the guide.\n>     echo hello\n',
         '> > [a]: /guide\nRead the guide.\n>     echo world\n'),
        ('an inline link next to a definition after two list boundaries changed',
         'Read [guide][r](alpha) now.\n\n1. [a]: /guide\nRead the guide.\n2. Normal text.\n3. [r]: /reference\n',
         'Read [guide][r](delta) now.\n\n1. [a]: /guide\nRead the guide.\n2. Normal text.\n3. [r]: /reference\n'),
        ('code after a definition in a quoted list item edited',
         '> - [a]: /guide\n    echo hello\n',
         '> - [a]: /guide\n    echo world\n'),
        ('an inline link next to an indented lazy definition changed',
         'Read [guide][r](alpha) now.\n\n> [a]: /guide\n  [r]: /reference\n',
         'Read [guide][r](delta) now.\n\n> [a]: /guide\n  [r]: /reference\n'),
        ('the member of a "$" variable changed',
         'Read $config.timeout before continuing.\n',
         'Read $config.interval before continuing.\n'),
        ('the scope of a call on a long braced variable removed',
         'Call ' + LONGVAR + '::make() now.\n',
         'Call ' + LONGVAR + ' make() now.\n'),
        ('an inline link next to a definition after an underline in a reopened quote changed',
         'Read [x][c](alpha) now.\n\n> [n]: /n\nlazy\n[j]:\n/j\n> ===\n> [c]: <u v>\n',
         'Read [x][c](delta) now.\n\n> [n]: /n\nlazy\n[j]:\n/j\n> ===\n> [c]: <u v>\n'),
        ('an inline link next to a definition in front matter changed',
         '---\n[r]: /guide\n---\n\nRead [x][r](alpha) now.\n',
         '---\n[r]: /guide\n---\n\nRead [x][r](delta) now.\n'),
        ('an inline link next to a definition after code outside a list item changed',
         'Read [x][b](alpha) now.\n\n- [k]: /k\n[a]: /x\n\tTab\n[b]: /y\n',
         'Read [x][b](delta) now.\n\n- [k]: /k\n[a]: /x\n\tTab\n[b]: /y\n'),
        ('an inline link next to a definition after a heading outside a list item changed',
         'Read [x][i](alpha) now.\n\n- [e]: /w\n[e]: /w\n  [g]: /a(b\n--\n[i]: /i\n',
         'Read [x][i](delta) now.\n\n- [e]: /w\n[e]: /w\n  [g]: /a(b\n--\n[i]: /i\n')]:
    rejects("R3 " + name, src.replace("FFF", "```"), cand.replace("FFF", "```"))
for name, src, cand in [
        ('prose after an indented lazy line that holds no definition reworded',
         'Read [a] and [r].\n\n> [a]: /guide\n  [r]: /reference\n  "Read the guide" extra.\n',
         'Read [a] and [r].\n\n> [a]: /guide\n  [r]: /reference\n  "See the guide" extra.\n'),
        ('a heading after inline HTML in list item text reworded',
         '[a]: /guide\n2. Install the package.\n<span>\n# Read the guide\n',
         '[a]: /guide\n2. Install the package.\n<span>\n# See the guide\n'),
        ('prose after a "$" variable that ends a sentence reworded',
         'Set $config. Then go.\n',
         'Set $config. Then continue.\n'),
        ('an inline link next to a definition in a quote after a heading kept',
         'Read [x][n](alpha) now.\n\n[c]: /c\n---\n--\n> [n]: /n\n',
         'Read [x][n](delta) now.\n\n[c]: /c\n---\n--\n> [n]: /n\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of d624bcc and a wider label differential fuzz: the rest of a
# container that markdown-it closed inside a paragraph is kept byte for
# byte, also past it while a block markdown-it reads there runs on; a
# paragraph markdown-it opens at cmark-gfm's setext underline continues
# lazily over the blocks after the heading; markdown-it ends nested quotes
# at an indented lazy block start and continues a quote at an indented
# quote marker; quoted multi-line labels in frozen blocks are collected
# without their markers; a kept title keeps cmark-gfm's lazy whitespace;
# and a heading in a list item keeps only its markers as structure.
for name, src, cand in [
        ('text markdown-it reads as code after it closed a list item edited',
         '- [a]: /guide\n[b]: /other\n\n    echo hello\n',
         '- [a]: /guide\n[b]: /other\n\n    echo world\n'),
        ('an inline link next to a definition after a heading and indented code changed',
         'Read [x][e](alpha) now.\n\n[j]: /j\n*\n--\n    code\n[e]: /w\n',
         'Read [x][e](delta) now.\n\n[j]: /j\n*\n--\n    code\n[e]: /w\n'),
        ('code after a list item markdown-it closed, in a further block, edited',
         '- [a]: /guide\n[b]: /reference\n    - echo hello\n',
         '- [a]: /guide\n[b]: /reference\n    - echo world\n'),
        ('text inside an HTML block markdown-it opens after it closed a list item edited',
         '- > [a]: /guide\nRead the guide.\n  <div>\nKeep this exact.\n</div>\n',
         '- > [a]: /guide\nRead the guide.\n  <div>\nRetain this text.\n</div>\n'),
        ('an indented heading-like lazy line after nested quotes edited',
         '> > Note.\n    # echo hello\n',
         '> > Note.\n    # echo world\n'),
        ('an indented list-like lazy line after nested quotes edited',
         '> > Note.\n    - echo hello\n',
         '> > Note.\n    - echo world\n'),
        ('an inline link next to a definition behind an indented quote marker changed',
         'Read [x][n](alpha) now.\n\n> quoted\n    > > [n]: /n\n',
         'Read [x][n](delta) now.\n\n> quoted\n    > > [n]: /n\n'),
        ('a reference to a quoted multi-line label in a protected region changed',
         'Read [guide][long label](alpha) now.\n\n<!-- polish:off -->\n> [long\n> label]: /guide\n<!-- polish:on -->\n',
         'Read [guide][other label](alpha) now.\n\n<!-- polish:off -->\n> [long\n> label]: /guide\n<!-- polish:on -->\n'),
        ('the whitespace of a lazy line inside a kept title changed',
         'Read [r].\n\n> [r]: /guide\n"Read\n  the guide" extra.\n',
         'Read [r].\n\n> [r]: /guide\n"Read\n the guide" extra.\n'),
        ('the level of a heading in a list item after a definition changed',
         '[a]: /guide\n2. # Install the package.\n',
         '[a]: /guide\n2. ## Install the package.\n'),
        ('a definition after indented code that continues a quote for markdown-it kept as a link',
         'Read [x][b](alpha) now.\n\n> -     code\n    > quoted\n[b]: /y\n',
         'Read [x][b](delta) now.\n\n> -     code\n    > quoted\n[b]: /y\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a list item markdown-it closed reworded',
         '- [a]: /guide\n[b]: /other\n\nRead the guide.\n',
         '- [a]: /guide\n[b]: /other\n\nSee the guide.\n'),
        ('a heading in a list item after a definition reworded',
         '[a]: /guide\n2. # Read the guide.\n',
         '[a]: /guide\n2. # See the guide.\n'),
        ('an indented plain lazy line after nested quotes reworded',
         '> > Note.\n    more text here\n',
         '> > Note.\n    more words here\n'),
        ('a lazy line in a nested quote reworded',
         '> > Note one.\n> continued here.\n',
         '> > Note two.\n> continued here.\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of 9963ebb and a plausible-document fuzz with nested
# containers: in the rest of a container that markdown-it closed, only the
# lines it may read as a block of another kind (indented code, a fence, an
# HTML block) and what follows them are kept byte for byte (a fence closes
# only at markdown-it's indentation and quote depth); prose, list items and
# headings there stay prose, and their definitions only possibly count. A
# list item markdown-it starts after a definition keeps the spaces after its
# marker; quoted indented code ends where a quote marker leaves a list item;
# a list item only cmark-gfm opens is read as markdown-it's top level; an
# HTML block in a quote markdown-it reopened runs over that quote.
for name, src, cand in [
        ('a nested list item after a quoted definition markdown-it closed reworded',
         '- > [api]: /api\n[api]: /api\n  - Read the guide notes.\n',
         '- > [api]: /api\n[api]: /api\n  - Read the setup notes.\n'),
        ('a list item after a quote markdown-it closed reworded',
         '> - [x]: /a\n> [r]: /r\n[r]: /r\n+ Another guide item\n',
         '> - [x]: /a\n> [r]: /r\n[r]: /r\n+ Another setup item\n'),
        ('a quoted heading after a definition markdown-it closed reworded',
         '- > [api]: /api\n[w]: /w\n  > # Heading guide\n',
         '- > [api]: /api\n[w]: /w\n  > # Heading setup\n'),
        ('an inline link next to a definition both renderers take after a closed item changed',
         'Read [x][c](alpha) now.\n\n- [a]: /guide\n[b]: /other\n  [c]: /c\n',
         'Read [x][c](delta) now.\n\n- [a]: /guide\n[b]: /other\n  [c]: /c\n'),
        ('a later paragraph in a list item markdown-it closed reworded',
         '- [a]: /guide\nRead the guide.\n\n  Read the notes.\n',
         '- [a]: /guide\nRead the guide.\n\n  See the notes.\n'),
        ('a heading in a list item markdown-it closed reworded',
         '- [a]: /guide\nRead the guide.\n  # Read the notes.\n',
         '- [a]: /guide\nRead the guide.\n  # See the notes.\n'),
        ('the next list item after one markdown-it closed reworded',
         '- [a]: /guide\nRead the guide.\n- Read the notes.\n',
         '- [a]: /guide\nRead the guide.\n- See the notes.\n')]:
    accepts("R3 " + name, src, cand)
for name, src, cand in [
        ('the spaces after a heading item marker after a definition changed',
         '[a]: /guide\n2. # Read the guide.\n   ## Read the notes.\n',
         '[a]: /guide\n2.  # Read the guide.\n   ## Read the notes.\n'),
        ('the spaces after a list item marker after a definition changed',
         '[a]: /guide\n2. Install the package.\n   # Read the notes.\n',
         '[a]: /guide\n2.  Install the package.\n   # Read the notes.\n'),
        ('code after quoted code that left a list item edited',
         '- >     echo first\n>     echo second\n\n    echo hello\n',
         '- >     echo first\n>     echo second\n\n    echo world\n'),
        ('an inline link next to code that looks like a definition after a closed list changed',
         'Read [x][ref](alpha) now.\n\n- >     echo first\n>     echo second\n\n    [ref]: /guide\n',
         'Read [x][ref](delta) now.\n\n- >     echo first\n>     echo second\n\n    [ref]: /guide\n'),
        ('code after an indented fence line in a fence markdown-it opened edited',
         '- [a]: /guide\nRead the guide.\n  FFF\necho first\n    FFF\n\necho hello\nFFF\n',
         '- [a]: /guide\nRead the guide.\n  FFF\necho first\n    FFF\n\necho world\nFFF\n'),
        ('code after a quoted fence line in a fence markdown-it opened edited',
         '- [a]: /guide\nRead the guide.\n  FFF\necho first\n> FFF\n\necho hello\nFFF\n',
         '- [a]: /guide\nRead the guide.\n  FFF\necho first\n> FFF\n\necho world\nFFF\n'),
        ('code in a list item only cmark-gfm opens edited',
         '- [docs]: /guide\nRead the guide.\n2. Read the notes.\n\n    echo hello\n',
         '- [docs]: /guide\nRead the guide.\n2. Read the notes.\n\n    echo world\n'),
        ('text inside an HTML block in a quote markdown-it reopened edited',
         '> - [docs]: /guide\nRead the guide.\n>   <span>\n> Keep this exact.\n> </span>\n',
         '> - [docs]: /guide\nRead the guide.\n>   <span>\n> Retain this text.\n> </span>\n'),
        ('text inside an HTML block after a closed list item in a quote edited',
         'See [the docs][docs] now.\n\n> - [spec]: https://example.com/spec\n>   [r]: /reference\n> [guide]: ./docs/guide.md\n>   <img src="logo.png">\n> Title word here\n',
         'See [the docs][docs] now.\n\n> - [spec]: https://example.com/spec\n>   [r]: /reference\n> [guide]: ./docs/guide.md\n>   <img src="logo.png">\n> Title text here\n'),
        ('an inline link next to a definition after an underline markdown-it reads as text changed',
         'Read [x][d](alpha) now.\n\n1. [c]: /c\n[i]: /i\n"t" more\n\t===\n[d]: /z\n',
         'Read [x][d](delta) now.\n\n1. [c]: /c\n[i]: /i\n"t" more\n\t===\n[d]: /z\n')]:
    rejects("R3 " + name, src.replace("FFF", "```"), cand.replace("FFF", "```"))


# Re-review of c2460e3: an HTML block markdown-it opens after it closed a
# container runs to a blank line (raw HTML to its end marker) whatever the
# containers of the lines; a list item cmark-gfm opens inside it stays open
# after it, where markdown-it reads the top level; an underline indented
# four columns is lazy text to a paragraph markdown-it reads outside the
# list item, whatever it looks like; a list item with fewer quote markers
# than markdown-it's open paragraph opens in markdown-it too; and the freeze
# after a closed container stops once no block markdown-it reads can run on.
for name, src, cand in [
        ('a heading markdown-it reads inside an HTML block after a closed item edited',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n# Keep this exact.\n',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n# Retain this text.\n'),
        ('a quote markdown-it reads inside an HTML block after a closed item edited',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n> Keep this exact.\n',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n> Retain this text.\n'),
        ('a list item markdown-it reads inside an HTML block after a closed item edited',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n- Keep this exact.\n',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n- Retain this text.\n'),
        ('text inside an HTML comment after a closed item and a blank line edited',
         '- [docs]: /guide\n[notes]: /notes\n  <!-- start\n\nKeep this exact.\n-->\n',
         '- [docs]: /guide\n[notes]: /notes\n  <!-- start\n\nRetain this text.\n-->\n'),
        ('code after a list item markdown-it reads inside an HTML block edited',
         '[docs]: /guide\n2. # Installation\n  <img src="logo.png">\n  - Setup notes.\n\n      echo hello\n',
         '[docs]: /guide\n2. # Installation\n  <img src="logo.png">\n  - Setup notes.\n\n      echo world\n'),
        ('an inline link next to a definition after an indented dash underline changed',
         'Read [guide][ref](online).\n\n- [docs]: /guide\nRead the setup notes.\n    ---\n[ref]: /reference\n',
         'Read [guide][ref](latest).\n\n- [docs]: /guide\nRead the setup notes.\n    ---\n[ref]: /reference\n'),
        ('an inline link next to a definition after an indented single dash changed',
         'Read [guide][ref](online).\n\n- [docs]: /guide\nRead the setup notes.\n    -\n[ref]: /reference\n',
         'Read [guide][ref](latest).\n\n- [docs]: /guide\nRead the setup notes.\n    -\n[ref]: /reference\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('a list item after a quote markdown-it closed, with an indented paragraph, reworded',
         '> - [docs]: /guide\n> Read the guide.\n2. Read notes.\n\n    Read the extra notes.\n',
         '> - [docs]: /guide\n> Read the guide.\n2. Read notes.\n\n    See the extra notes.\n'),
        ('prose after a closed quoted fence after a closed item reworded',
         '- [docs]: /guide\nRead the guide.\n  > FFF\n  > echo first\n  > FFF\nRead the notes.\n',
         '- [docs]: /guide\nRead the guide.\n  > FFF\n  > echo first\n  > FFF\nSee the notes.\n'),
        ('prose after an HTML block and a blank line after a closed item reworded',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n\nRead the notes.\n',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n\nSee the notes.\n')]:
    accepts("R3 " + name, src.replace("FFF", "```"), cand.replace("FFF", "```"))


# Re-review of 798b312: the freeze of a container markdown-it closed runs on
# over HTML blocks frozen before it and reads fences and raw HTML inside an
# HTML block as its text; lazy lines and further list items only cmark-gfm
# opens stay in the container markdown-it closed; an indented quote marker
# under a paragraph markdown-it reads outside the quote is lazy text;
# cmark-gfm keeps no whitespace on a lazy line that reaches an outer list
# item's content column; markdown-it ends raw HTML in a list item at a blank
# line short of the item's content column; an HTML block in a quote
# markdown-it reopened ends with that quote. Own additions: a lazy line
# indented four columns but short of a wide list item's content column that
# looks like a block start ends markdown-it's paragraph and item (indented
# code); an HTML block inside a container that swallows a nested list item;
# a block markdown-it reads past an unknown stretch; a quoted HTML block
# markdown-it continues over a quote marker indented four columns.
for name, src, cand in [
        ('code after a quoted HTML line markdown-it reads inside an HTML block edited',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n  > <img src="logo.png">\n\n    echo hello\n',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n  > <img src="logo.png">\n\n    echo world\n'),
        ('code after an HTML block that ends a closed item edited',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n  <div>\n\n    echo hello\n',
         '- [docs]: /guide\n[notes]: /notes\n  <img src="logo.png">\n  <div>\n\n    echo world\n'),
        ('a heading after a fence inside an HTML block after a closed item edited',
         '- [docs]: /guide\nRead the guide.\n\n  <img src="logo.png">\n  FFF\n  FFF\n# Keep this exact.\n',
         '- [docs]: /guide\nRead the guide.\n\n  <img src="logo.png">\n  FFF\n  FFF\n# Retain this text.\n'),
        ('code after a lazy line in a list item only cmark-gfm opens edited',
         '1. [docs]: /guide\nRead the guide.\n2. Read notes.\nMore details.\n\n    echo hello\n',
         '1. [docs]: /guide\nRead the guide.\n2. Read notes.\nMore details.\n\n    echo world\n'),
        ('code in a further list item only cmark-gfm opens edited',
         '1. [docs]: /guide\nRead the guide.\n2. Read notes.\n3. More details.\n\n    echo hello\n',
         '1. [docs]: /guide\nRead the guide.\n2. Read notes.\n3. More details.\n\n    echo world\n'),
        ('an inline link next to a definition after an indented quoted underline changed',
         'Read [guide][ref](online).\n\n- > [docs]: /guide\nRead the guide.\n    > ---\n[ref]: /reference\n',
         'Read [guide][ref](latest).\n\n- > [docs]: /guide\nRead the guide.\n    > ---\n[ref]: /reference\n'),
        ('an inline link next to text after definitions in a nested list item changed',
         'Read [guide][ref](online).\n\n- Outer list.\n  - [docs]: /guide\n  [notes]: /notes\n    ---\n[ref]: /reference\n',
         'Read [guide][ref](latest).\n\n- Outer list.\n  - [docs]: /guide\n  [notes]: /notes\n    ---\n[ref]: /reference\n'),
        ('code after a wide ordered item and a lazy thematic break edited',
         '  2. Read notes.\n    ---\n        echo hello\n',
         '  2. Read notes.\n    ---\n        echo world\n'),
        ('a heading-like lazy line markdown-it reads as code under a wide item edited',
         '   - Read the guide.\n    # Setup\n',
         '   - Read the guide.\n    # Install\n'),
        ('an inline link next to a definition after a list HTML comment with a blank line changed',
         'Read [guide][ref](online).\n\n- Notes.\n  <!-- start\n\n  -->\n[ref]: /reference\n',
         'Read [guide][ref](latest).\n\n- Notes.\n  <!-- start\n\n  -->\n[ref]: /reference\n'),
        ('code after a nested list item an HTML block in a list item swallows edited',
         '- [docs]: /guide\n  <img src="x">\n  - Setup notes.\n\n      echo hello\n',
         '- [docs]: /guide\n  <img src="x">\n  - Setup notes.\n\n      echo world\n'),
        ('code after a nested list item an HTML block in a quote swallows edited',
         '> [docs]: /guide\n> <img src="x">\n> - Setup notes.\n>\n>     echo hello\n',
         '> [docs]: /guide\n> <img src="x">\n> - Setup notes.\n>\n>     echo world\n'),
        ('a list item markdown-it reads inside an HTML block after nested quotes it ended edited',
         '> >  [notes]: /notes\n    # Notes\n> > <img src="x">\n> >   - Keep this item\n',
         '> >  [notes]: /notes\n    # Notes\n> > <img src="x">\n> >   - Retain this item\n'),
        ('a quote markdown-it reads inside a quoted HTML block over an indented quote marker edited',
         '> <span>\n>[d]: /g\n    > Read more.\n> Keep this exact.\n',
         '> <span>\n>[d]: /g\n    > Read more.\n> Retain this text.\n')]:
    rejects("R3 " + name, src.replace("FFF", "```"), cand.replace("FFF", "```"))
for name, src, cand in [
        ('a heading after an HTML block in a quote markdown-it reopened reworded',
         '> [docs]: /guide\nRead the guide.\n> <img src="logo.png">\n# Read the notes.\n',
         '> [docs]: /guide\nRead the guide.\n> <img src="logo.png">\n# See the notes.\n'),
        ('a lazy line under a wide list item reworded',
         '   1. Run this:\n    and that line.\n',
         '   1. Run this:\n    and this line.\n'),
        ('a heading indented inside a narrow list item reworded',
         '1. Run this:\n    # Not a header\n',
         '1. Run this:\n    # Not a heading\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of 5986fac: a fence that opened in text an HTML block may hold
# opens again at its closing line once that block ended at a blank line; a
# list item cmark-gfm opens after a setext underline markdown-it reads as
# lazy text is read outside it; quote depths in the post-pass follow the
# quote markers the parse moved into list items; an HTML block markdown-it
# reads in frozen lines swallows the list items cmark-gfm opens there; a
# quoted fence cmark-gfm ended with its quote runs on in markdown-it over a
# quote marker indented four columns; quadratic rescans of the blocks are
# gone; the freeze past a container stops at a line that interrupts a
# paragraph, a paragraph that only continues a definition paragraph across
# a new list item is not lazy, and the closed list item is the one the
# lazy line does not reach. Own addition: where cmark-gfm starts an HTML
# block on a lazy line and markdown-it continues its paragraph over it,
# what markdown-it reads there and runs on is kept byte for byte.
for name, src, cand in [
        ('a heading markdown-it reads as code after a fence that opens again after a blank line edited',
         '> - [docs]: /guide\n> [notes]: /notes\n>   <img src="logo.png">\n>   FFF\n>\n>   FFF\n> # Keep this exact.\n',
         '> - [docs]: /guide\n> [notes]: /notes\n>   <img src="logo.png">\n>   FFF\n>\n>   FFF\n> # Retain this text.\n'),
        ('code after a list item opened below a lazy underline edited',
         '1. [docs]: /guide\nRead the guide.\n    ---\n2. Read notes.\n\n    echo hello\n',
         '1. [docs]: /guide\nRead the guide.\n    ---\n2. Read notes.\n\n    echo world\n'),
        ('a title markdown-it reads after a quoted HTML block in a nested item changed',
         'Read [the guide][ref].\n\n- Notes.\n  - > [docs]: /guide\n    > <img src="logo.png">\n    > - Setup notes.\n    [ref]: /reference "Guide"\n',
         'Read [the guide][ref].\n\n- Notes.\n  - > [docs]: /guide\n    > <img src="logo.png">\n    > - Setup notes.\n    [ref]: /reference "Notes"\n'),
        ('an inline link next to a definition after a quoted comment with a blank line in a nested item changed',
         'Read [guide][ref](online).\n\n- Outer notes.\n  - > - Notes.\n    >   <!-- start\n    >\n    >   -->\n    [ref]: /reference\n',
         'Read [guide][ref](latest).\n\n- Outer notes.\n  - > - Notes.\n    >   <!-- start\n    >\n    >   -->\n    [ref]: /reference\n'),
        ('code after a list item an HTML block inside a comment swallows edited',
         '- Notes.\n  <!-- start\n\n  <img src="logo.png">\n  -->\n  - Read notes.\n\n      echo hello\n',
         '- Notes.\n  <!-- start\n\n  <img src="logo.png">\n  -->\n  - Read notes.\n\n      echo world\n'),
        ('a heading markdown-it reads in a quoted fence over an indented quote marker edited',
         '> FFFtext\n    > Quoted code\n> # Setup notes\n> FFF\n',
         '> FFFtext\n    > Quoted code\n> # Usage notes\n> FFF\n'),
        ('a quoted list item markdown-it reads inside a comment after a lazy closing tag edited',
         '>   - Read the item\n  </pre>\n   <!-- note\n\n> >\n> - Keep this item\n  here\n',
         '>   - Read the item\n  </pre>\n   <!-- note\n\n> >\n> - Retain this item\n  here\n'),
        ('a comment markdown-it reads inline across a lazy HTML line edited',
         '  > Read this\n      FFF\n    <pre>\n    <!-- keep this\n<img src="x">\n-->\n<!-- end\n',
         '  > Read this\n      FFF\n    <pre>\n    <!-- drop this\n<img src="x">\n-->\n<!-- end\n'),
        ('a quote markdown-it reads as code after a fence in a lazy HTML block edited',
         '> Read this\n    <img src="x">\n  <img src="x">\n   FFF\n<!-- note\n\n  -->\n      > Keep this\n',
         '> Read this\n    <img src="x">\n  <img src="x">\n   FFF\n<!-- note\n\n  -->\n      > Drop this\n')]:
    rejects("R3 " + name, src.replace("FFF", "```"), cand.replace("FFF", "```"))
for name, src, cand in [
        ('a heading after a list item comment with a blank line reworded',
         '- Notes.\n  <!-- start\n\n  -->\n# Read the notes.\n',
         '- Notes.\n  <!-- start\n\n  -->\n# See the notes.\n'),
        ('an indented paragraph in a list item both renderers open after definitions reworded',
         '- [docs]: /guide\n[notes]: /notes\n2. Read notes.\nMore details.\n\n    Explain the setup.\n',
         '- [docs]: /guide\n[notes]: /notes\n2. Read notes.\nMore details.\n\n    Describe the setup.\n'),
        ('a heading after an HTML block that ends with its list item reworded',
         '- Outer list.\n  - [docs]: /guide\n  [notes]: /notes\n    ---\n  <img src="logo.png">\n  FFF\n  FFF\n# Read the notes.\n',
         '- Outer list.\n  - [docs]: /guide\n  [notes]: /notes\n    ---\n  <img src="logo.png">\n  FFF\n  FFF\n# See the notes.\n')]:
    accepts("R3 " + name, src.replace("FFF", "```"), cand.replace("FFF", "```"))
started = time.time()
src = ">[a]: x\n><b>\n>- x\n\n" * 4000
accepts("R3 4000 quoted HTML blocks after definitions unchanged", src, src)
report("R3 4000 quoted HTML blocks after definitions checked within two and a half seconds",
       time.time() - started < 2.5, "%.2fs" % (time.time() - started))


# Re-review of c54a348: the open-inline check scans the whole paragraph
# with code spans masked; a paragraph that leaves an inline element open
# is kept with the lines markdown-it continues it on, wherever it does; a
# paragraph of only definitions in a list item records whether a blank
# line closes it (cmark-gfm drops it before deciding looseness); closed
# container regions are read once per container.
for name, src, cand in [
        ('a comment markdown-it reads across lazy HTML lines behind a later tag edited',
         '> Note: <!-- Keep the old logo for now.\n    <img src="logo.png">\n  <img src="fallback.png">\n-->\n',
         '> Note: <!-- Retain the old logo for now.\n    <img src="logo.png">\n  <img src="fallback.png">\n-->\n'),
        ('a code span markdown-it reads across a lazy underline and a list item edited',
         '1. [docs]: /guide\nRead `echo hello\n    ---\n2. echo done`\n',
         '1. [docs]: /guide\nRead `echo world\n    ---\n2. echo done`\n'),
        ('the end of a code span markdown-it reads across a list item edited',
         '1. [docs]: /guide\nRead `echo hello\n2. echo done`\n',
         '1. [docs]: /guide\nRead `echo hello\n2. echo over`\n')]:
    rejects("R3 " + name, src, cand)
rejects("R3 a blank line added after a definition that ends a list item",
        '- Read [the notes][docs].\n\n  [docs]: /guide\n# Next step\n',
        '- Read [the notes][docs].\n\n  [docs]: /guide\n\n# Next step\n', "structure")
for name, src, cand in [
        ('prose with a bracket in a code span before lazy HTML lines reworded',
         '> Use `[` to start a character class.\n    <img src="logo.png">\n  <img src="fallback.png">\n',
         '> Start a character class with `[`.\n    <img src="logo.png">\n  <img src="fallback.png">\n'),
        ('prose with a backtick in a double-backtick code span before lazy HTML lines reworded',
         '> Read ``a ` b`` in this example.\n    <img src="logo.png">\n  <img src="fallback.png">\n',
         '> See ``a ` b`` in this example.\n    <img src="logo.png">\n  <img src="fallback.png">\n'),
        ('a quote before a lazy HTML line reworded',
         '> Read the notes here.\n<img src="logo.png">\n',
         '> See the notes here.\n<img src="logo.png">\n')]:
    accepts("R3 " + name, src, cand)
started = time.time()
src = "- [root]: /root\n[root]: /root\n\n" + "  [docs]: /guide\n[notes]: /notes\n\n" * 1000
accepts("R3 1000 lazy definition paragraphs in one list item unchanged", src, src)
report("R3 1000 lazy definition paragraphs in one list item checked within two seconds",
       time.time() - started < 2.0, "%.2fs" % (time.time() - started))


# Re-review of 3633f10: where markdown-it continues a paragraph past
# cmark-gfm's, the paragraph it reads is compared as a prose unit of its
# own (code spans, raw HTML, emphasis and links as markdown-it groups
# them), which replaces the open-inline heuristic; a blank line after a
# container markdown-it closed is structure; and the reference labels the
# renderers may define must stay the same.
for name, src, cand in [
        ('a code span after an escaped backtick markdown-it reads across a list item edited',
         '1. [docs]: /guide\nType \\` here, then run `echo hello\n2. echo done`\n',
         '1. [docs]: /guide\nType \\` here, then run `echo world\n2. echo done`\n'),
        ('a processing instruction markdown-it reads across a list item edited',
         "1. [docs]: /guide\nPreview: <?php if ($count > 0) echo 'old';\n2. ?>\n",
         "1. [docs]: /guide\nPreview: <?php if ($count > 0) echo 'new';\n2. ?>\n"),
        ('a quoted attribute markdown-it reads across a list item edited',
         '1. [docs]: /guide\nPreview: <span title="More > old\n2. details">note</span>\n',
         '1. [docs]: /guide\nPreview: <span title="More > new\n2. details">note</span>\n'),
        ('emphasis markdown-it reads across a list item broken',
         '1. [docs]: /guide\nRead *the guide\n2. notes* here.\n',
         '1. [docs]: /guide\nRead * the guide\n2. notes* here.\n'),
        ('a blank line added after a quote markdown-it continues past a closed item',
         '- [docs]: /guide\nContinue the setup.\n  > Read the guide.\n> Read the notes.\n',
         '- [docs]: /guide\nContinue the setup.\n  > Read the guide.\n\n> Read the notes.\n'),
        ('a blank line added before a definition markdown-it reads in a quote over indentation',
         'Read [the guide][docs].\n\n> # Next step\n    > [docs]: /guide\n',
         'Read [the guide][docs].\n\n> # Next step\n\n    > [docs]: /guide\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose with an escaped backtick before a list item markdown-it continues reworded',
         '1. [docs]: /guide\nType \\` to start the example.\n2. Continue with the setup.\n',
         '1. [docs]: /guide\nEnter \\` to start the example.\n2. Continue with the setup.\n'),
        ('prose with a bracket in a closed comment before a list item markdown-it continues reworded',
         '1. [docs]: /guide\nRead <!-- Keep [ as written. -->the notes here.\n2. Continue with the setup.\n',
         '1. [docs]: /guide\nSee <!-- Keep [ as written. -->the notes here.\n2. Continue with the setup.\n'),
        ('prose with a bracket in a closed attribute before a list item markdown-it continues reworded',
         '1. [docs]: /guide\nRead <span title="[">the notes</span> here.\n2. Continue with the setup.\n',
         '1. [docs]: /guide\nSee <span title="[">the notes</span> here.\n2. Continue with the setup.\n'),
        ('prose with a backtick in a closed comment before a list item markdown-it continues reworded',
         '1. [docs]: /guide\nRead <!-- Keep ` as written. -->the notes here.\n2. Continue with the setup.\n',
         '1. [docs]: /guide\nSee <!-- Keep ` as written. -->the notes here.\n2. Continue with the setup.\n'),
        ('emphasis markdown-it reads across a list item reworded with its words',
         '1. [docs]: /guide\nRead *the guide\n2. notes* here.\n',
         '1. [docs]: /guide\nSee *the guide\n2. notes* here.\n'),
        # (A line that ends the paragraph for markdown-it too, a quoted
        # blank line or a block inside the paragraph's list item, starts no
        # paragraph of markdown-it's own.)
        ('a blank line moved into the quote after its paragraph',
         '> Read the guide.\n\nSee the notes.\n',
         '> Read the guide.\n>\nSee the notes.\n'),
        ('a nested list item indented further inside its item',
         '- Read the guide.\n  - Read the notes.\n  ```\n  make\n  ```\n',
         '- Read the guide.\n    - Read the notes.\n  ```\n  make\n  ```\n'),
        ('a heading indented further inside its list item',
         '1. Read the guide.\n   # Next step\n   Read the notes.\n',
         '1. Read the guide.\n     # Next step\n   Read the notes.\n')]:
    accepts("R3 " + name, src, cand)


# Found after be7201c by an edit fuzz of the paragraphs markdown-it reads:
# where markdown-it reads a line of cmark-gfm's paragraph outside the
# paragraph's quote or list item (after a definition, a line that does not
# reach the item's content column or lacks the quote marker), the blocks it
# starts there and the containers it closes are structure, and each
# paragraph it reads there is a prose unit of its own.
for name, src, cand in [
        ('a line after a definition in a list item moved short of its content column',
         '1. [docs]: /guide\n   Read the notes.\n',
         '1. [docs]: /guide\n  Read the notes.\n'),
        ('a quote marker added to the line after a quoted definition',
         '> [docs]: /guide\nRead the notes.\n',
         '> [docs]: /guide\n> Read the notes.\n'),
        ('a quote marker removed where markdown-it reopens the quote',
         '> 1. [docs]: /guide\nRead the notes.\n> See the guide.\n',
         '> 1. [docs]: /guide\nRead the notes.\nSee the guide.\n'),
        ('a line after a quoted definition in a list item moved out of the item',
         '- > [docs]: /guide\n  Read the notes.\n',
         '- > [docs]: /guide\n Read the notes.\n'),
        ('a link markdown-it forms where it no longer splits the paragraph',
         '> 1. [docs]: /guide\n   Read [the notes\n> and](/guide) more.\n> See the guide.\n',
         '> 1. [docs]: /guide\n   Read [the notes\n  and](/guide) more.\n> See the guide.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose markdown-it reads outside the list item reworded',
         '1. [docs]: /guide\n  Read the notes.\n',
         '1. [docs]: /guide\n  See the notes.\n'),
        ('prose before the quote markdown-it reopens reworded',
         '> 1. [docs]: /guide\nRead the notes.\n> See the guide.\n',
         '> 1. [docs]: /guide\nRead these notes.\n> See the guide.\n'),
        ('prose markdown-it reads outside the list item rewrapped',
         '1. [docs]: /guide\n  Read the notes\n  and the guide.\n',
         '1. [docs]: /guide\n  Read the notes and the guide.\n'),
        ('prose around a link markdown-it splits reworded',
         '> 1. [docs]: /guide\n   Read [the notes\n> and](/guide) more.\n> See the guide.\n',
         '> 1. [docs]: /guide\n   See [the notes\n> and](/guide) more.\n> See the guide.\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of be7201c: the paragraph units keep trailing whitespace (it may
# be inside a code span), belong to the block that holds their first line
# and are compared also when that block is a definition; markdown-it's
# reading of a paragraph it reads outside its quote or list item is
# structure; a setext underline counts only from the content column of the
# list item markdown-it still reads the paragraph in; which definition of
# a label comes first is compared; indented code markdown-it reads as a
# quote continuation is marked; and a list item outside the paragraph's
# own item ends markdown-it's paragraph there.
for name, src, cand in [
        ('trailing whitespace inside a code span markdown-it reads across a list item removed',
         '1. [docs]: /guide\nRun `echo hello \n2. echo done`\n',
         '1. [docs]: /guide\nRun `echo hello\n2. echo done`\n'),
        ('a code span markdown-it reads after a definition it does not take edited',
         '1. [docs]: /guide\n[local]: file:///guide\nRun `echo hello\n2. echo done`\n',
         '1. [docs]: /guide\n[local]: file:///guide\nRun `echo world\n2. echo done`\n'),
        ('a code span markdown-it reads after a heading it reads in the paragraph edited',
         '1. [docs]: /guide\nExample\n===\nRun `echo hello\n2. echo done`\n',
         '1. [docs]: /guide\nExample\n===\nRun `echo world\n2. echo done`\n'),
        ('a blank line that makes markdown-it take a later definition of the same label',
         'Read [the guide][docs].\n\n> # Next step\n    > [docs]: /guide\n\n[docs]: /fallback\n',
         'Read [the guide][docs].\n\n> # Next step\n\n    > [docs]: /guide\n\n[docs]: /fallback\n'),
        ('a blank line that makes a quote markdown-it continues into code',
         'Read the guide.\n\n> # Next step\n    > Read the notes.\n',
         'Read the guide.\n\n> # Next step\n\n    > Read the notes.\n'),
        ('a paragraph after a definition moved into the list item',
         '- [docs]: /guide\nRead the guide.\n',
         '- [docs]: /guide\n  Read the guide.\n'),
        ('a code span markdown-it reads over an underline short of the outer list item edited',
         '- 1. [docs]: /guide\n  Run `echo hello\n===\n  2. echo done`\n',
         '- 1. [docs]: /guide\n  Run `echo world\n===\n  2. echo done`\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose in separate numbered items with literal asterisks reworded',
         '1. Use *suffix when matching **files**.\n2. Use prefix* for the other pattern.\n',
         '1. When matching **files**, use *suffix.\n2. Use prefix* for the other pattern.\n')]:
    accepts("R3 " + name, src, cand)
started = time.time()
src = "".join("%d. Read the notes.\n" % (k + 1) for k in range(1600))
accepts("R3 1600 numbered list items unchanged", src, src)
report("R3 1600 numbered list items checked within two seconds",
       time.time() - started < 2.0, "took %.2f s" % (time.time() - started))

# (A tag whose quoted attribute value is still open at the line end starts
# no HTML block: both renderers read a paragraph with raw inline HTML.)
for name, src, cand in [
        ('an attribute value continued from a tag line ending in ">" in a list item edited',
         '-   <span title="Next ->\n  old page">next</span> here.\n',
         '-   <span title="Next ->\n  new page">next</span> here.\n'),
        ('an attribute value continued from a tag line ending in ">" edited',
         'Intro.\n\n<span title="Next ->\nold page">next</span> here.\n',
         'Intro.\n\n<span title="Next ->\nnew page">next</span> here.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after an attribute value continued from a tag line in a list item reworded',
         '-   <span title="Next ->\n  old page">next</span> here.\n',
         '-   <span title="Next ->\n  old page">next</span> now.\n'),
        ('prose after an attribute value continued from a tag line reworded',
         'Intro.\n\n<span title="Next ->\nold page">next</span> here.\n',
         'Intro.\n\n<span title="Next ->\nold page">next</span> now.\n')]:
    accepts("R3 " + name, src, cand)

# (Over a list item only cmark-gfm opens, markdown-it measures the lines of
# the paragraph it continues from the column it reads that paragraph at:
# four spaces there start indented code after a heading it reads.)
for name, src, cand in [
        ('code markdown-it reads after a heading across a list item edited',
         '- [docs]: /guide\nRead the guide\n3. More notes\n===\n    make build\n',
         '- [docs]: /guide\nRead the guide\n3. More notes\n===\n    make test\n'),
        ('code markdown-it reads after a heading across a list item in a quote edited',
         '> - [docs]: /guide\n  Read the guide\n3. More notes\n===\n     make build\n',
         '> - [docs]: /guide\n  Read the guide\n3. More notes\n===\n     make test\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose before a heading markdown-it reads across a list item reworded',
         '- [docs]: /guide\nRead the guide\n3. More notes\n===\n    make build\n',
         '- [docs]: /guide\nSee the guide\n3. More notes\n===\n    make build\n')]:
    accepts("R3 " + name, src, cand)


# Re-review of e14f2de: cmark-gfm keeps the whitespace at the start of a
# lazy line inside a span that opened before it; the paragraph of a list
# item only markdown-it opens continues lazily too; how many blocks a
# markdown-it paragraph spans, and what follows a paragraph markdown-it
# reads outside its containers, are structure; a range markdown-it may read
# in any way keeps its quote depths; a list item outside the item
# markdown-it reads the paragraph in ends that paragraph; and the paragraph
# units keep the whitespace markdown-it may keep in a code span.
for name, src, cand in [
        ('a quote marker added to a lazy line inside a multi-line attribute',
         '> <span title="Next ->\n old page">next</span> here.\n',
         '> <span title="Next ->\n>  old page">next</span> here.\n'),
        ('emphasis in a list item only markdown-it opens broken across a lazy HTML line',
         '> [docs]: /guide\n> 2. Read *the guide\n<br>\nnotes* here.\n',
         '> [docs]: /guide\n> 2. Read * the guide\n<br>\nnotes* here.\n'),
        ('a blank line that moves prose out of the paragraph markdown-it continues',
         '> - Read the guide.\n> <br>\nRead the notes.\n',
         '> - Read the guide.\n> <br>\n\nRead the notes.\n'),
        ('a quote line markdown-it reads as a quote after a closed container removed',
         '> [docs]: /guide\nRead the guide.\n>\n',
         '> [docs]: /guide\nRead the guide.\n\n'),
        ('quote markers removed in lines markdown-it may read in any way',
         'Read [the docs][docs].\n\n> > [guide]: /guide\n> Read these notes.\n    2. Read the guide.\n> > [docs]: /guide "Useful title"\n\n[docs]: /fallback\n',
         'Read [the docs][docs].\n\n> > [guide]: /guide\n> Read these notes.\n    2. Read the guide.\n[docs]: /guide "Useful title"\n\n[docs]: /fallback\n'),
        ('whitespace inside a code span markdown-it reads over lazy lines changed',
         '> > [docs]: /guide\n  Read ``echo `alpha here\n     beta~~\n  2. \\`alpha `beta\n',
         '> > [docs]: /guide\n  Read ``echo `alpha here\n    beta~~\n  2. \\`alpha `beta\n'),
        ('an underline indented four columns after markdown-it closed the list item',
         '- [docs]: /guide\nIntro\n===\n  Read the guide\n    ---\n',
         '- [docs]: /guide\nIntro\n===\n  Read the guide\n   ---\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose in a nested list after a definition and a lazy underline reworded',
         '- 1. [docs]: /guide\n  Use *suffix when matching **files**.\n===\n2. Use prefix* for the other pattern.\n',
         '- 1. [docs]: /guide\n  When matching **files**, use *suffix.\n===\n2. Use prefix* for the other pattern.\n'),
        ('prose in a list item only markdown-it opens reworded',
         '> [docs]: /guide\n> 2. Read *the guide\n<br>\nnotes* here.\n',
         '> [docs]: /guide\n> 2. See *the guide\n<br>\nnotes* here.\n'),
        ('prose after a multi-line attribute reworded',
         '> <span title="Next ->\n old page">next</span> here.\n',
         '> <span title="Next ->\n old page">next</span> now.\n'),
        ('the indentation of a prose line markdown-it continues changed',
         '1. [docs]: /guide\nRead the notes\n    and more here.\n2. Next item\n',
         '1. [docs]: /guide\nRead the notes\n  and more here.\n2. Next item\n')]:
    accepts("R3 " + name, src, cand)

# (An underline below a paragraph markdown-it continues over a list item
# only cmark-gfm opens is read from the column markdown-it reads that
# paragraph at: four columns there are lazy text, three an underline.)
for name, src, cand in [
        ('an underline markdown-it reads after a list item it continues indented less',
         '- [docs]: /guide\nRead the guide\n3. More notes\nand words\n    ---\n',
         '- [docs]: /guide\nRead the guide\n3. More notes\nand words\n   ---\n'),
        ('an underline markdown-it reads after a list item it continues indented more',
         '- [docs]: /guide\nRead the guide\n3. More notes\nand words\n   ---\n',
         '- [docs]: /guide\nRead the guide\n3. More notes\nand words\n    ---\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose above an underline markdown-it reads as text reworded',
         '- [docs]: /guide\nRead the guide\n3. More notes\nand words\n    ---\n',
         '- [docs]: /guide\nSee the guide\n3. More notes\nand words\n    ---\n')]:
    accepts("R3 " + name, src, cand)

# (A paragraph markdown-it continues keeps its owner over the list items it
# continues; which lazy lines start inside a code span or raw HTML is
# structure, not only how many; each list item only markdown-it opens is a
# prose unit; a paragraph markdown-it reads outside its item is measured
# from its own column; and an underline outside a quote is read from the
# column of the list item still open there.)
for name, src, cand in [
        ('indented code after a paragraph markdown-it continues over list items changed',
         '- 1. [docs]: /guide\nRead the guide\n  2. Read the notes\n  3. More notes\n===\n    Run old code.\n',
         '- 1. [docs]: /guide\nRead the guide\n  2. Read the notes\n  3. More notes\n===\n    Run new code.\n'),
        ('which line of a multi-line attribute is lazy swapped',
         '> <span title="Read\n these\n>  notes">tip</span> here.\n',
         '> <span title="Read\n>  these\n notes">tip</span> here.\n'),
        ('emphasis in list items only markdown-it opens moved across items',
         '[docs]: /guide\n2. Read *the guide*.\n3. Read *the notes*.\n',
         '[docs]: /guide\n2. Read *the guide.\n3. Read* *the notes*.\n'),
        ('a code span markdown-it continues over an indented HTML line changed',
         '1. [docs]: /guide\nUse `old\n    <div>\ntext` here.\n',
         '1. [docs]: /guide\nUse `new\n    <div>\ntext` here.\n'),
        ('a code span over a lazy underline in an outer list item changed',
         '- > [docs]: /guide\n  Read `old\n===\n  2. text`\n',
         '- > [docs]: /guide\n  Read `new\n===\n  2. text`\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose between separate code spans in a quote reflowed',
         '> Run `alpha` for setup,\n then use `beta` to finish.\n',
         '> For setup, run `alpha`, then use `beta` to finish.\n'),
        ('a blank line added before a heading after a lazy paragraph',
         '> [docs]: /guide\nRead the guide.\n# Next\n',
         '> [docs]: /guide\nSee the guide.\n\n# Next\n'),
        ('prose in list items only markdown-it opens reworded',
         '[docs]: /guide\n2. Read *the guide*.\n3. Read *the notes*.\n',
         '[docs]: /guide\n2. See *the guide*.\n3. Read *the notes*.\n'),
        ('prose after a multi-line attribute with a lazy line reworded',
         '> <span title="Read\n these\n>  notes">tip</span> here.\n',
         '> <span title="Read\n these\n>  notes">tip</span> now.\n'),
        ('prose around a code span over a lazy underline reworded',
         '- > [docs]: /guide\n  Read `old\n===\n  2. text`\n',
         '- > [docs]: /guide\n  See `old\n===\n  2. text`\n')]:
    accepts("R3 " + name, src, cand)

# (A setext underline after markdown-it's lazy paragraph is part of the
# reading shape; which line of which span is lazy is recorded, with code
# spans and raw HTML read from left to right; the indentation of a list
# item only markdown-it opens is structure, and a marker outside its
# column ends its paragraph; a definition cmark-gfm may take at a setext
# underline counts; an unknown range and an underline in a lazy run freeze
# what markdown-it reads after them; a stray backtick, and brackets next to
# code, are markup.)
for name, src, cand in [
        ('a blank line added between a lazy paragraph and an underline after a definition',
         '> [docs]: /guide\nRead the guide.\n---\n',
         '> [docs]: /guide\nRead the guide.\n\n---\n'),
        ('a lazy attribute line swapped while the prose before it is reflowed',
         '> Read this\n> <span title="Read\n these\n>  notes">tip</span> here.\n',
         '> Read this <span title="Read\n>  these\n notes">tip</span> here.\n'),
        ('a quote marker added inside a code span after a tag holding a backtick',
         '> Read <span title="`">the note</span> and `echo\n hello` now.\n',
         '> Read <span title="`">the note</span> and `echo\n>  hello` now.\n'),
        ('a list item only markdown-it opens indented into the item before it',
         '[docs]: /guide\n2. Read the guide.\n3. Read the notes.\n',
         '[docs]: /guide\n2. Read the guide.\n   3. Read the notes.\n'),
        ('the title of a definition cmark-gfm takes at a setext underline changed',
         'See [the reference][r].\n\n- > [a]: /guide\n  [r]: file:///guide "Old title"\n  > ===\n',
         'See [the reference][r].\n\n- > [a]: /guide\n  [r]: file:///guide "New title"\n  > ===\n'),
        ('a code span markdown-it continues after an unknown line changed',
         '- 1. [docs]: /guide\n    Run `echo\n  2. old` now.\n',
         '- 1. [docs]: /guide\n    Run `echo\n  2. new` now.\n'),
        ('indented code after an underline that ends a lazy run changed',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n    Run old code.\n',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n    Run new code.\n'),
        ('the indentation of a list marker only markdown-it reads changed',
         '[docs]: /guide\n2. # guide*\n   ===\n3. Use `a\n4. # guide*\n',
         '[docs]: /guide\n 2. # guide*\n   ===\n3. Use `a\n4. # guide*\n'),
        ('an underline after a paragraph that a list marker outside its item ends changed',
         '[docs]: /guide\n2. b` here\n3. # Read *the\n   more words\n4. notes* here.\n---\n',
         '[docs]: /guide\n2. b` here\n3. # Read *the\n   more words\n4. notes* here.\n--\n'),
        ('the indentation of an underline below a heading item changed',
         '[docs]: /guide\n2. Read <span title="a\n3. # Read *the\n   ===\n4. notes* here.\n===\n',
         '[docs]: /guide\n2. Read <span title="a\n3. # Read *the\n===\n   4. notes* here.\n===\n'),
        ('a paragraph moved out of a list item only markdown-it opens',
         '[docs]: /guide\n2. # guide*\n3. Read *the guide*.\n4. plain words\n5. # guide*\n   c` end\n',
         '[docs]: /guide\n2. # guide*\n3. Read *the guide*.\n4. plain words\n5. # guide*\n c` end\n'),
        ('a code span word changed where markdown-it reads past nested quotes',
         '- > > [docs]: /guide\nRead ``echo `alpha\n      ---\n    2. text`\n',
         '- > > [docs]: /guide\nRead ``echo `zeta\n      ---\n    2. text`\n'),
        ('whitespace inside a code span after an underline below a heading item changed',
         '1. [docs]: /guide\n   2. # Read *the\n   ===\n   3. Read *the guide*.\n   4. b` here\n   5. Read *the guide\n   c` end\n',
         '1. [docs]: /guide\n   2. # Read *the\n   ===\n   3. Read *the guide*.\n   4. b` here\n   5. Read *the guide\n    c` end\n'),
        ('a stray backtick removed after an unclosed bracket',
         'Read [alpha `a` and `b x\n',
         'Read [alpha `a` and b x\n'),
        ('a bracket added before code spans',
         '> > Read <!-- alpha here\n> >  beta">x</a>\n> more beta` then `c` words\n',
         '> > Read <!-- alpha here\n> >  beta"[x</a>\n> more beta` then `c` words\n'),
        ('whitespace inside a code span of a paragraph markdown-it reads after list items',
         '[docs]: /guide\n2. Read *the guide*.\nc` end\n3. # guide*\nc` end\n4. # guide*\n5. Read *the guide*.\nc` end\n',
         '[docs]: /guide\n2. Read *the guide*.\nc` end\n3. # guide*\nc` end\n4. # guide*\n 5. Read *the guide*.\nc` end\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose reflowed before a code span with a lazy line',
         '> Read these notes and use\n> the command `echo\n hello` to proceed.\n',
         '> Read these notes\n> and use\n> the command `echo\n hello` to proceed.\n'),
        ('prose reflowed after a closed code span holding a tag start',
         '> Use `<span` to start,\n then follow the guide.\n',
         '> Use `<span` to start, then follow the guide.\n'),
        ('emphasis moved with its words over a numbered line markdown-it keeps in the item',
         '[docs]: /guide\n2. For *the guide*, see section\n   3. before starting.\n',
         '[docs]: /guide\n2. See section\n   3. of *the guide* before starting.\n'),
        ('prose before an underline after a definition reworded',
         '> [docs]: /guide\nRead the guide.\n---\n',
         '> [docs]: /guide\nSee the guide.\n---\n'),
        ('prose around a definition cmark-gfm takes at an underline reworded',
         'See [the reference][r].\n\n- > [a]: /guide\n  [r]: file:///guide "Old title"\n  > ===\n',
         'Read [the reference][r].\n\n- > [a]: /guide\n  [r]: file:///guide "Old title"\n  > ===\n'),
        ('prose of a heading markdown-it reads over a heading item reworded',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n    Run old code.\n',
         '> [docs]: /guide\nSee the guide\n2. # Notes\n===\n    Run old code.\n'),
        ('prose next to a stray backtick reworded',
         'Use `a` and `b x here.\n',
         'See `a` and `b x here.\n')]:
    accepts("R3 " + name, src, cand)

# (Code spans, raw HTML, autolinks and link tails are read from left to
# right in CommonMark's precedence, also for the protected tokens; a tag
# has no length limit; in a list item, the content column is structure for
# a paragraph whose code span, raw HTML or link title spans lines; which
# later lines reach the column of a list item only markdown-it opens is
# structure; the lines after an unknown range are a markdown-it unit, and
# after a lazy run's underline only the lines markdown-it reads as code are
# kept byte for byte; brackets count next to a stray backtick only.)
LONG_IMG = '> See <img src="data:image/png;base64,' + 'A' * 20000 + '" title="Read\n these notes"> here.\n'
for name, src, cand in [
        ('a quote marker added inside the title of a tag longer than 20,000 characters',
         LONG_IMG, LONG_IMG.replace('\n these', '\n>  these')),
        ('code after a tag whose attribute holds a backtick changed',
         'Read <span title="`">the note</span> and `echo old` now.\n',
         'Read <span title="`">the note</span> and `echo new` now.\n'),
        ('code after a comment that holds a backtick changed',
         'Read <!-- Type ` to begin --> and `echo old` now.\n',
         'Read <!-- Type ` to begin --> and `echo new` now.\n'),
        ('a quote marker added inside a code span after a link title holding a backtick',
         '> Read [the note](guide "a `") and `echo\n hello` now.\n',
         '> Read [the note](guide "a `") and `echo\n>  hello` now.\n'),
        ('a quote marker added inside a multi-line link title',
         '> Read [the note](guide "old\n title") now.\n',
         '> Read [the note](guide "old\n>  title") now.\n'),
        ('a list marker indented less where a code span spans the item lines',
         '  4. Run `echo\n     hello` now.\n',
         ' 4. Run `echo\n     hello` now.\n'),
        ('a heading moved out of an empty list item only markdown-it opens',
         '[docs]: /guide\n2.\n   # Notes\n',
         '[docs]: /guide\n2.\n # Notes\n'),
        ('a quote line indented into a list item only markdown-it opens',
         '[docs]: /guide\n2. # Notes\n   > Read the notes.\n     <!-- comment -->\n  > 3. Use echo\n',
         '[docs]: /guide\n2. # Notes\n   > Read the notes.\n     <!-- comment -->\n      3. Use echo\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after an unknown range reworded',
         '- 1. [docs]: /guide\n    Read the guide.\n  2. The notes explain everything.\n',
         '- 1. [docs]: /guide\n    Read the guide.\n  2. The notes cover everything.\n'),
        ('prose after the underline of a lazy run reworded',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\nRead these notes carefully.\n',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\nRead these notes closely.\n'),
        ('a literal bracket next to code spelled out',
         'Use `check`; the prompt ends with [ to request more input.\n',
         'Use `check`; the prompt ends with an opening square bracket to request more input.\n'),
        ('prose around code after a tag holding a backtick reworded',
         'Read <span title="`">the note</span> and `echo old` now.\n',
         'See <span title="`">the note</span> and `echo old` now.\n'),
        ('prose in a list item whose code span spans its lines reworded',
         '  4. Run `echo\n     hello` now.\n',
         '  4. Use `echo\n     hello` now.\n')]:
    accepts("R3 " + name, src, cand)
for name, src in [('unclosed comment openers', 'See ' + '<!-- a ' * 8000 + '\n'),
                  ('unclosed processing instruction openers', 'See ' + '<? a ' * 8000 + '\n')]:
    started = time.time()
    accepts("R3 8000 %s unchanged" % name, src, src)
    report("R3 8000 %s checked within two seconds" % name,
           time.time() - started < 2.0, "took %.2f s" % (time.time() - started))

# (A text that reads in two ways, a reference label that may or may not be
# defined or a link that only cmark-gfm takes, has the code, raw HTML,
# autolinks and link tails of each reading protected; which blocks after a
# list item only markdown-it opens are inside it is structure block by
# block, and a fence markdown-it opens where the item ends is kept byte for
# byte; a lazy run after an unknown range is read from the content column
# of the list item that survives; after a lazy run's underline, what
# markdown-it reads before a paragraph starts is kept byte for byte; a
# malformed tag with a long whitespace run is matched in linear time.)
for name, src, cand in [
        ('code in parentheses after a full reference link changed',
         'See [the option][docs](`old`) for details.\n\n[docs]: /guide\n',
         'See [the option][docs](`new`) for details.\n\n[docs]: /guide\n'),
        ('code in parentheses after a collapsed reference link changed',
         'See [docs][](`old`) for details.\n\n[docs]: /guide\n',
         'See [docs][](`new`) for details.\n\n[docs]: /guide\n'),
        ('code after an undefined reference whose link title holds a backtick changed',
         'Read [the note][x](guide "a `") and `echo old` now.\n',
         'Read [the note][x](guide "a `") and `echo new` now.\n'),
        ('words markdown-it reads as code after a link it refuses changed',
         'See [local help](file:///tmp/help.html "Use ` for commands") and `open` then `close`.\n',
         'See [local help](file:///tmp/help.html "Use ` for commands") and `open` next `close`.\n'),
        ('code after an autolink markdown-it refuses changed',
         'Open <file:///a`b> and `echo old` now.\n',
         'Open <file:///a`b> and `echo new` now.\n'),
        ('a heading moved out of a list item only markdown-it opens, before another',
         '[docs]: /guide\n2.\n   # First\n   # Second\n # Last\n',
         '[docs]: /guide\n2.\n   # First\n # Second\n # Last\n'),
        ('an underline moved out of a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   Title\n   ===\n',
         '[docs]: /guide\n2.\n   Title\n===\n'),
        ('a line after a fence that leaves a list item only markdown-it opens changed',
         '[docs]: /guide\n2.\n   ```text\n   Keep these notes.\n```\nRead old notes.\n',
         '[docs]: /guide\n2.\n   ```text\n   Keep these notes.\n```\nRead new notes.\n'),
        ('a line after fence content that leaves such a list item changed',
         '[docs]: /guide\n2.\n   ```\n   code\nfoo\n```\nRead old notes.\n',
         '[docs]: /guide\n2.\n   ```\n   code\nfoo\n```\nRead new notes.\n'),
        ('indented code after an underline in a surviving outer list item changed',
         '- 1. [docs]: /guide\n    Read the guide.\n  2. The notes explain everything.\n     ---\n      echo old\n',
         '- 1. [docs]: /guide\n    Read the guide.\n  2. The notes explain everything.\n     ---\n      echo new\n'),
        ('a heading in a surviving outer list item indented into the paragraph',
         '- 1. [docs]: /guide\n    Read the guide.\n  2. The notes explain everything.\n     # Notes\n',
         '- 1. [docs]: /guide\n    Read the guide.\n  2. The notes explain everything.\n      # Notes\n'),
        ('a definition after the underline of a lazy run changed',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n[ref]: old\nRead the notes.\n\nSee [ref].\n',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n[ref]: new\nRead the notes.\n\nSee [ref].\n'),
        ('a reference to a definition after the underline of a lazy run reworded',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n[ref]: old\nRead the notes.\n\nSee [ref].\n',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n[ref]: old\nRead the notes.\n\nSee [the ref].\n'),
        ('an HTML block after the underline of a lazy run changed',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n<span>\nRead old notes.\n',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n<span>\nRead new notes.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a full reference link reworded',
         'See [the option][docs](`old`) for details.\n\n[docs]: /guide\n',
         'See [the option][docs](`old`) to learn more.\n\n[docs]: /guide\n'),
        ('prose before an autolink markdown-it refuses reworded',
         'Open <file:///a`b> and `echo old` now.\n',
         'See <file:///a`b> and `echo old` now.\n'),
        ('prose under an underline in a surviving outer list item reworded',
         '- 1. [docs]: /guide\n    Read the guide.\n  2. The notes explain everything.\n   ---\n     Read old notes.\n',
         '- 1. [docs]: /guide\n    Read the guide.\n  2. The notes explain everything.\n   ---\n     Read new notes.\n'),
        ('an indented continuation after prose under a lazy underline reworded',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\nRead these notes.\n    Continue with care.\n',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\nRead these notes.\n    Continue with caution.\n'),
        ('a paragraph in a list item only markdown-it opens rewrapped lazily',
         '[docs]: /guide\n2.\n   # Notes\n   Read these notes carefully.\n',
         '[docs]: /guide\n2.\n   # Notes\n   Read these notes\ncarefully.\n'),
        ('prose after a definition after the underline of a lazy run reworded',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n[ref]: old\nRead the notes.\n\nSee [ref].\n',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n[ref]: old\nRead these notes.\n\nSee [ref].\n')]:
    accepts("R3 " + name, src, cand)
for k in (2000, 20000):
    src = 'See <a ' + ' ' * k + '\n'
    started = time.time()
    accepts("R3 a malformed tag with %d spaces unchanged" % k, src, src)
    report("R3 a malformed tag with %d spaces checked within two seconds" % k,
           time.time() - started < 2.0, "took %.2f s" % (time.time() - started))

# (Inside a list item only markdown-it opens, a quote holding a heading
# continues no paragraph, a block that starts in the item's column ends the
# item's paragraph, and a fence or HTML block opened in the item keeps the
# lines it holds after cmark-gfm's paragraph; an empty such item right after
# a definition is tracked too; where it ends, markdown-it's fence, HTML
# block or indented code is measured from the list item around it and ends
# with it; every lazy run is read from the column of the list item
# markdown-it reads it in; a reference label is consumed without a link
# tail too, and span records resolve labels against the document; the
# stray-backtick rule holds in every reading.)
for name, src, cand in [
        ('a paragraph after a quoted heading moved out of a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > # Notes\n   Read these notes.\n',
         '[docs]: /guide\n2.\n   > # Notes\n  Read these notes.\n'),
        ('indented code after an underline of a paragraph read in an outer list item changed',
         '- 1. [docs]: /guide\n  Read the guide.\n  2. # Notes\n    ===\n      echo old\n',
         '- 1. [docs]: /guide\n  Read the guide.\n  2. # Notes\n    ===\n      echo new\n'),
        ('a fence content line after a nested item exit changed',
         '100. [docs]: /guide\n     2.\n        ```text\n        Keep these notes.\n     ```\n     Read old notes.\n\n     More old notes.\n',
         '100. [docs]: /guide\n     2.\n        ```text\n        Keep these notes.\n     ```\n     Read old notes.\n\n     More new notes.\n'),
        ('code after a full reference whose label holds a backtick changed',
         'See [the backtick][`] and `echo old` now.\n\n[`]: /syntax\n',
         'See [the backtick][`] and `echo new` now.\n\n[`]: /syntax\n'),
        ('a line of an HTML block in a list item only markdown-it opens changed',
         '[docs]: /guide\n2.\n   <img src="diagram.svg">\n   # Read old notes.\n',
         '[docs]: /guide\n2.\n   <img src="diagram.svg">\n   # Read new notes.\n'),
        ('a quote-only line added to an HTML block after a lazy underline',
         '> > [docs]: /guide\nRead the guide\n2. # Notes\n===\n    Continue with care.\n<span>\n> old "title"\n\nSee [ref].\n',
         '> > [docs]: /guide\nRead the guide\n2. # Notes\n===\n    Continue with care.\n<span>\n> old "title"\n> \nSee [ref].\n'),
        ('a bracket added before a link markdown-it refuses, next to a stray backtick in its reading',
         '1. See [the option][ref](file:///a "` t") then `a` and `b`.\n',
         '1. See[[the option][ref](file:///a "` t") then `a` and `b`.\n'),
        ('code indentation after a heading in a surviving outer list item changed',
         '- 1. [docs]: /guide\n    Read the guide.\n  2. The notes explain everything.\n     # Notes\n      ===\n <span>\n',
         '- 1. [docs]: /guide\n    Read the guide.\n  2. The notes explain everything.\n     # Notes\n       ===\n <span>\n'),
        ('a heading moved out of a fence in a list item only markdown-it opens',
         '> [docs]: /guide\n> 2.\n>    echo old\n>     ~~~\n>    # Heading\n> [ref]: old\n',
         '> [docs]: /guide\n> 2.\n>    echo old\n>     ~~~\n>   # Heading\n> [ref]: old\n'),
        ('a nested list moved out of an empty list item only markdown-it opens',
         '- [docs]: /guide\n  2.\n      ---\n     - item\n     ---\n',
         '- [docs]: /guide\n  2.\n      ---\n    - item\n     ---\n'),
        ('a nested list in a list item only markdown-it opens turned into text',
         '- [docs]: /guide\n  3. # Notes\n     echo old\n      - item\n    # Heading\n',
         '- [docs]: /guide\n  3. # Notes\n     echo old\n     "- item\n    # Heading\n'),
        ('a line after a fence that leaves a list item only markdown-it opens, after a fence of its own',
         '[docs]: /guide\n3. # Notes\n   ```text\n   ---\n```\n\nSee [ref] and old words.\n',
         '[docs]: /guide\n3. # Notes\n   ```text\n   ---\n```\n\nSee [ref] and new words.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('a paragraph after an inline link with a backtick in its title rewrapped',
         '> Read [the note][x](guide "a `") carefully and `echo old` now.\n',
         '> Read [the note][x](guide "a `") carefully\n and `echo old` now.\n'),
        ('prose after a fence that leaves a list item only markdown-it opens, outside the outer item',
         '- [docs]: /guide\n  2.\n     ```text\n     Keep these notes.\n  ```\nRead old notes.\n',
         '- [docs]: /guide\n  2.\n     ```text\n     Keep these notes.\n  ```\nRead new notes.\n'),
        ('prose around a full reference whose label holds a backtick reworded',
         'See [the backtick][`] and `echo old` now.\n\n[`]: /syntax\n',
         'Read [the backtick][`] and `echo old` now.\n\n[`]: /syntax\n'),
        ('a paragraph after a quoted paragraph in a list item only markdown-it opens reworded',
         '[docs]: /guide\n2.\n   > Some notes\n   Read these notes.\n',
         '[docs]: /guide\n2.\n   > Some notes\n   Read the notes.\n')]:
    accepts("R3 " + name, src, cand)

# (Re-review of fbf4735: a quote line short of a list item only markdown-it
# opens ends the item unless it continues a paragraph lazily, and a lazy
# line there ends the paragraph at a block start at any indentation; a
# quote continues lazily only when it holds a paragraph; the lines a fence
# or HTML block holds are kept line by line, inside another block too and
# on a blank line; the label resolver reads labels past quote markers;
# exits inside lines read already are not walked again; and an HTML block
# closed on its first line ends there.)
for name, src, cand in [
        ('a paragraph after a lazy underline moved out of its outer list item',
         '- > [docs]: /guide\n  Read the guide\n  2. # Notes\n  ===\n    Read these notes.\n',
         '- > [docs]: /guide\n  Read the guide\n  2. # Notes\n  ===\nRead these notes.\n'),
        ('a quote moved into a nested list item only markdown-it opens',
         '- [docs]: /guide\n  2. Read these notes.\n    > First note.\n     > Second note.\n',
         '- [docs]: /guide\n  2. Read these notes.\n     > First note.\n     > Second note.\n'),
        ('a paragraph after a quoted HTML comment moved out of a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > <!-- note -->\n   Read these notes.\n',
         '[docs]: /guide\n2.\n   > <!-- note -->\n  Read these notes.\n'),
        ('fence content inside a quoted paragraph cmark-gfm reads changed',
         '[docs]: /guide\n2.\n   > A quoted note.\n    ```text\n    echo old\n',
         '[docs]: /guide\n2.\n   > A quoted note.\n    ```text\n    echo new\n'),
        ('whitespace added to a blank line in a fence that only markdown-it opens after an HTML block',
         '- [docs]: /guide\n  2. Read\n   Read the notes.\n    > quoted\n   <span>\n      echo old\n  ~~~\n\nSee [ref] and old words.\n',
         '- [docs]: /guide\n  2. Read\nRead the notes.\n    > quoted\n   <span>\n      echo old\n  ~~~\n   \nSee [ref] and old words.\n'),
        ('a quote-only line added to an exit fence with no block of its own',
         '> [docs]: /guide\n> 3. # Notes\n>    ```text\n> # Heading\n>    ```\n\n<div>\nNote.\n</div>\n',
         '> [docs]: /guide\n> 3. # Notes\n>    ```text\n> # Heading\n>    ```\n> \n<div>\nNote.\n</div>\n'),
        ('code whitespace after a reference whose quoted label continues on a quote line changed',
         '> See [the key][backtick ` key] and `echo\n>  old` now.\n\n> [backtick\n> ` key]: /syntax\n',
         '> See [the key][backtick ` key] and `echo\n old` now.\n\n> [backtick\n> ` key]: /syntax\n'),
        ('a quote marker removed from a line after a lazy underline in a quote',
         '> > [docs]: /guide\n> Read the guide\n> 2. # Notes\n> ===\n>   Continue with care.\n>   old "title"\n>\n> - [docs]: /guide\n>   3. # Notes\n>     [ref]: old\n>       [ref]: old\n>\n> See [ref] and old words.\n>\n> ```\n> old\n> ```\n',
         '> > [docs]: /guide\n> Read the guide\n> 2. # Notes\n> ===\n<   Continue with care.\n>   old "title"\n>\n> - [docs]: /guide\n>   3. # Notes\n>     [ref]: old\n>       [ref]: old\n>\n> See [ref] and old words.\n>\n> ```\n> old\n> ```\n'),
        ('a paragraph after a lazy underline in a nested list moved out of its item',
         '- - See [Docs](<x`>) for details.\n\n  - > [docs]: /guide\n  Read the guide\n  2. # Notes\n   ===\n    Continue with care.\n  > [ref]: old\n\n  See [ref].\n',
         '- - See [Docs](<x`>) for details.\n    \n  - > [docs]: /guide\n  Read the guide\n  2. # Notes\n   ===\nContinue with care.\n  > [ref]: old\n\n  See [ref].\n'),
        ('a quote marker removed from a fence after a doubled underline in a quoted list item',
         '> > [docs]: /guide\n> > 2.  Text\n> >    ===\n> >   ===\n> >     Read the notes.\n> >     ```\n> > echo old\n',
         '> > [docs]: /guide\n> > 2.  Text\n> >    ===\n> >   ===\n> >     Read the notes.\n>     ```\n> > echo old\n'),
        ('a definition after a lazy underline moved out of its outer list item',
         '- > [docs]: /guide\n  Read the guide\n  2. # Notes\n   ===\n  [ref]:\n  [ref]: old\n\n  See [ref].\n',
         '- > [docs]: /guide\n  Read the guide\n  2. # Notes\n   ===\n [ref]:\n  [ref]: old\n\n  See [ref].\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('a paragraph after a lazy underline reworded in its outer list item',
         '- > [docs]: /guide\n  Read the guide\n  2. # Notes\n  ===\n    Read these notes.\n',
         '- > [docs]: /guide\n  Read the guide\n  2. # Notes\n  ===\n    Consult these notes.\n'),
        ('prose after an HTML comment closed on its line in a list item only markdown-it opens',
         '[docs]: /guide\n2. Read the guide.\n   <!-- note -->\n   Read these notes.\n',
         '[docs]: /guide\n2. Read the guide.\n   <!-- note -->\n   Consult these notes.\n'),
        ('prose after a pre block closed on its line in a list item only markdown-it opens',
         '[docs]: /guide\n2. Read the guide.\n   <pre>keep</pre>\n   Read these notes.\n',
         '[docs]: /guide\n2. Read the guide.\n   <pre>keep</pre>\n   Consult these notes.\n'),
        ('prose after a script block closed on its line in a list item only markdown-it opens',
         '[docs]: /guide\n2. Read the guide.\n   <script>keep</script>\n   Read these notes.\n',
         '[docs]: /guide\n2. Read the guide.\n   <script>keep</script>\n   Consult these notes.\n'),
        ('prose in a quoted paragraph before a fence in a list item only markdown-it opens reworded',
         '[docs]: /guide\n2.\n   > A quoted note.\n    ```text\n    echo old\n',
         '[docs]: /guide\n2.\n   > A short quoted note.\n    ```text\n    echo old\n'),
        ('a quote marker indented one more column inside an outer list item, after a lazy line',
         '1. > - [docs]: /guide\n   >   2. Read\n   >    Keep old notes.\n   >       Read the notes.\n',
         '1. > - [docs]: /guide\n   >   2. Read\n   >    Keep old notes.\n    >       Read the notes.\n'),
        ('a quote marker indented one more column inside an outer list item, before a definition',
         '1. > - [docs]: /guide\n   >   2.  Text\n   >       <span>\n   >      [ref]: old\n',
         '1. > - [docs]: /guide\n   >   2.  Text\n   >       <span>\n    >      [ref]: old\n'),
        ('a quote marker indented one column on a fence line kept in a list item only markdown-it opens',
         '> [docs]: /guide\n> 2.\n>   <span>\n>     ```\n> # Heading\n>     ```text\n>     > quoted\n\nSee [ref] and old words.\n',
         '> [docs]: /guide\n> 2.\n>   <span>\n >     ```\n> # Heading\n>     ```text\n>     > quoted\n\nSee [ref] and old words.\n'),
        ('a quote marker indented one column on an HTML line kept in a list item only markdown-it opens',
         '> [docs]: /guide\n> 2.\n>  <span>\n>   [ref]: old\n>  Read the notes.\n',
         '> [docs]: /guide\n> 2.\n >  <span>\n>   [ref]: old\n>  Read the notes.\n'),
        ('whitespace added to a blank line after text markdown-it continues lazily over a fence-like line',
         '- [docs]: /guide\n  2.  Text\n   - item\n    # Heading\n  Keep old notes.\n  [ref]: old\n      ```\n\nSee [ref] and old words.\n',
         '- [docs]: /guide\n  2.  Text\n   - item\n    # Heading\n  Keep old notes.\n  [ref]: old\n      ```\n \nSee [ref] and old words.\n'),
        ('whitespace added to a blank line after indented code markdown-it reads after a closed fence',
         '- [docs]: /guide\n  2.\n    ```\n  ```\n      <span>\n\n> Read the notes.\n',
         '- [docs]: /guide\n  2.\n    ```\n  ```\n      <span>\n \n> Read the notes.\n')]:
    accepts("R3 " + name, src, cand)

EXITS = "[docs]: /guide\n2.\n   ```\n   notes\n```\n\n" * 800
started = time.time()
accepts("R3 800 repeated item exit fences unchanged", EXITS, EXITS)
report("R3 800 repeated item exit fences checked within two seconds", time.time() - started < 2.0,
       "%.2fs" % (time.time() - started))

# (Re-review of d31cc76: kept lines strip only the quote markers of the
# container markdown-it reads them in and keep their bytes, as runs that may
# move with the prose before them; the item walk follows a fence, HTML block
# or definition-like paragraph inside the item's quote, and records where
# the item ends (the line's kind, quote depth and reach of the list item
# around it); blank lines inside markdown-it's indented code after a
# definition are kept; and a lazy run records where the line that ends it
# stands against its list item's column.)
for name, src, cand in [
        ('a literal quote marker in a fence in a quoted list item only markdown-it opens lost its space',
         '> [docs]: /guide\n> 2.\n>     ~~~\n>    > quoted\n',
         '> [docs]: /guide\n> 2.\n>     ~~~\n>    >quoted\n'),
        ('a tab in fence content after a quoted paragraph replaced with spaces',
         '[docs]: /guide\n2.\n   > A quoted note.\n    ```text\n    \techo old\n',
         '[docs]: /guide\n2.\n   > A quoted note.\n    ```text\n        echo old\n'),
        ('a paragraph after a quoted HTML comment over two lines moved out of a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > <!-- note\n   > more notes -->\n   Read these notes.\n',
         '[docs]: /guide\n2.\n   > <!-- note\n   > more notes -->\n  Read these notes.\n'),
        ('a paragraph after a quoted definition over two lines moved out of a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > [a]:\n   > /url\n   Read these notes.\n',
         '[docs]: /guide\n2.\n   > [a]:\n   > /url\n  Read these notes.\n'),
        ('a paragraph after a quoted setext heading moved out of a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > Title\n   > ===\n   Read these notes.\n',
         '[docs]: /guide\n2.\n   > Title\n   > ===\n  Read these notes.\n'),
        ('a quote marker added to the line where a list item only markdown-it opens ends',
         '[docs]: /guide\n3. # Notes\n   > quoted\nRead the notes.\n# Heading\n',
         '[docs]: /guide\n3. # Notes\n   > quoted\n> Read the notes.\n# Heading\n'),
        ('the line that ends a list item only markdown-it opens moved out of the outer list item',
         '- [docs]: /guide\n  3. # Notes\n     > quoted\n      ```\n  Read the notes.\n',
         '- [docs]: /guide\n  3. # Notes\n     > quoted\n      ```\n Read the notes.\n'),
        ('whitespace added to a blank line inside indented code markdown-it reads after a definition',
         '[docs]: /guide\n    echo old\n\n    more old\n',
         '[docs]: /guide\n    echo old\n     \n    more old\n'),
        ('a heading after a lazy HTML line moved out of its nested list item by the marker indentation',
         '- 1. Read the guide.\n  2. The notes explain everything.\n   <span>\n     # Notes\n',
         '- 1. Read the guide.\n   2. The notes explain everything.\n   <span>\n     # Notes\n'),
        ('a space removed after a literal quote marker in an HTML block markdown-it reads after an empty item',
         '> > [docs]: /guide\nRead the guide\n2. # Notes\n===\n  echo old\n    echo old\necho old\n\nSee [ref].\n\n[docs]: /guide\n2.\n  <span>\n    - item\n  > quoted\n    ~~~\n [ref]: old\n\nSee [ref] and old words.\n\t\n<!-- note\nold -->\n',
         '> > [docs]: /guide\nRead the guide\n2. # Notes\n===\n  echo old\n    echo old\necho old\n\nSee [ref].\n\n[docs]: /guide\n2.\n  <span>\n    - item\n  >quoted\n    ~~~\n [ref]: old\n\nSee [ref] and old words.\n\t\n<!-- note\nold -->\n'),
        ('a paragraph after a lazy HTML line moved into the list item markdown-it continues',
         '- item\n <span>\n\nSee words.\n',
         '- item\n <span>\n\n  See words.\n'),
        ('a paragraph moved into a list item after an empty item and a lazy HTML line',
         '[docs]: /guide\n2.\n  - item\n <span>\n\nSee [ref] and old words.\n',
         '[docs]: /guide\n2.\n- item\n <span>\n\n  See [ref] and old words.\n'),
        ('a quote marker moved below a definition after a lazy underline',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n    <span>\n  [ref]: old\n> old "title"\necho old\n',
         '> [docs]: /guide\nRead the guide\n2. # Notes\n===\n    <span>\n  [ref]: old\nold "title"\n> echo old\n'),
        ('the spaces after the marker of a list item before a lazy HTML line widened',
         '- 1. [docs]: /guide\n     Read the guide.\n  2. The notes explain everything.\n  <span>\n    echo old\n     # Notes\n',
         '- 1. [docs]: /guide\n     Read the guide.\n  2.  The notes explain everything.\n  <span>\n    echo old\n     # Notes\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('whitespace added to a blank line after indented code markdown-it reads after a definition',
         '[docs]: /guide\n    echo old\n\nmore old\n',
         '[docs]: /guide\n    echo old\n     \nmore old\n'),
        ('prose rewrapped before a fence kept in a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > A quoted note with several ordinary words.\n    ```text\n    echo old\n',
         '[docs]: /guide\n2.\n   > A quoted note with\n   > several ordinary words.\n    ```text\n    echo old\n'),
        ('definition-like prose in a quote rewrapped in a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > [Warning]: Please read these notes carefully.\n   Continue with care.\n',
         '[docs]: /guide\n2.\n   > [Warning]: Please read these\n   > notes carefully.\n   Continue with care.\n'),
        ('a paragraph after a lazy HTML line reworded outside the list item',
         '- item\n <span>\n\nSee words.\n',
         '- item\n <span>\n\nRead words.\n'),
        ('a paragraph after a lazy HTML line reworded inside the list item',
         '- item\n <span>\n\n  See words.\n',
         '- item\n <span>\n\n  Read words.\n'),
        ('a nested marker indented one more column with a heading that stays in its item',
         '- 1. [docs]: /guide\n     Read the guide.\n  2. The notes explain everything.\n    <span>\n      # Notes\n',
         '- 1. [docs]: /guide\n     Read the guide.\n   2. The notes explain everything.\n    <span>\n      # Notes\n'),
        ('a quote marker indented one more column inside an outer list item after a lazy run',
         '1. > - 1. [docs]: /guide\n   >    Read the guide.\n   >   2. The notes explain everything.\n   >   Read old notes.\n   >  ```\n',
         '1. > - 1. [docs]: /guide\n   >    Read the guide.\n   >   2. The notes explain everything.\n    >   Read old notes.\n   >  ```\n'),
        ('a thematic break indented one more column after a lazy run in a nested list',
         '1. [docs]: /guide\n   2. b">x</span>\n3. b">x</span>\n   ---\n',
         '1. [docs]: /guide\n   2. b">x</span>\n3. b">x</span>\n    ---\n')]:
    accepts("R3 " + name, src, cand)

# (Re-review of 1866a46: a paragraph in a quote that starts like a
# definition is read with the markdown-it walk also after the definition
# (its title may follow); a quoted fence or HTML block ends with its quote;
# the line after a lazy underline records which of the columns of the list
# items around it it reaches; and an inline link right after a label that
# may be defined is a label after it, so a shortcut reference cannot be
# made by adding a space.)
for name, src, cand in [
        ('a paragraph after a quoted definition with its title on the next line moved out of a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > [a]: /url\n   > "Guide title"\n   Read these notes.\n',
         '[docs]: /guide\n2.\n   > [a]: /url\n   > "Guide title"\n  Read these notes.\n'),
        ('a paragraph after a quoted definition with a title over two lines moved out of a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > [a]: /url\n   > "Guide\n   > title"\n   Read these notes.\n',
         '[docs]: /guide\n2.\n   > [a]: /url\n   > "Guide\n   > title"\n  Read these notes.\n'),
        ('a paragraph after a lazy underline moved out of the surviving outer list item',
         '- Outer item.\n  - Procedure.\n    1. [docs]: /guide\n     Read the guide.\n    2. The notes explain everything.\n     ===\n  Continue with care.\n',
         '- Outer item.\n  - Procedure.\n    1. [docs]: /guide\n     Read the guide.\n    2. The notes explain everything.\n     ===\n Continue with care.\n'),
        ('a space added between a defined label and an inline link, which makes the label a shortcut reference',
         'See [docs][reference](/reference) for details.\n\n[docs]: /guide\n',
         'See [docs] [reference](/reference) for details.\n\n[docs]: /guide\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a lazy underline reworded in the surviving outer list item',
         '- Outer item.\n  - Procedure.\n    1. [docs]: /guide\n     Read the guide.\n    2. The notes explain everything.\n     ===\n  Continue with care.\n',
         '- Outer item.\n  - Procedure.\n    1. [docs]: /guide\n     Read the guide.\n    2. The notes explain everything.\n     ===\n  Go on with care.\n'),
        ('prose reworded around a defined label before an inline link',
         'See [docs][reference](/reference) for details.\n\n[docs]: /guide\n',
         'See [docs][reference](/reference) for more.\n\n[docs]: /guide\n'),
        ('a space added between an undefined label and an inline link',
         'See [x][Docs](`a` b) for details.\n\n[other]: /guide\n',
         'See [x] [Docs](`a` b) for details.\n\n[other]: /guide\n'),
        ('prose rewrapped after a nested quote ends a fence in a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > > ~~~text\n   > > echo old\n   > Read these notes carefully.\n',
         '[docs]: /guide\n2.\n   > > ~~~text\n   > > echo old\n   > Read these notes\n   carefully.\n'),
        ('a list marker indented one column less after a lazy run in an outer list',
         '- [docs]: /guide\n  2. Read *the guide*.\n3. Read *the guide\n  4. Read *the guide\n  ---\n',
         '- [docs]: /guide\n  2. Read *the guide*.\n3. Read *the guide\n 4. Read *the guide\n  ---\n')]:
    accepts("R3 " + name, src, cand)

# (Re-review of dd172ae: a line without quote markers after a quoted
# definition in a list item only markdown-it opens is read in the quote
# while the definition's reading takes it (a title), and ends the quote
# otherwise; a deeper quote marker there opens a quote of its own; the label
# after a shortcut reference counts only where a renderer reads those
# brackets as a label; where such an item ends is recorded among cmark-gfm's
# blocks; and a paragraph markdown-it reads before a range it may read in
# another way is also compared together with that range.)
for name, src, cand in [
        ('a paragraph after a quoted definition with its title on the next lazy line moved out of a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > [a]: /url\n   "Guide title"\n   Continue with care.\n',
         '[docs]: /guide\n2.\n   > [a]: /url\n   "Guide title"\n  Continue with care.\n'),
        ('a paragraph after a quoted definition with a title over two lazy lines moved out of a list item only markdown-it opens',
         '[docs]: /guide\n2.\n   > [a]: /url\n   "Guide\n   title"\n   Continue with care.\n',
         '[docs]: /guide\n2.\n   > [a]: /url\n   "Guide\n   title"\n  Continue with care.\n'),
        ('a space added between a label defined in both renderers and an inline link with nested brackets',
         'See [docs][manual [PDF]](/manual.pdf) for details.\n\n[docs]: /guide\n',
         'See [docs] [manual [PDF]](/manual.pdf) for details.\n\n[docs]: /guide\n'),
        ('a space added between a label only cmark-gfm defines and an inline link',
         'See [docs][reference](/reference) for details.\n\n[docs]: file:///guide.md\n',
         'See [docs] [reference](/reference) for details.\n\n[docs]: file:///guide.md\n'),
        ('a list item marker moved into the paragraph after an underline in a list item only markdown-it opens',
         '[docs]: /guide\n2. Run the steps.\n3. # Guide\n   ===\n4. # Notes\n5. Read *the guide*.\n',
         '[docs]: /guide\n2. Run the steps.\n3. # Guide\n   ===\n   4. # Notes\n5. Read *the guide*.\n'),
        ('a word changed inside an HTML comment markdown-it reads across a range it may read in another way',
         '>   1. Read the guide\n      <!-- note\n>     - Install the tool first\n<img src="x">\n  -->\n',
         '>   1. Read the guide\n      <!-- notes\n>     - Install the tool first\n<img src="x">\n  -->\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose reworded after a quoted definition with its title on the next lazy line',
         '[docs]: /guide\n2.\n   > [a]: /url\n   "Guide title"\n   Continue with care.\n',
         '[docs]: /guide\n2.\n   > [a]: /url\n   "Guide title"\n   Go on with care.\n'),
        ('prose rewrapped after a quoted definition with a title over two lazy lines',
         '[docs]: /guide\n2.\n   > [a]: /url\n   "Guide\n   title"\n   Continue with care.\n',
         '[docs]: /guide\n2.\n   > [a]: /url\n   "Guide\n   title"\n   Continue with\n   care.\n'),
        ('prose rewrapped after a title-like paragraph in a deeper quote',
         '[docs]: /guide\n2.\n   > [a]: /url\n   > > "Guide title"\n   Read these notes carefully.\n',
         '[docs]: /guide\n2.\n   > [a]: /url\n   > > "Guide title"\n  Read these notes\n  carefully.\n'),
        ('a space added between a label only cmark-gfm defines and an inline link with nested brackets',
         'See [docs][manual [PDF]](/manual.pdf) for details.\n\n[docs]: file:///guide.md\n',
         'See [docs] [manual [PDF]](/manual.pdf) for details.\n\n[docs]: file:///guide.md\n'),
        ('prose reworded in a list item only markdown-it opens before an underline',
         '[docs]: /guide\n2. Run the steps.\n3. # Guide\n   ===\n4. # Notes\n5. Read *the guide*.\n',
         '[docs]: /guide\n2. Run all the steps.\n3. # Guide\n   ===\n4. # Notes\n5. Read *the guide*.\n'),
        ('prose reworded before an HTML comment markdown-it reads across a range it may read in another way',
         '>   1. Read the guide\n      <!-- note\n>     - Install the tool first\n<img src="x">\n  -->\n',
         '>   1. Read this guide\n      <!-- note\n>     - Install the tool first\n<img src="x">\n  -->\n')]:
    accepts("R3 " + name, src, cand)

# (Re-review of c7ab94a: markdown-it reads the brackets of an inline link
# right after a shortcut reference as a label whatever they hold; a list
# item that starts with a block the walk reads no further is walked after a
# list item too; markdown-it ends a quote at any list marker on a lazy line;
# and the lines after a definition-like paragraph too long for the
# markdown-it walk are kept byte for byte up to a blank line.)
LONG_DEFS = ("[docs]: /guide\n2.\n" + "".join("   > [manual%d]: /guide/%d\n" % (i, i) for i in range(64))
             + '   "Guide title"\n' + "   Continue with care.\n")
for name, src, cand in [
        ('a space removed between a defined shortcut reference and an inline link whose text holds a bracket in code',
         'See [docs] [the `[` operator](/operators) for details.\n\n[docs]: /guide\n',
         'See [docs][the `[` operator](/operators) for details.\n\n[docs]: /guide\n'),
        ('a space removed between a defined shortcut reference and an inline link whose text holds a bracket in raw HTML',
         'See [docs] [the <b title="[">op</b>](/o) now.\n\n[docs]: /guide\n',
         'See [docs][the <b title="[">op</b>](/o) now.\n\n[docs]: /guide\n'),
        ('a list item indented into the item before it that starts with a quote, in a list only markdown-it opens',
         '[docs]: /guide\n2. Run the steps.\n3. > Read the quoted notes.\n   > Continue with care.\n4. More notes.\n',
         '[docs]: /guide\n2. Run the steps.\n3. > Read the quoted notes.\n   > Continue with care.\n   4. More notes.\n')]:
    rejects("R3 " + name, src, cand)
rejects("R3 a paragraph after 64 quoted definitions and a lazy title moved out of a list item only markdown-it opens",
        LONG_DEFS, LONG_DEFS.replace("\n   Continue", "\n  Continue"))
rejects("R3 a list item moved out of the item it is nested in, after a list item only markdown-it opens",
        "- [docs]: /guide\n  3. # Notes\n       - item one\n     - item two\n   - item three\n",
        "- [docs]: /guide\n  3. # Notes\n       - item one\n    - item two\n   - item three\n")
for name, src, cand in [
        ('prose reworded in a list item after an item that starts with a quote, in a list only markdown-it opens',
         '[docs]: /guide\n2. Run the steps.\n3. > Read the quoted notes.\n   > Continue with care.\n4. More notes.\n',
         '[docs]: /guide\n2. Run the steps.\n3. > Read the quoted notes.\n   > Continue with care.\n4. Further notes.\n'),
        ('prose reworded where a quote and a list item each hold a lone backtick',
         '>   1. Read the guide\n>      A lone ` opens an inline code span.\n>     - Install the tool first\n2. More notes.\nUse another ` to close it.\n',
         '>   1. Read the guide\n>      A lone ` starts an inline code span.\n>     - Install the tool first\n2. More notes.\nUse another ` to close it.\n')]:
    accepts("R3 " + name, src, cand)

# (Re-review of 38770d3: a later list item beside or outside the item
# markdown-it opened is walked whatever reading ends that item; a title
# the walk cannot read to its end, and the lines after it up to a blank
# line, are kept byte for byte, while a long paragraph whose first line
# starts no definition stays prose; and where such an item ends at a quote
# markdown-it opens, a fence, HTML block or indented code in that quote is
# kept byte for byte.)
LONG_TITLE = ('[docs]: /guide\n2.\n   > [a]: /url\n   "Guide\n' + '   useful notes\n' * 63
              + '   title"\n   Continue with care.\n')
LONG_PROSE = ('[docs]: /guide\n2.\n   > [docs] explains the procedure.\n'
              + '   > Read the next step carefully.\n' * 63 + '   > Continue with care.\n')
for name, src, cand in [
        ('a list item indented into an item that starts with a quote, after a paragraph in the item before it',
         '[docs]: /guide\n2. # Step\n   Some prose.\n3. > Read the quoted notes.\n   > Continue with care.\n4. More notes.\n',
         '[docs]: /guide\n2. # Step\n   Some prose.\n3. > Read the quoted notes.\n   > Continue with care.\n   4. More notes.\n'),
        ('indented code changed in a quote markdown-it opens where a list item only it opens ends',
         '[docs]: /guide\n2. Read the notes.\n   > Read the quoted notes.\n>     echo old\n',
         '[docs]: /guide\n2. Read the notes.\n   > Read the quoted notes.\n>     echo new\n'),
        ('indentation changed in code in a quote markdown-it opens after a nested quote in such an item',
         '[docs]: /guide\n2.\n   > [manual]: /guide\n   > > Continue with care.\n>      4. *Read the notes.\n   Read the ` span.\n',
         '[docs]: /guide\n2.\n   > [manual]: /guide\n   > > Continue with care.\n>       4. *Read the notes.\n   Read the ` span.\n')]:
    rejects("R3 " + name, src, cand)
rejects("R3 a paragraph after a lazy title over 64 lines moved out of a list item only markdown-it opens",
        LONG_TITLE, LONG_TITLE.replace("   Continue with care.", "  Continue with care."))
accepts("R3 prose reworded at the end of a long quoted paragraph that starts with a reference link",
        LONG_PROSE, LONG_PROSE.replace("Continue with care.", "Continue with caution."))
for name, src, cand in [
        ('prose reworded in a quote markdown-it opens where a list item only it opens ends',
         '[docs]: /guide\n2. Read the notes.\n   > Read the quoted notes.\n> Plain quoted text.\n',
         '[docs]: /guide\n2. Read the notes.\n   > Read the quoted notes.\n> Plain quoted words.\n'),
        ('prose reworded in a list item after an item that starts with a quote, after a paragraph',
         '[docs]: /guide\n2. # Step\n   Some prose.\n3. > Read the quoted notes.\n   > Continue with care.\n4. More notes.\n',
         '[docs]: /guide\n2. # Step\n   Some prose.\n3. > Read the quoted notes.\n   > Continue with care.\n4. Further notes.\n')]:
    accepts("R3 " + name, src, cand)

# (Re-review of e159fd5: the walk of a list item only markdown-it opens
# reads on into the next item at a list marker short of the item's column;
# a fence or HTML block in the item's quote is kept byte for byte; a quote
# markdown-it opens where an item ends is measured from the column of the
# list item around it; at the cap, an unclosed label or a label followed
# by a colon may still make a definition; and after a complete definition
# only a title may continue it.)
OPEN_TITLE = ('[docs]: /guide\n2.\n   > [a]: /url "Title\n' + '   > note\n' * 63
              + '   > end"\n   Continue with care.\n')
OPEN_LABEL = ('[docs]: /guide\n2.\n   > [abc\n' + '   > note\n' * 63 + '   > def]: /url\n   Continue with care.\n')
LAZY_PROSE = ('[docs]: /guide\n2.\n   > [a]: /url\n' + '   Read the next step carefully.\n' * 63
              + '   Continue with care.\n')
for name, src, cand in [
        ('a list item indented into a later item that starts with a quote, after an item that starts with a definition',
         '[docs]: /guide\n2. [a]: /url\n   A paragraph.\n3. > Read the quoted notes.\n   > Continue with care.\n4. More notes.\n',
         '[docs]: /guide\n2. [a]: /url\n   A paragraph.\n3. > Read the quoted notes.\n   > Continue with care.\n   4. More notes.\n'),
        ('indented code changed in a quote markdown-it opens inside an outer list item where an item ends',
         '- [docs]: /guide\n  2. Read the notes.\n     > Read the quoted notes.\n    >     echo old\n',
         '- [docs]: /guide\n  2. Read the notes.\n     > Read the quoted notes.\n    >     echo new\n'),
        ('code changed in a fence inside the quote of a list item only markdown-it opens',
         '[docs]: /guide\n2. > ~~~\n   > echo old\n   > ~~~\n',
         '[docs]: /guide\n2. > ~~~\n   > echo new\n   > ~~~\n'),
        ('text changed in an HTML block inside the quote of a list item only markdown-it opens',
         '[docs]: /guide\n2. > <div>\n   > old text\n   > </div>\n',
         '[docs]: /guide\n2. > <div>\n   > new text\n   > </div>\n')]:
    rejects("R3 " + name, src, cand)
rejects("R3 a paragraph after a quoted title still open at the walk's cap moved out of a list item only markdown-it opens",
        OPEN_TITLE, OPEN_TITLE.replace("   Continue with care.", "  Continue with care."))
rejects("R3 a paragraph after a quoted label still open at the walk's cap moved out of a list item only markdown-it opens",
        OPEN_LABEL, OPEN_LABEL.replace("   Continue with care.", "  Continue with care."))
accepts("R3 prose reworded in a long lazy paragraph after a complete quoted definition",
        LAZY_PROSE, LAZY_PROSE.replace("Continue with care.", "Continue with caution."))
for name, src, cand in [
        ('prose reworded in a later list item after an item that starts with a definition',
         '[docs]: /guide\n2. [a]: /url\n   A paragraph.\n3. > Read the quoted notes.\n   > Continue with care.\n4. More notes.\n',
         '[docs]: /guide\n2. [a]: /url\n   A paragraph.\n3. > Read the quoted notes.\n   > Continue with care.\n4. Further notes.\n'),
        ('prose reworded in a quote before a quote markdown-it opens inside an outer list item',
         '- [docs]: /guide\n  2. Read the notes.\n     > Read the quoted notes.\n    >     echo old\n',
         '- [docs]: /guide\n  2. Read the notes.\n     > Read these quoted notes.\n    >     echo old\n')]:
    accepts("R3 " + name, src, cand)

# (Older edits found by fresh fuzz seeds, accepted since fbf4735 or earlier,
# in lists markdown-it opens or lines it reads outside their containers
# after a definition: now kept byte for byte.)
for src, cand in [
        ('1. [docs]: /guide\n   2. # guide*\n   3. # Read *the\n   ===\n   4. Read **bold** words\n   ===\n',
         '1. [docs]: /guide\n   2. # guide*\n   3. # Read *the\n   ===\n   4. Read **bold** words\n  ===\n'),
        ('> - > [docs]: /guide\n>    Read `old\n      ===\nmore `x` words\n',
         '> - > [docs]: /guide\n>    Read `old\n>       ===\nmore `x` words\n'),
        ('>   See <file:///a`b> and `echo old` now.\n>\n> - > [docs]: /guide\n> Read the guide\n> 2. # Notes\n>  ===\n>     echo old\n>     [ref]: old\n>   Read the notes.\n>\n> ```\n> old\n> ```\n',
         '>   See <file:///a`b> and `echo old` now.\n>\n> - > [docs]: /guide\n> Read the guide\n> 2. # Notes\n>  ===\n>     echo old\n>     [ref]: old\n"   Read the notes.\n>\n> ```\n> old\n> ```\n'),
        ('- 1. [docs]: /guide\n   Read the guide.\n  2. The notes explain everything.\n      ```\n  ===\n> > [docs]: /guide\nRead the guide\n2. # Notes\n    ===\nold "title"\n  old "title"\n[ref]:\n\n    old code\n',
         '- 1. [docs]: /guide\n   Read the guide.\n  2. The notes explain everything.\n      ```\n  ===\n> > [docs]: /guide\nRead the guide\n2. # Notes\n    ===\nold "title"\n  old "title"\n[ref]:\n\n   old code\n'),
        ('- [docs]: /guide\n  2.  Text\n    [ref]: old\n      ```\nSee [a](javascript:go(`x`)) and `open` then `close`.\nplain words\n\n    old code\n',
         '- [docs]: /guide\n  2.  Text\n    [ref]: old\n      ```\nSee [a](javascript:go(`x`)) and `open` then `close`.\nplain words\n\n    old  code\n'),
        ('1. > > > [docs]: /guide\n   > Read the guide\n   > 2. # Notes\n   >  ===\n   >     ```\n   >     Read the notes.\n   >   Continue with care.\n\n   > See [ref].\n',
         '1. > > > [docs]: /guide\n   > Read the guide\n   > 2. # Notes\n   >  ===\n   >     ```\n   >     Read the notes.\n   \\   Continue with care.\n\n   > See [ref].\n')]:
    rejects("R3 an older fuzz find after a definition kept byte for byte: " + repr(src[:40]), src, cand)

# (d37cc77 re-review: blank lines by Markdown's rule, a table header row
# markdown-it reads as a block of its own after a definition, kept lines
# hashed from the bytes as written, polish:on inside an open fence or HTML
# block, and list markers with ASCII digits only.)
for name, src, cand in [
        ("a no-break space line in a list markdown-it opens after a definition",
         "[docs]: /guide\n2. Read `echo\n\u00a0\nold` carefully.\n",
         "[docs]: /guide\n2. Read `echo\n\u00a0\nnew` carefully.\n"),
        ("a numbered table header row after a definition, a later line moved out of the item",
         "[docs]: /guide\n2. Read\n:---\n\n   Read the notes carefully.\n",
         "[docs]: /guide\n2. Read\n:---\n\n  Read the notes carefully.\n"),
        ("an indented table header row after a definition (code to markdown-it)",
         "[docs]: /guide\n    alpha | b\n--- | ---\n",
         "[docs]: /guide\n    gamma | b\n--- | ---\n"),
        ("a line added below a table markdown-it reads as a paragraph after a definition",
         "[docs]: /guide\n<span> | old\n--- | ---\n   ---\n\n3. old item\n",
         "[docs]: /guide\n<span> | old\n--- | ---\n \n   ---\n\n3. old item\n"),
        ("whitespace after polish:on inside a pre block in a region kept after a definition",
         "[docs]: /guide\n2. Read the notes.\n<!-- polish:off -->\n<pre>\nKeep old text.\n"
         "<!-- polish:on --> Read the notes.\n</pre>\n",
         "[docs]: /guide\n2. Read the notes.\n<!-- polish:off -->\n<pre>\nKeep old text.\n"
         "<!-- polish:on -->\tRead the notes.\n</pre>\n"),
        ("text after polish:on inside a pre block opened in the region",
         "<!-- polish:off -->\n<pre>\nKeep old text.\n<!-- polish:on --> Read the notes.\n</pre>\n",
         "<!-- polish:off -->\n<pre>\nKeep old text.\n<!-- polish:on --> Review the notes.\n</pre>\n"),
        ("code after polish:on inside a fence opened in the region",
         "<!-- polish:off -->\n```\ncode\n<!-- polish:on -->\nmore code\n```\nText after.\n",
         "<!-- polish:off -->\n```\ncode\n<!-- polish:on -->\nless code\n```\nText after.\n"),
        ("a code span over a no-break space line",
         "Read `echo\n\u00a0\nold` carefully.\n", "Read `echo\n\u00a0\nnew` carefully.\n"),
        ("an attribute over an ideographic space line",
         "Read <span title=\"a\n\u3000\nold\">x</span> now.\n", "Read <span title=\"a\n\u3000\nnew\">x</span> now.\n"),
        ("a code span over a form feed line in a list item",
         "- Read `echo\n  \x0c\n  old` carefully.\n", "- Read `echo\n  \x0c\n  new` carefully.\n"),
        ("a code span over a quoted no-break space line",
         "> Read `echo\n> \u00a0\n> old` carefully.\n", "> Read `echo\n> \u00a0\n> new` carefully.\n"),
        ("an HTML block over a no-break space line",
         "<div>\n\u00a0\nold text\n</div>\n", "<div>\n\u00a0\nnew text\n</div>\n"),
        ("indented code after carriage returns without line feeds",
         "Read this.\r\r    echo old\r\n", "Read this.\r\r    echo new\r\n"),
        ("indented code after a fullwidth-numbered line (no list item)",
         "\uff12. Read\n\n    echo old\n", "\uff12. Read\n\n    echo new\n"),
        ("indented code after an Arabic-Indic-numbered line (no list item)",
         "\u0663. Read\n\n    echo old\n", "\u0663. Read\n\n    echo new\n")]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ("prose after a triple-backtick code span in a region kept after a definition",
         "[docs]: /guide\n2. Read the notes.\n   ```Use ``old`` here``` carefully.\n\n"
         "Read the next section carefully.\n",
         "[docs]: /guide\n2. Read the notes.\n   ```Use ``old`` here``` carefully.\n\n"
         "Review the next section carefully.\n"),
        ("a fullwidth-numbered line after a definition reworded",
         "[docs]: /guide\n\uff12. Read the notes carefully.\n", "[docs]: /guide\n\uff12. Review the notes carefully.\n"),
        ("a fullwidth-numbered paragraph after a region kept after a definition reworded",
         "[docs]: /guide\n2. Read the notes.\n\n\uff12. Read the notes carefully.\n",
         "[docs]: /guide\n2. Read the notes.\n\n\uff12. Review the notes carefully.\n"),
        ("a document with carriage return line endings reworded",
         "Read this.\r\n\r\nMore text.\r\n", "Read this.\r\n\r\nSome text.\r\n"),
        ("a line with a no-break space between words reworded",
         "Read the\u00a0notes now.\n", "Review the\u00a0notes now.\n"),
        ("prose after polish:on when the fence in the region is closed",
         "<!-- polish:off -->\n```\ncode\n```\n<!-- polish:on -->\nRead the notes.\n",
         "<!-- polish:off -->\n```\ncode\n```\n<!-- polish:on -->\nReview the notes.\n")]:
    accepts("R3 " + name, src, cand)

# (5e23e8d re-review: mixed line endings, a definition title running onto a
# table header row, polish:on inside a raw block as the renderers read it,
# and whitespace other than spaces and tabs at the edges of a line's text.)
for name, src, cand in [
        ("a fence after a bare carriage return",
         "Read the notes.\r```text\n\nRead old text.\n```\n", "Read the notes.\r```text\n\nRead new text.\n```\n"),
        ("one line with a CRLF ending in an LF document",
         "- 1. [docs]: /guide\r\n     Read the guide.\n  2. The notes explain everything.\n",
         "- 1. [docs]: /guide\r\nRead the guide.\n  2. The notes explain everything.\n"),
        ("a definition title running onto a table header row",
         "[docs]: /guide\n\"Read old\nmore | words\"\n--- | ---\n\nSee [docs] now.\n",
         "[docs]: /guide\n\"Read new\nmore | words\"\n--- | ---\n\nSee [docs] now.\n"),
        ("text after polish:on on its own line inside a div opened in the region",
         "<!-- polish:off -->\n<div>\nKeep text.\n<!-- polish:on -->\nRead old text.\n</div>\n",
         "<!-- polish:off -->\n<div>\nKeep text.\n<!-- polish:on -->\nRead new text.\n</div>\n"),
        ("text after polish:on inside a span block opened in the region",
         "<!-- polish:off -->\n<span>\nKeep text.\n<!-- polish:on -->\nRead old text.\n</span>\n",
         "<!-- polish:off -->\n<span>\nKeep text.\n<!-- polish:on -->\nRead new text.\n</span>\n"),
        ("text after polish:on inside a div in a list item",
         "- <!-- polish:off -->\n  <div>\n  Keep text.\n  <!-- polish:on -->\n  Read old text.\n  </div>\n",
         "- <!-- polish:off -->\n  <div>\n  Keep text.\n  <!-- polish:on -->\n  Read new text.\n  </div>\n"),
        ("text after polish:on when an indented backtick line does not close the fence",
         "<!-- polish:off -->\n```markdown\n    ```\n<!-- polish:on -->\nRead old text.\n```\n",
         "<!-- polish:off -->\n```markdown\n    ```\n<!-- polish:on -->\nRead new text.\n```\n"),
        ("text after polish:on when a quoted backtick line does not close the fence",
         "<!-- polish:off -->\n```markdown\n> ```\n<!-- polish:on -->\nRead old text.\n```\n",
         "<!-- polish:off -->\n```markdown\n> ```\n<!-- polish:on -->\nRead new text.\n```\n"),
        ("text after polish:on on a line that opens a pre block before the marker",
         "<!-- polish:off -->\nKeep.\n<pre><!-- polish:on --> text old\n</pre>\n",
         "<!-- polish:off -->\nKeep.\n<pre><!-- polish:on --> text new\n</pre>\n"),
        ("a list item holding only an ideographic space before a heading item",
         "> [docs]: /guide\n- \u3000\nRead the guide\n2. # Notes\n",
         "> [docs]: /guide\n- \u3000\nRead the guide\n2. #Notes\n"),
        ("a definition ending in a vertical tab",
         "1. See ![x][docs](old) and `echo old` now.\n> old` here\u00a0\n\n[docs]: <x`y>\u000b\n",
         "1. See ![x][docs](old) and `echo old` now.\n> old` here\u00a0\n\n[docs]:'<x`y>\u000b\n"),
        ("a line starting with an ideographic space before a list marker",
         "- - 1. [docs]: /guide\n       Read the guide.\n    2. The notes explain everything.\n  <span>\n  ```\n"
         "  \u3000- See ![the option][ref](file:///a \"` t\") for details.\n\n  [ref]: <x`y>\n\n"
         "  | a | b |\n  | - | - |\n  | old | x |\n",
         "- - 1. [docs]: /guide\n       Read the guide.\n    2. The notes explain everything.\n  <span>\n  ```\n"
         "  \u3000- See ![the option][ref](file:///a \"` t\") for details.\n\n  [ref]: <x`y>\n\n"
         "  | a | b |\n  | - |- |\n  | old | x |\n")]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ("prose after a comment the polish:on marker closes",
         "<!-- polish:off -->\n<!-- keep this comment\n<!-- polish:on -->\n\nRead old notes.\n",
         "<!-- polish:off -->\n<!-- keep this comment\n<!-- polish:on -->\n\nRead new notes.\n"),
        ("prose after a quoted fence that ended with its quote before polish:on",
         "> <!-- polish:off -->\n> ```text\n> Keep this example.\n\n<!-- polish:on -->\n\nRead old notes.\n",
         "> <!-- polish:off -->\n> ```text\n> Keep this example.\n\n<!-- polish:on -->\n\nRead new notes.\n"),
        ("prose after a div that a blank line closed before polish:on",
         "<!-- polish:off -->\n<div>\nKeep.\n\n<!-- polish:on -->\nRead old.\n",
         "<!-- polish:off -->\n<div>\nKeep.\n\n<!-- polish:on -->\nRead new.\n"),
        ("many closed fences in polish:off regions, prose after one reworded",
         "".join("<!-- polish:off -->\n```\ncode %d\n```\n<!-- polish:on -->\nRead the notes %d.\n\n" % (x, x)
                 for x in range(2000)),
         "".join("<!-- polish:off -->\n```\ncode %d\n```\n<!-- polish:on -->\n%s the notes %d.\n\n"
                 % (x, "Review" if x == 5 else "Read", x) for x in range(2000)))]:
    accepts("R3 " + name, src, cand)

# (Polish markers as the renderers read them: plain HTML comments. Edits a
# marker placement fuzz found, accepted at 4464ffb and earlier.)
for name, src, cand in [
        ("indented code after a polish:on line that ends no region",
         "Intro text.\n\n<!-- polish:off -->\n<!-- polish:on --> Read old text.\n<!-- polish:on -->\n"
         "    old code\n    old code\n",
         "Intro text.\n\n<!-- polish:off -->\n<!-- polish:on --> Read old text.\n<!-- polish:on -->\n"
         "    old code\n    new code\n"),
        ("indented code after a polish:on line with text after the marker",
         "Intro text.\n\n<!-- polish:off -->\nold\"\n<!-- polish:on --> Read old text.\n    old code\n",
         "Intro text.\n\n<!-- polish:off -->\nold\"\n<!-- polish:on --> Read old text.\n   old code\n"),
        ("a fence markdown-it opens after a polish:on line inside a lazy HTML block cmark-gfm opens",
         "Intro text.\n\n<!-- polish:off -->\n- old item\n<span>\n    old code\n[r]: /old \"title\n"
         "<!-- polish:on -->\n~~~\n\nProse after old.\n",
         "Intro text.\n\n<!-- polish:off -->\n- old item\n<span>\n    old code\n[r]: /old \"title\n"
         "<!-- polish:on -->\n~~~\n\nProse after new.\n")]:
    rejects("R3 " + name, src, cand)

# (4464ffb re-review: with polish markers, the regions are compared byte for
# byte and the rest as the renderers read it, the markers being plain HTML
# comments to them.)
for name, src, cand in [
        ("text in an HTML block markdown-it reads across a quoted polish:on marker",
         "> <!-- polish:off -->\n> [docs]: /guide\n> <span>\n> <!-- polish:on -->\n> Read old notes.\n> </span>\n",
         "> <!-- polish:off -->\n> [docs]: /guide\n> <span>\n> <!-- polish:on -->\n> Read new notes.\n> </span>\n"),
        ("code in a code span across a polish:on marker",
         "<!-- polish:off -->\nRead this example:\n    ```text\n    <!-- polish:on -->\n   echo old\n    ```\n",
         "<!-- polish:off -->\nRead this example:\n    ```text\n    <!-- polish:on -->\n   echo new\n    ```\n"),
        ("indented code after a quoted polish:on line with text after the marker",
         "> <!-- polish:off -->\n> <div>Keep.</div>\n>\n> <!-- polish:on --> Continue here.\n>     echo old\n",
         "> <!-- polish:off -->\n> <div>Keep.</div>\n>\n> <!-- polish:on --> Continue here.\n>     echo new\n"),
        ("a paragraph moved out of a list item opened inside a region",
         "<!-- polish:off -->\n- Notes.\n  <!-- polish:on -->\n  More text.\n",
         "<!-- polish:off -->\n- Notes.\n  <!-- polish:on -->\nMore text.\n")]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ("prose after a region whose marker line is paragraph text with indented tildes",
         "<!-- polish:off -->\nNotes.\n    ~~~\n    <!-- polish:on --> Done.\n    ~~~\n\nRead old prose.\n",
         "<!-- polish:off -->\nNotes.\n    ~~~\n    <!-- polish:on --> Done.\n    ~~~\n\nRead new prose.\n"),
        ("prose after list items whose fences end with the items, around a polish:on marker",
         "<!-- polish:off -->\n- ```text\n  Keep this example.\n- <!-- polish:on -->\n  ```\n  Keep another example.\n\n"
         "Read old prose.\n",
         "<!-- polish:off -->\n- ```text\n  Keep this example.\n- <!-- polish:on -->\n  ```\n  Keep another example.\n\n"
         "Read new prose.\n")]:
    accepts("R3 " + name, src, cand)

# (0bd3e72 re-review: renamed markers must stay different from literal
# look-alike comments, and a marker inside a footnote definition is read both
# as a marker and as text.)
for name, src, cand in [
        ("a literal marker in a code span changed to its renamed form",
         "Use `<!-- polish:off -->` to freeze the text.\n", "Use `<!-- polish-off -->` to freeze the text.\n"),
        ("a renamed-looking comment in a code span changed to a marker",
         "Use `<!-- polish-on -->` to freeze the text.\n", "Use `<!-- polish:on -->` to freeze the text.\n"),
        ("a literal marker in a fence changed to its renamed form",
         "```\n<!-- polish:on -->\n```\n", "```\n<!-- polish-on -->\n```\n"),
        ("a protected sentence after a marker in footnote code",
         "See[^1].\n\n<!-- polish:off -->\n[^1]: Use `<!-- polish:on -->` in the example.\n\nKeep old wording.\n"
         "<!-- polish:on -->\n",
         "See[^1].\n\n<!-- polish:off -->\n[^1]: Use `<!-- polish:on -->` in the example.\n\nKeep new wording.\n"
         "<!-- polish:on -->\n"),
        ("a protected sentence after a marker in a fence in a footnote",
         "See[^1].\n\n<!-- polish:off -->\n[^1]: Example:\n\n    ```\n    <!-- polish:on -->\n    ```\n\n"
         "Keep old wording.\n<!-- polish:on -->\n",
         "See[^1].\n\n<!-- polish:off -->\n[^1]: Example:\n\n    ```\n    <!-- polish:on -->\n    ```\n\n"
         "Keep new wording.\n<!-- polish:on -->\n"),
        ("a protected sentence after a marker in footnote code, region never closed",
         "See[^1].\n\n<!-- polish:off -->\n[^1]: Use `<!-- polish:on -->` in the example.\n\nKeep old wording.\n",
         "See[^1].\n\n<!-- polish:off -->\n[^1]: Use `<!-- polish:on -->` in the example.\n\nKeep new wording.\n")]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ("prose after a region inside a footnote definition reworded",
         "See[^1].\n\n[^1]: Note <!-- polish:off -->keep<!-- polish:on --> old text.\n\nMore old text.\n",
         "See[^1].\n\n[^1]: Note <!-- polish:off -->keep<!-- polish:on --> old text.\n\nMore new text.\n"),
        ("prose next to a literal renamed-looking comment and a region reworded",
         "Use `<!-- polish-off -->` and <!-- polish:off -->keep<!-- polish:on --> old text.\n",
         "Use `<!-- polish-off -->` and <!-- polish:off -->keep<!-- polish:on --> new text.\n")]:
    accepts("R3 " + name, src, cand)
for name, src, cand in [
        ('a protected sentence after a real marker and a code marker in one footnote',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep `<!-- polish:on -->`\n\nKeep old wording.\n<!-- polish:on -->\n',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep `<!-- polish:on -->`\n\nKeep new wording.\n<!-- polish:on -->\n'),
        ('the same with the region never closed',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep `<!-- polish:on -->`\n\nKeep old wording.\n',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep `<!-- polish:on -->`\n\nKeep new wording.\n'),
        ('the same with the code marker in a fence in the footnote',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep\n\n    ```\n    <!-- polish:on -->\n    ```\n\nKeep old wording.\n<!-- polish:on -->\n',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep\n\n    ```\n    <!-- polish:on -->\n    ```\n\nKeep new wording.\n<!-- polish:on -->\n'),
        ('the same with the code marker in indented code in the footnote',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep\n\n        <!-- polish:on -->\n\nKeep old wording.\n<!-- polish:on -->\n',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep\n\n        <!-- polish:on -->\n\nKeep new wording.\n<!-- polish:on -->\n'),
        ('the same with the code marker on a lazy line',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep\nlazy `<!-- polish:on -->` text\n\nKeep old wording.\n<!-- polish:on -->\n',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep\nlazy `<!-- polish:on -->` text\n\nKeep new wording.\n<!-- polish:on -->\n'),
        ('the same with a markdown-it code span over the next footnote line',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep `a\n    <!-- polish:on -->` b\n\nKeep old wording.\n<!-- polish:on -->\n',
         'See[^1].\n\n[^1]: Note <!-- polish:off -->keep `a\n    <!-- polish:on -->` b\n\nKeep new wording.\n<!-- polish:on -->\n'),
        ('the same with the code marker in a nested footnote',
         'See[^1][^2].\n\n[^1]: Note <!-- polish:off -->keep\n    [^2]: Inner `<!-- polish:on -->` x\n\nKeep old wording.\n<!-- polish:on -->\n',
         'See[^1][^2].\n\n[^1]: Note <!-- polish:off -->keep\n    [^2]: Inner `<!-- polish:on -->` x\n\nKeep new wording.\n<!-- polish:on -->\n'),
        ('the same in a quote',
         '> See[^1].\n>\n> [^1]: Note <!-- polish:off -->keep `<!-- polish:on -->`\n>\n> Keep old wording.\n> <!-- polish:on -->\n',
         '> See[^1].\n>\n> [^1]: Note <!-- polish:off -->keep `<!-- polish:on -->`\n>\n> Keep new wording.\n> <!-- polish:on -->\n'),
        ('the same in a list item',
         '- See[^1].\n\n  [^1]: Note <!-- polish:off -->keep `<!-- polish:on -->`\n\n  Keep old wording.\n  <!-- polish:on -->\n',
         '- See[^1].\n\n  [^1]: Note <!-- polish:off -->keep `<!-- polish:on -->`\n\n  Keep new wording.\n  <!-- polish:on -->\n'),
        ('a protected sentence after a footnote comment line markdown-it reads as code',
         'See[^1].\n\n<!-- polish:off -->\n[^1]: Example:\n\n    <!-- polish:on -->\n\nKeep old wording.\n<!-- polish:on -->\n',
         'See[^1].\n\n<!-- polish:off -->\n[^1]: Example:\n\n    <!-- polish:on -->\n\nKeep new wording.\n<!-- polish:on -->\n'),
        ("a protected sentence after a marker in a footnote's reference title",
         "See[^1].\n\n<!-- polish:off -->\n[^1]: /url '<!-- polish:on -->'\n\nKeep old wording.\n<!-- polish:on -->\n",
         "See[^1].\n\n<!-- polish:off -->\n[^1]: /url '<!-- polish:on -->'\n\nKeep new wording.\n<!-- polish:on -->\n"),
        ('a protected sentence after a marker in a footnote label',
         'See[^a<!-- polish:on -->].\n\n<!-- polish:off -->\n[^a<!-- polish:on -->]: x\n\nKeep old wording.\n<!-- polish:on -->\n',
         'See[^a<!-- polish:on -->].\n\n<!-- polish:off -->\n[^a<!-- polish:on -->]: x\n\nKeep new wording.\n<!-- polish:on -->\n'),
        ('a protected sentence after a code marker on a tab-indented footnote line',
         'See[^1].\n\n<!-- polish:off -->\n[^1]: Example\n\t`<!-- polish:on -->`\n\nKeep old wording.\n<!-- polish:on -->\n',
         'See[^1].\n\n<!-- polish:off -->\n[^1]: Example\n\t`<!-- polish:on -->`\n\nKeep new wording.\n<!-- polish:on -->\n'),
        ('a protected sentence after an escaped marker split by a code span',
         'Start <!-- polish:off -->keep.\n\nSee \\<!--`x`polish:on --> here.\n\nKeep old wording.\n<!-- polish:on -->\n',
         'Start <!-- polish:off -->keep.\n\nSee \\<!--`x`polish:on --> here.\n\nKeep new wording.\n<!-- polish:on -->\n'),
        ('code after a footnote and a lone tag that markdown-it reads in a fence',
         'See[^1].\n\n[^1]: Additional notes.\n<span class="example">\n```sh\necho start\n\necho old\n```\n</span>\n',
         'See[^1].\n\n[^1]: Additional notes.\n<span class="example">\n```sh\necho start\n\necho new\n```\n</span>\n'),
        ('prose after a footnote and a lone tag that markdown-it reads as code',
         'See[^1].\n\n[^2]: Some note.\n<span>\n```\ncode old\n\nProse old.\n',
         'See[^1].\n\n[^2]: Some note.\n<span>\n```\ncode old\n\nProse new.\n'),
        ('the same after a lazy line of a footnote read as a reference definition',
         'See[^1].\n\n[^2]: Example:\nlazy text\n<span>\n```\ncode old\n\nProse old.\n',
         'See[^1].\n\n[^2]: Example:\nlazy text\n<span>\n```\ncode old\n\nProse new.\n'),
        ('the same after an empty list item that markdown-it reads as an underline',
         'See[^1].\n\n[^2]: Some note.\n-\n  ```\n  code old\n\nProse old.\n',
         'See[^1].\n\n[^2]: Some note.\n-\n  ```\n  code old\n\nProse new.\n'),
        ('the same after a list item numbered 2',
         'See[^1].\n\n[^2]: Some note.\n2. item\n   ```\n   code old\n\nProse old.\n',
         'See[^1].\n\n[^2]: Some note.\n2. item\n   ```\n   code old\n\nProse new.\n'),
        ('the same after a footnote that interrupts a paragraph',
         'See[^1].\n\nKeep text.\n[^2]: Example:\n<span>\n```\ncode old\n\nProse old.\n',
         'See[^1].\n\nKeep text.\n[^2]: Example:\n<span>\n```\ncode old\n\nProse new.\n'),
        ('the same with an empty list item after a footnote that interrupts a paragraph',
         'See[^1].\n\nKeep text.\n[^2]: Example:\n-\n  ```\n  code old\n\nProse old.\n',
         'See[^1].\n\nKeep text.\n[^2]: Example:\n-\n  ```\n  code old\n\nProse new.\n'),
        ('the same in a quote',
         '> See[^2].\n>\n> [^2]: Some note.\n> <span>\n> ```\n> code old\n>\n> Prose old.\n',
         '> See[^2].\n>\n> [^2]: Some note.\n> <span>\n> ```\n> code old\n>\n> Prose new.\n'),
        ('the same in a list item',
         'See[^1].\n\n- [^2]: Some note.\n  <span>\n  ```\n  code old\n\n  Prose old.\n',
         'See[^1].\n\n- [^2]: Some note.\n  <span>\n  ```\n  code old\n\n  Prose new.\n'),
        ('the same after a footnote that ends a quote lazily',
         '> Keep text.\n[^2]: Some note.\n<span>\n```\ncode old\n\nProse old.\n',
         '> Keep text.\n[^2]: Some note.\n<span>\n```\ncode old\n\nProse new.\n'),
        ('the same after an indented footnote line',
         'See[^1].\n\n[^2]: Some note.\n    more note\n<span>\n```\ncode old\n\nProse old.\n',
         'See[^1].\n\n[^2]: Some note.\n    more note\n<span>\n```\ncode old\n\nProse new.\n'),
        ('a region whose markdown-it reading runs into a fence after a footnote',
         'Intro text.\n\n<!-- polish:off -->\nKeep old text.\n[^2]: Example:\n<span>\n```\n> [^1]: <!-- polish:on --> old\n[^1]: Note <!-- polish:off --> old\n<!-- polish:on -->\n    ```\n\nProse after old.\n',
         'Intro text.\n\n<!-- polish:off -->\nKeep old text.\n[^2]: Example:\n<span>\n```\n> [^1]: <!-- polish:on --> old\n[^1]: Note <!-- polish:off --> old\n<!-- polish:on -->\n    ```\n\nProse after new.\n'),
        ('a region whose markdown-it reading runs into a comment after a quoted footnote',
         'Intro text.\n\n> <!-- polish:off -->\n> [^2]: Example:\n> Keep old text.\n> <span>\n> lazy <!-- polish:on --> old\n> <!-- note\n>\n> Prose after old.\n',
         'Intro text.\n\n> <!-- polish:off -->\n> [^2]: Example:\n> Keep old text.\n> <span>\n> lazy <!-- polish:on --> old\n> <!-- note\n>\n> Prose after new.\n'),
        ('a protected sentence after a marker in raw HTML that markdown-it reads as a code span',
         'See[^1] and [^2].\n\n[^11]: Note <!-- polish:off --> old\n[^12]: Use `<!-- polish:on -->` old\n<span>\nlazy `<!-- polish:on -->` old\n<span class="x">\n\nProse after old.\n',
         'See[^1] and [^2].\n\n[^11]: Note <!-- polish:off --> old\n[^12]: Use `<!-- polish:on -->` old\n<span>\nlazy `<!-- polish:on -->` old\n<span class="x">\n\nProse after new.\n'),
        ("a protected sentence after a marker markdown-it reads lazily in a list item's paragraph",
         'See[^1] and [^2].\n\n<!-- polish:off -->\n    [^11]: Inner <!-- polish:on --> old\n    ```\n- old item\n</span>\n    [^12]: Inner `<!-- polish:on -->` old\n<span>\n    [^13]: Inner `<!-- polish:on -->` old\n\nProse after old.\n',
         'See[^1] and [^2].\n\n<!-- polish:off -->\n    [^11]: Inner <!-- polish:on --> old\n    ```\n- old item\n</span>\n    [^12]: Inner `<!-- polish:on -->` old\n<span>\n    [^13]: Inner `<!-- polish:on -->` old\n\nProse after new.\n'),
        ('a protected sentence after a marker that only markdown-it reads after a quoted footnote',
         'See[^1] and [^2].\n\n  <!-- polish:off -->\n  <!-- polish:on -->\n  > [^11]: <!-- polish:on --> old\n      <!-- polish:off -->\n      <!-- polish:on -->\n  \\<!--`x`polish:on --> old\n  Keep old text.\n          <!-- polish:on -->\n',
         'See[^1] and [^2].\n\n  <!-- polish:off -->\n  <!-- polish:on -->\n  > [^11]: <!-- polish:on --> old\n      <!-- polish:off -->\n      <!-- polish:on -->\n  \\<!--`x`polish:on --> new\n  Keep old text.\n          <!-- polish:on -->\n'),
        ("a protected sentence after a marker in a footnote that interrupts a list item's paragraph",
         "See[^1] and [^2].\n\n1. Start <!-- polish:off -->keep old.\n   <span>\n       <!-- polish:on -->\n   [^11]: /url '<!-- polish:on -->'\n       ```\n       <!-- polish:off -->\n\n   Prose after old.\n",
         "See[^1] and [^2].\n\n1. Start <!-- polish:off -->keep old.\n   <span>\n       <!-- polish:on -->\n   [^11]: /url '<!-- polish:on -->'\n       ```\n       <!-- polish:off -->\n\n   Prose after new.\n")]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a real marker in footnote prose reworded',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Note <!-- polish:on --> done.\n\nRead old prose.\n',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Note <!-- polish:on --> done.\n\nRead new prose.\n'),
        ('the same in a quote',
         '> See[^1].\n>\n> Start <!-- polish:off -->keep.\n>\n> [^1]: Note <!-- polish:on --> done.\n>\n> Read old prose.\n',
         '> See[^1].\n>\n> Start <!-- polish:off -->keep.\n>\n> [^1]: Note <!-- polish:on --> done.\n>\n> Read new prose.\n'),
        ('the same in a list item',
         '- See[^1].\n\n  Start <!-- polish:off -->keep.\n\n  [^1]: Note <!-- polish:on --> done.\n\n  Read old prose.\n',
         '- See[^1].\n\n  Start <!-- polish:off -->keep.\n\n  [^1]: Note <!-- polish:on --> done.\n\n  Read new prose.\n'),
        ("the same with the marker on a footnote's lazy line",
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Note\nlazy <!-- polish:on --> done.\n\nRead old prose.\n',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Note\nlazy <!-- polish:on --> done.\n\nRead new prose.\n'),
        ('the same with the marker in a nested footnote',
         'See[^1][^2].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Note text.\n    [^2]: Inner <!-- polish:on --> done.\n\nRead old prose.\n',
         'See[^1][^2].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Note text.\n    [^2]: Inner <!-- polish:on --> done.\n\nRead new prose.\n'),
        ('prose after a footnote code marker and a real marker reworded',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Use `<!-- polish:on -->` here.\n\n<!-- polish:on -->\nRead old prose.\n',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Use `<!-- polish:on -->` here.\n\n<!-- polish:on -->\nRead new prose.\n'),
        ('prose after a footnote read as a reference definition and a lone tag reworded',
         'See[^1].\n\n[^2]: Example:\n<span>\n```\ncode old\n\nRead old prose.\n',
         'See[^1].\n\n[^2]: Example:\n<span>\n```\ncode old\n\nRead new prose.\n'),
        ('prose after consecutive footnotes reworded',
         'See[^1] and [^2].\n\n[^1]: First note.\n[^2]: Second note.\n\nRead old prose.\n',
         'See[^1] and [^2].\n\n[^1]: First note.\n[^2]: Second note.\n\nRead new prose.\n'),
        ('prose after a footnote and a heading reworded',
         'See[^1].\n\n[^1]: Some note.\n# Heading\n\nRead old prose.\n',
         'See[^1].\n\n[^1]: Some note.\n# Heading\n\nRead new prose.\n'),
        ('prose after a footnote and a list item numbered 1 reworded',
         'See[^1].\n\n[^1]: Some note.\n1. Item\n\nRead old prose.\n',
         'See[^1].\n\n[^1]: Some note.\n1. Item\n\nRead new prose.\n'),
        ('prose after a footnote with a blank line and code reworded',
         'See[^1].\n\n[^1]: Some note.\n\n    ```\n    code\n    ```\nText.\n\nRead old prose.\n',
         'See[^1].\n\n[^1]: Some note.\n\n    ```\n    code\n    ```\nText.\n\nRead new prose.\n'),
        ('prose after a real marker following a footnote with an indented fence reworded',
         'Intro text.\n\n  <!-- polish:off -->\n  <!-- polish:off -->\n  [^2]: Example:\n      ```\n  lazy <!-- polish:on --> Read old prose.\n      ```\n  <!-- polish:on -->\n  See[^1] and [^2] old.\n  <!-- polish:off -->\n\n',
         'Intro text.\n\n  <!-- polish:off -->\n  <!-- polish:off -->\n  [^2]: Example:\n      ```\n  lazy <!-- polish:on --> Read new prose.\n      ```\n  <!-- polish:on -->\n  See[^1] and [^2] old.\n  <!-- polish:off -->\n\n')]:
    accepts("R3 " + name, src, cand)
for name, src, cand in [
        ('a protected sentence after a code marker on the line after an unclosed definition title',
         'Start <!-- polish:off -->keep.\n\n[r]: /old "title\n`<!-- polish:on -->` old\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n[r]: /old "title\n`<!-- polish:on -->` old\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a definition title',
         'Start <!-- polish:off -->keep.\n\n[r]: /old "title <!-- polish:on --> x"\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n[r]: /old "title <!-- polish:on --> x"\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a definition title on the next line',
         'Start <!-- polish:off -->keep.\n\n[r]: /old\n"title <!-- polish:on --> x"\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n[r]: /old\n"title <!-- polish:on --> x"\n\nRead new prose.\n'),
        ('a protected sentence after a marker in display math',
         'Start <!-- polish:off -->keep.\n\n$$\n<!-- polish:on -->\n$$\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n$$\n<!-- polish:on -->\n$$\n\nRead new prose.\n'),
        ('a protected sentence after a code marker in a table row with HTML',
         'Start <!-- polish:off -->keep.\n\n| <b>x</b> | `<!-- polish:on -->` |\n| --- | --- |\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n| <b>x</b> | `<!-- polish:on -->` |\n| --- | --- |\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a code span inside one table cell',
         'Start <!-- polish:off -->keep.\n\n| <b>x</b> | `a | `<!-- polish:on -->` |\n| --- | --- | --- |\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n| <b>x</b> | `a | `<!-- polish:on -->` |\n| --- | --- | --- |\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a code span across table cells',
         'Start <!-- polish:off -->keep.\n\n| <b>x</b> | `a | <!-- polish:on --> b` |\n| --- | --- | --- |\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n| <b>x</b> | `a | <!-- polish:on --> b` |\n| --- | --- | --- |\n\nRead new prose.\n'),
        ('a protected sentence after an indented code line and a tab-indented code marker',
         'See[^1] and [^2].\n\n<!-- polish:off -->\n    `a\n[r]: /old "title\n\t`<!-- polish:on -->` old\n> old quote\n[^11]: Example:\n\nRead old prose.\n',
         'See[^1] and [^2].\n\n<!-- polish:off -->\n    `a\n[r]: /old "title\n\t`<!-- polish:on -->` old\n> old quote\n[^11]: Example:\n\nRead new prose.\n'),
        ('a protected sentence after code markers in a list item with unclosed titles',
         'See[^1] and [^2].\n\n1. [^11]: Note <!-- polish:off --> old\n   [^12]: Note <!-- polish:off -->keep `<!-- polish:on -->` old\n\n   [r]: /old "title\n   lazy `<!-- polish:on -->` old\n   [r]: /old "title\n   <span class="x">\n   See[^1] and [^2] old.\n   [^13]: Use `<!-- polish:on -->` old\n\n   Read old prose.\n',
         'See[^1] and [^2].\n\n1. [^11]: Note <!-- polish:off --> old\n   [^12]: Note <!-- polish:off -->keep `<!-- polish:on -->` old\n\n   [r]: /old "title\n   lazy `<!-- polish:on -->` old\n   [r]: /old "title\n   <span class="x">\n   See[^1] and [^2] old.\n   [^13]: Use `<!-- polish:on -->` old\n\n   Read new prose.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a region inside a table cell reworded',
         '| Name | Value |\n| --- | --- |\n| a | <!-- polish:off -->keep old<!-- polish:on --> |\n\nRead old prose.\n',
         '| Name | Value |\n| --- | --- |\n| a | <!-- polish:off -->keep old<!-- polish:on --> |\n\nRead new prose.\n'),
        ('prose after a real marker following a definition reworded',
         'Start <!-- polish:off -->keep.\n\n[r]: /old\n\nText <!-- polish:on --> done.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n[r]: /old\n\nText <!-- polish:on --> done.\n\nRead new prose.\n')]:
    accepts("R3 " + name, src, cand)
for name, src, cand in [
        ('a protected sentence after a marker markdown-it reads as indented code after a definition',
         'Start <!-- polish:off -->keep.\n\n[r]: /old\n    <!-- polish:on -->\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n[r]: /old\n    <!-- polish:on -->\n\nRead new prose.\n'),
        ('protected code after markers markdown-it reads as indented code after definitions in a list item',
         "See[^1] and [^2].\n\n1. <!-- polish:off -->\n   [r]: /old '<!-- polish:on -->'\n       `a\n       <!-- polish:on -->\n   <!-- polish:off -->\n   [r]: /old '<!-- polish:on -->'\n       [^11]: Inner <!-- polish:on --> old\n   $$\n       Read old prose.\n   Prose after old.\n",
         "See[^1] and [^2].\n\n1. <!-- polish:off -->\n   [r]: /old '<!-- polish:on -->'\n       `a\n       <!-- polish:on -->\n   <!-- polish:off -->\n   [r]: /old '<!-- polish:on -->'\n       [^11]: Inner <!-- polish:on --> old\n   $$\n       Read new prose.\n   Prose after old.\n")]:
    rejects("R3 " + name, src, cand)

for name, src, cand in [
        ('a protected sentence after a lazy underline inside a footnote code span',
         'See[^1].\n\n[^1]: Keep <!-- polish:off --> `example\n===\ntext <!-- polish:on -->`\n\nRead old prose.\n',
         'See[^1].\n\n[^1]: Keep <!-- polish:off --> `example\n===\ntext <!-- polish:on -->`\n\nRead new prose.\n'),
        ('code markdown-it continues from a footnote into the next paragraph',
         'See[^1].\n\n[^1]: The command is `echo\n    # Notes\nold`.\n\nEnd.\n',
         'See[^1].\n\n[^1]: The command is `echo\n    # Notes\nnew`.\n\nEnd.\n'),
        ('indented code markdown-it reads after an underline that follows a footnote',
         'See[^1].\n\n[^1]: # Notes\n===\n    echo old\n',
         'See[^1].\n\n[^1]: # Notes\n===\n    echo new\n'),
        ('an HTML attribute markdown-it continues from a footnote into the next paragraph',
         'See[^1].\n\n[^1]: Note <span title="a\n    # Notes\nold">x</span>.\n\nEnd.\n',
         'See[^1].\n\n[^1]: Note <span title="a\n    # Notes\nnew">x</span>.\n\nEnd.\n'),
        ('a protected sentence after a marker in code markdown-it continues from a footnote',
         'Start <!-- polish:off -->keep.\n\nSee[^1].\n\n[^1]: The command is `echo\n    # Notes\nthen <!-- polish:on -->`.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\nSee[^1].\n\n[^1]: The command is `echo\n    # Notes\nthen <!-- polish:on -->`.\n\nRead new prose.\n'),
        ('a link markdown-it continues from a footnote into the next paragraph',
         'See[^1].\n\n[^1]: See [the\n    # Notes\nguide](/old) here.\n',
         'See[^1].\n\n[^1]: See [the\n    # Notes\nguide](/new) here.\n'),
        ('a protected sentence after a marker in a code span of one table cell',
         'Start <!-- polish:off -->keep.\n\n| Name | Value |\n| --- | --- |\n| `a | `<!-- polish:on -->` |\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n| Name | Value |\n| --- | --- |\n| `a | `<!-- polish:on -->` |\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a code span from the paragraph before a table',
         'Start <!-- polish:off -->keep.\n\nIntro `a\n| Name | Value |\n| --- | --- |\n| one | <!-- polish:on -->` |\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\nIntro `a\n| Name | Value |\n| --- | --- |\n| one | <!-- polish:on -->` |\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a code span across table rows',
         'Start <!-- polish:off -->keep.\n\n| Name | Value |\n| --- | --- |\n| one | `example |\n| two | <!-- polish:on -->` |\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n| Name | Value |\n| --- | --- |\n| one | `example |\n| two | <!-- polish:on -->` |\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a code span from the table header',
         'Start <!-- polish:off -->keep.\n\n| Name | `Value |\n| --- | --- |\n| one | <!-- polish:on -->` |\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n| Name | `Value |\n| --- | --- |\n| one | <!-- polish:on -->` |\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a definition title in a list item',
         'Start <!-- polish:off -->keep.\n\n- [docs]: /guide "<!-- polish:on -->"\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n- [docs]: /guide "<!-- polish:on -->"\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a definition title in an ordered list item',
         'Start <!-- polish:off -->keep.\n\n1. [docs]: /guide "<!-- polish:on -->"\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n1. [docs]: /guide "<!-- polish:on -->"\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a definition title in a quoted list item',
         'Start <!-- polish:off -->keep.\n\n> - [docs]: /guide "<!-- polish:on -->"\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n> - [docs]: /guide "<!-- polish:on -->"\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a code span inside TeX math',
         'Start <!-- polish:off -->keep.\n\nUse \\(`<!-- polish:on -->`\\) to resume.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\nUse \\(`<!-- polish:on -->`\\) to resume.\n\nRead new prose.\n'),
        ('a protected sentence after a marker in a link title',
         'Start <!-- polish:off -->keep.\n\nSee [docs](/guide "<!-- polish:on -->") for details.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\nSee [docs](/guide "<!-- polish:on -->") for details.\n\nRead new prose.\n'),
        ('a protected sentence after an escaped marker',
         'Start <!-- polish:off -->keep.\n\nUse \\<!-- polish:on --> as text.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\nUse \\<!-- polish:on --> as text.\n\nRead new prose.\n'),
        ('a protected sentence after a marker in an HTML attribute',
         'Start <!-- polish:off -->keep.\n\nUse <span title="<!-- polish:on -->">x</span> here.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\nUse <span title="<!-- polish:on -->">x</span> here.\n\nRead new prose.\n'),
        ("a protected sentence after a marker in a code span from a definition's indented line",
         'Start <!-- polish:off -->keep.\n\n[r]: /old\n    `a\n| `<!-- polish:on -->` b\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n[r]: /old\n    `a\n| `<!-- polish:on -->` b\n\nRead new prose.\n'),
        ("a protected sentence after an opener in a code span from a definition's indented line",
         'Intro.\n\n[r]: /old\n    `a\nStart <!-- polish:off -->` keep\n\nRead old prose.\n',
         'Intro.\n\n[r]: /old\n    `a\nStart <!-- polish:off -->` keep\n\nRead new prose.\n'),
        ('a protected row after a footnote whose fence markdown-it does not read',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Note text.\n    ```\n| <b>x</b> | <!-- polish:on --> old |\n    ```\nRead old prose.\n',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Note text.\n    ```\n| <b>x</b> | <!-- polish:on --> old |\n    ```\nRead new prose.\n'),
        ('a protected row after a quoted footnote whose fence markdown-it does not read',
         '> See[^1].\n>\n> Start <!-- polish:off -->keep.\n>\n> [^1]: Note text.\n>     ```\n> | <b>x</b> | <!-- polish:on --> old |\n>     ```\n> Read old prose.\n',
         '> See[^1].\n>\n> Start <!-- polish:off -->keep.\n>\n> [^1]: Note text.\n>     ```\n> | <b>x</b> | <!-- polish:on --> old |\n>     ```\n> Read new prose.\n'),
        ('a protected sentence after code markers in a list item with a definition and a table row',
         'See[^1] and [^2].\n\n  <!-- polish:off -->\n  [r]: /old \'<!-- polish:on -->\'\n      `a\n      old code\n  | a | `<!-- polish:on -->` old |\n  lazy `<!-- polish:on -->` old\n  [^11]: Example:\n  "t <!-- polish:on --> old"\n  <!-- polish:on -->\n\n  Prose after old.\n',
         'See[^1] and [^2].\n\n  <!-- polish:off -->\n  [r]: /old \'<!-- polish:on -->\'\n      `a\n      old code\n  | a | `<!-- polish:on -->` old |\n  lazy `<!-- polish:on -->` new\n  [^11]: Example:\n  "t <!-- polish:on --> old"\n  <!-- polish:on -->\n\n  Prose after old.\n'),
        ('a protected row after a quoted footnote fence with an HTML table row',
         'See[^1] and [^2].\n\n> [^11]: Note <!-- polish:off --> old\n>     ```\n> | <b>x</b> | <!-- polish:on --> old |\n>     ```\n> Prose after old.\n',
         'See[^1] and [^2].\n\n> [^11]: Note <!-- polish:off --> old\n>     ```\n> | <b>x</b> | <!-- polish:on --> new |\n>     ```\n> Prose after old.\n'),
        ('a protected list item after definitions, code lines and nested footnotes',
         'See[^1] and [^2].\n\nStart <!-- polish:off -->keep old.\n| a | `<!-- polish:on -->` old |\n    ```\n<!-- polish:on -->\n\n[r]: /old "title `<!-- polish:on -->` old"\n    <!-- polish:on -->` old\nStart <!-- polish:off -->keep old.\n    [^11]: Inner `<!-- polish:on -->` old\n2. old item\n$$\n',
         'See[^1] and [^2].\n\nStart <!-- polish:off -->keep old.\n| a | `<!-- polish:on -->` old |\n    ```\n<!-- polish:on -->\n\n[r]: /old "title `<!-- polish:on -->` old"\n    <!-- polish:on -->` old\nStart <!-- polish:off -->keep old.\n    [^11]: Inner `<!-- polish:on -->` old\n2. new item\n$$\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a region in a footnote on a list item line reworded',
         'See[^1].\n\n- [^1]: Note <!-- polish:off -->keep <!-- polish:on -->.\n\nRead old prose.\n',
         'See[^1].\n\n- [^1]: Note <!-- polish:off -->keep <!-- polish:on -->.\n\nRead new prose.\n'),
        ('prose after a code opener in a footnote on a list item line reworded',
         'See[^1].\n\n- [^1]: Use `<!-- polish:off -->` for disabled text.\n\nRead old prose.\n',
         'See[^1].\n\n- [^1]: Use `<!-- polish:off -->` for disabled text.\n\nRead new prose.\n'),
        ('prose after a region in a footnote on an ordered list item line reworded',
         'See[^1].\n\n1. [^1]: Note <!-- polish:off -->keep <!-- polish:on -->.\n\nRead old prose.\n',
         'See[^1].\n\n1. [^1]: Note <!-- polish:off -->keep <!-- polish:on -->.\n\nRead new prose.\n'),
        ('prose after a region in a footnote on a quote line reworded',
         'See[^1].\n\n> [^1]: Note <!-- polish:off -->keep <!-- polish:on -->.\n\nRead old prose.\n',
         'See[^1].\n\n> [^1]: Note <!-- polish:off -->keep <!-- polish:on -->.\n\nRead new prose.\n'),
        ('prose after a closer that follows a footnote fence and a blank line reworded',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Note text.\n    ```\n    code\n    ```\n\n<!-- polish:on -->\n\nRead old prose.\n',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\n[^1]: Note text.\n    ```\n    code\n    ```\n\n<!-- polish:on -->\n\nRead new prose.\n'),
        ('prose after a closer that follows a definition and indented code reworded',
         'Start <!-- polish:off -->keep.\n\n[r]: /old\n\n    code\n\n<!-- polish:on -->\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n[r]: /old\n\n    code\n\n<!-- polish:on -->\n\nRead new prose.\n'),
        ('prose after a closer in link text reworded',
         'Start <!-- polish:off -->keep.\n\nSee [docs <!-- polish:on -->](/guide) here.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\nSee [docs <!-- polish:on -->](/guide) here.\n\nRead new prose.\n'),
        ('prose after a plain closer reworded',
         'Start <!-- polish:off -->keep.\n\nThen <!-- polish:on --> here.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\nThen <!-- polish:on --> here.\n\nRead new prose.\n'),
        ('prose after a footnote with a code span and a blank line reworded',
         'See[^1].\n\n[^1]: The command is `echo`.\n\nEnd old.\n',
         'See[^1].\n\n[^1]: The command is `echo`.\n\nEnd new.\n'),
        ('prose after a closer in a table cell reworded',
         'Start <!-- polish:off -->keep.\n\n| Name | Value |\n| --- | --- |\n| one | <!-- polish:on --> |\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n| Name | Value |\n| --- | --- |\n| one | <!-- polish:on --> |\n\nRead new prose.\n'),
        ('prose after a closer both renderers read past a lazy break in a footnote reworded',
         'See[^1].\n\n[^1]: Keep <!-- polish:off --> `example\n---\ntext <!-- polish:on -->`\n\nRead old prose.\n',
         'See[^1].\n\n[^1]: Keep <!-- polish:off --> `example\n---\ntext <!-- polish:on -->`\n\nRead new prose.\n'),
        ('prose after a footnote with a heading and a blank line reworded',
         'See[^1].\n\n[^1]: See [docs] and `x`.\n    # Notes\nold text.\n\nRead old prose.\n',
         'See[^1].\n\n[^1]: See [docs] and `x`.\n    # Notes\nold text.\n\nRead new prose.\n'),
        ('prose after a closer in a list item reworded',
         'Start <!-- polish:off -->keep.\n\n- Item <!-- polish:on --> done.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n- Item <!-- polish:on --> done.\n\nRead new prose.\n')]:
    accepts("R3 " + name, src, cand)

for name, src, cand in [
        ('code markdown-it continues from display math into the next line',
         'Intro.\n\n$$\nx `a\n$$\nb` old.\n',
         'Intro.\n\n$$\nx `a\n$$\nc` old.\n'),
        ('an HTML block in display math that runs on past it',
         'Intro.\n\n$$\n<div>\nx\n$$\nProse after old.\n',
         'Intro.\n\n$$\n<div>\nx\n$$\nProse after new.\n'),
        ('a fence in display math that runs on past it',
         'Intro.\n\n$$\n```\nx\n$$\n\nProse after old.\n',
         'Intro.\n\n$$\n```\nx\n$$\n\nProse after new.\n'),
        ('a fence in quoted display math that runs on past it',
         '> $$\n> ```\n> x $$\n> Prose after old.\n',
         '> $$\n> ```\n> x $$\n> Prose after new.\n'),
        ('indented code after an underline below display math',
         'Intro.\n\n$$\nx\n$$\n===\n    echo old\n',
         'Intro.\n\n$$\nx\n$$\n===\n    echo new\n'),
        ('a protected sentence after markers in a fence that runs on past display math',
         '> <!-- polish:off -->\n> $$\n> ```\n>     <!-- polish:on -->\n> ~~~\n> <!-- polish:on --> old $$\n> <!-- polish:on -->\n> Prose after old.\n',
         '> <!-- polish:off -->\n> $$\n> ```\n>     <!-- polish:on -->\n> ~~~\n> <!-- polish:on --> old $$\n> <!-- polish:on -->\n> Prose after new.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose right after display math reworded',
         'Intro.\n\n$$\nx\n$$\nNext old.\n',
         'Intro.\n\n$$\nx\n$$\nNext new.\n'),
        ('prose right after display math with stars and underscores reworded',
         'Intro.\n\n$$\nx_1 * y\n$$\nNext old.\n',
         'Intro.\n\n$$\nx_1 * y\n$$\nNext new.\n'),
        ('prose after display math holding a closed fence reworded',
         'Intro.\n\n$$\n```\nx\n```\n$$\n\nProse after old.\n',
         'Intro.\n\n$$\n```\nx\n```\n$$\n\nProse after new.\n'),
        ('prose after display math holding an HTML block and a blank line reworded',
         'Intro.\n\n$$\n<div>\nx\n$$\n\nProse after old.\n',
         'Intro.\n\n$$\n<div>\nx\n$$\n\nProse after new.\n'),
        ('prose right after display math with a closed code span reworded',
         'Intro.\n\n$$\nx `a` y\n$$\nb` old.\n',
         'Intro.\n\n$$\nx `a` y\n$$\nc` old.\n')]:
    accepts("R3 " + name, src, cand)

for name, src, cand in [
        ('a protected sentence after an opener in a quoted table right after a table',
         '| Name | Value |\n| --- | --- |\n| one | `example |\n> | Name | Value |\n> | --- | --- |\n> | `a | `<!-- polish:off -->` |\n\nRead old prose.\n',
         '| Name | Value |\n| --- | --- |\n| one | `example |\n> | Name | Value |\n> | --- | --- |\n> | `a | `<!-- polish:off -->` |\n\nRead new prose.\n'),
        ('a protected sentence after an opener in a table in the next list item',
         '- | Name | Value |\n  | --- | --- |\n  | one | `example |\n- | Name | Value |\n  | --- | --- |\n  | `a | `<!-- polish:off -->` |\n\nRead old prose.\n',
         '- | Name | Value |\n  | --- | --- |\n  | one | `example |\n- | Name | Value |\n  | --- | --- |\n  | `a | `<!-- polish:off -->` |\n\nRead new prose.\n'),
        ('a protected sentence after a marker in image alt text',
         '<!-- polish:off -->\n\n![Diagram <!-- polish:on -->](diagram.svg)\n\nRead old prose.\n',
         '<!-- polish:off -->\n\n![Diagram <!-- polish:on -->](diagram.svg)\n\nRead new prose.\n'),
        ('a protected sentence after a marker in reference image alt text',
         '<!-- polish:off -->\n\n![Diagram <!-- polish:on -->][d]\n\n[d]: /d.svg\n\nRead old prose.\n',
         '<!-- polish:off -->\n\n![Diagram <!-- polish:on -->][d]\n\n[d]: /d.svg\n\nRead new prose.\n'),
        ('emphasis from display math into the next line moved',
         '$$\nx*y\n$$\nThe value* is approximate.\n',
         '$$\nx*y\n$$\nThe value *is approximate.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a closer in a quoted table right after a table reworded',
         'Start <!-- polish:off -->keep.\n\n| Name | Value |\n| --- | --- |\n| one | `example |\n> | Name | Value |\n> | --- | --- |\n> | two | <!-- polish:on -->` |\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n| Name | Value |\n| --- | --- |\n| one | `example |\n> | Name | Value |\n> | --- | --- |\n> | two | <!-- polish:on -->` |\n\nRead new prose.\n'),
        ('prose after a closer in link text reworded (image control)',
         '<!-- polish:off -->\n\n[Diagram <!-- polish:on -->](diagram.svg)\n\nRead old prose.\n',
         '<!-- polish:off -->\n\n[Diagram <!-- polish:on -->](diagram.svg)\n\nRead new prose.\n'),
        ('prose after a closer right after an image reworded',
         '<!-- polish:off -->\n\n![Diagram](diagram.svg) <!-- polish:on -->\n\nRead old prose.\n',
         '<!-- polish:off -->\n\n![Diagram](diagram.svg) <!-- polish:on -->\n\nRead new prose.\n'),
        ('emphasis right after display math with a star reworded',
         '$$\nx*y\n$$\nNext *old* text.\n',
         '$$\nx*y\n$$\nNext *new* text.\n')]:
    accepts("R3 " + name, src, cand)
for name, doc in (("4000 display math blocks in one paragraph", "$$x$$\n" * 4000 + "Ordinary prose.\n"),
                  ("4000 footnote definitions in a row", "See[^1].\n\n" + "".join("[^%d]: Note %d.\n" % (k, k) for k in range(4000))),
                  ("2000 footnote definitions on list item lines", "See[^1].\n\n" + "".join("- [^%d]: Note %d.\n" % (k, k) for k in range(2000)))):
    started = time.process_time()
    accepts("R3 " + name + " unchanged", doc, doc)
    report("R3 " + name + " checked within two seconds", time.process_time() - started < 2.0,
           "%.2fs" % (time.process_time() - started))

for name, src, cand in [
        ('a protected sentence after a closer in a table markdown-it reads on from a quoted table',
         'Start <!-- polish:off -->keep.\n\n> | Name | Value |\n> | --- | --- |\n> | one | `example |\n| Name | Value |\n| --- | --- |\n| two | <!-- polish:on -->` |\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n> | Name | Value |\n> | --- | --- |\n> | one | `example |\n| Name | Value |\n| --- | --- |\n| two | <!-- polish:on -->` |\n\nRead new prose.\n'),
        ('a protected sentence after a closer in a table markdown-it reads on from a table before it',
         'Start <!-- polish:off -->keep.\n\n| Name | Value |\n| --- | --- |\n| one | `example |\n2. | Name | Value |\n   | --- | --- |\n   | two | <!-- polish:on -->` |\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n| Name | Value |\n| --- | --- |\n| one | `example |\n2. | Name | Value |\n   | --- | --- |\n   | two | <!-- polish:on -->` |\n\nRead new prose.\n'),
        ('a protected sentence after a marker in image text with a nested link title holding a bracket',
         '<!-- polish:off -->\n\n![Diagram [syntax](syntax.md "Use ] to close a label") <!-- polish:on -->](diagram.svg)\n\nRead old prose.\n',
         '<!-- polish:off -->\n\n![Diagram [syntax](syntax.md "Use ] to close a label") <!-- polish:on -->](diagram.svg)\n\nRead new prose.\n'),
        ('a protected sentence after a marker in image text with a nested link title opening a bracket',
         '<!-- polish:off -->\n\n![Diagram [syntax](syntax.md "Use [ to open") <!-- polish:on -->](diagram.svg)\n\nRead old prose.\n',
         '<!-- polish:off -->\n\n![Diagram [syntax](syntax.md "Use [ to open") <!-- polish:on -->](diagram.svg)\n\nRead new prose.\n'),
        ('a protected sentence after a marker in an explicit image reference label',
         '<!-- polish:off -->\n\n![Diagram][figure <!-- polish:on -->]\n\n[figure <!-- polish:on -->]: diagram.svg\n\nRead old prose.\n',
         '<!-- polish:off -->\n\n![Diagram][figure <!-- polish:on -->]\n\n[figure <!-- polish:on -->]: diagram.svg\n\nRead new prose.\n'),
        ('a protected sentence after a marker in an explicit link reference label',
         '<!-- polish:off -->\n\n[Diagram][figure <!-- polish:on -->]\n\n[figure <!-- polish:on -->]: diagram.svg\n\nRead old prose.\n',
         '<!-- polish:off -->\n\n[Diagram][figure <!-- polish:on -->]\n\n[figure <!-- polish:on -->]: diagram.svg\n\nRead new prose.\n'),
        ('emphasis from display math with an escaped star into the next line moved',
         '$$\nx*y + z \\* w\n$$\nThe value* is approximate.\n',
         '$$\nx*y + z \\* w\n$$\nThe value *is approximate.\n'),
        ('emphasis from display math with a star in code into the next line moved',
         '$$\nx*y + `z*` w\n$$\nThe value* is approximate.\n',
         '$$\nx*y + `z*` w\n$$\nThe value *is approximate.\n'),
        ('code from display math on past an indented math-looking line',
         '$$x`y$$\n    $$z$$\nThe old value` is approximate.\n',
         '$$x`y$$\n    $$z$$\nThe new value` is approximate.\n'),
        ('code from quoted display math on past a lazy math-looking line',
         '> $$x`y$$\n$$z$$\nThe old value` is approximate.\n',
         '> $$x`y$$\n$$z$$\nThe new value` is approximate.\n'),
        ('code from display math in a list item on past a math-looking line outside it',
         '- $$x`y$$\n$$z$$\nThe old value` is approximate.\n',
         '- $$x`y$$\n$$z$$\nThe new value` is approximate.\n'),
        ("a table cell inside markdown-it's code span across rows reworded",
         '| Name | `Value |\n| --- | --- |\n| one old | two` |\n',
         '| Name | `Value |\n| --- | --- |\n| one new | two` |\n'),
        ("a quoted table cell inside markdown-it's code span across rows reworded",
         '> | Name | `Value |\n> | --- | --- |\n> | one old | two` |\n',
         '> | Name | `Value |\n> | --- | --- |\n> | one new | two` |\n'),
        ("a lazy line inside markdown-it's code span from a quoted table reworded",
         '> | two | x` old |\n> | --- | --- |\nlazy text old\n> | two | y` old |\n',
         '> | two | x` old |\n> | --- | --- |\nlazy text new\n> | two | y` old |\n'),
        ("a lazy line inside markdown-it's code span from a quoted table cell reworded",
         '> | two | `x old |\n> | --- | --- |\nlazy text old` end\n',
         '> | two | `x old |\n> | --- | --- |\nlazy text new` end\n'),
        ("a paragraph inside markdown-it's code span into a table reworded",
         'Intro `a old\n| Name | Value |\n| --- | --- |\n| one | b` |\n',
         'Intro `a new\n| Name | Value |\n| --- | --- |\n| one | b` |\n'),
        ('a link target markdown-it reads across table cells changed',
         '| a | [link |\n| --- | --- |\n| b | text](/old) |\n',
         '| a | [link |\n| --- | --- |\n| b | text](/new) |\n'),
        ("a cell inside markdown-it's emphasis across cells reworded",
         '| *a | b* old |\n| --- | --- |\n| c | d |\n',
         '| *a | b* new |\n| --- | --- |\n| c | d |\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a closer in shortcut link text reworded',
         '<!-- polish:off -->\n\n[figure <!-- polish:on -->]\n\nRead old prose.\n',
         '<!-- polish:off -->\n\n[figure <!-- polish:on -->]\n\nRead new prose.\n'),
        ('prose after a closer in link text after an escaped bang reworded',
         '<!-- polish:off -->\n\n\\![Diagram <!-- polish:on -->](d.svg)\n\nRead old prose.\n',
         '<!-- polish:off -->\n\n\\![Diagram <!-- polish:on -->](d.svg)\n\nRead new prose.\n'),
        ('prose after a footnote closer on a bullet after 256 items reworded',
         'See[^1].\n\n<!-- polish:off -->\n\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- [^1]: Note <!-- polish:on -->\n\nRead old prose.\n',
         'See[^1].\n\n<!-- polish:off -->\n\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- Entry item.\n- [^1]: Note <!-- polish:on -->\n\nRead new prose.\n'),
        ('prose with a star in code right after display math reworded',
         '$$\nx*y\n$$\nThe `a*b` value is approximate.\n',
         '$$\nx*y\n$$\nThe `a*b` value is estimated.\n'),
        ("a table cell outside markdown-it's emphasis across cells reworded",
         '| *a | b* |\n| --- | --- |\n| c old | d |\n',
         '| *a | b* |\n| --- | --- |\n| c new | d |\n'),
        ('a lazy line after a quoted table without code reworded',
         '> | a | b |\n> | --- | --- |\nlazy text old\n',
         '> | a | b |\n> | --- | --- |\nlazy text new\n'),
        ('a table cell next to closed code spans reworded',
         '| Name | Value |\n| --- | --- |\n| `a` old | `b` |\n',
         '| Name | Value |\n| --- | --- |\n| `a` new | `b` |\n'),
        ('a table cell with an escaped pipe in code, a link and emphasis reworded',
         '| Name | Value |\n| --- | --- |\n| `a \\| b` old | [x](/u) *y* |\n',
         '| Name | Value |\n| --- | --- |\n| `a \\| b` new | [x](/u) *y* |\n')]:
    accepts("R3 " + name, src, cand)
for name, doc in (("32000 display math blocks in one paragraph", "$$x$$\n" * 32000 + "Ordinary prose.\n"),):
    started = time.process_time()
    accepts("R3 " + name + " unchanged", doc, doc)
    report("R3 " + name + " checked within two seconds", time.process_time() - started < 2.0,
           "%.2fs" % (time.process_time() - started))

for name, src, cand in [
        ('a protected sentence after a closer in code markdown-it reads on from a quoted table with HTML',
         'Start <!-- polish:off -->keep.\n\n> | Name | Value |\n> | --- | --- |\n> | <br> | `example |\nlazy <!-- polish:on -->` end.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n> | Name | Value |\n> | --- | --- |\n> | <br> | `example |\nlazy <!-- polish:on -->` end.\n\nRead new prose.\n'),
        ('a protected sentence after a marker in image text that markdown-it reads with a refused link inside',
         'Start <!-- polish:off -->keep.\n\n![Opening [ in [sample](file:///tmp/sample.md "Use ] here") <!-- polish:on -->](diagram.svg)\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n![Opening [ in [sample](file:///tmp/sample.md "Use ] here") <!-- polish:on -->](diagram.svg)\n\nRead new prose.\n'),
        ("a delimiter row inside markdown-it's code span respaced",
         '| Name | `Value |\n| --- | --- |\n| one | two` |\n',
         '| Name | `Value |\n|  --- | --- |\n| one | two` |\n'),
        ('emphasis markdown-it reads from TeX math across table cells moved',
         '| Expression | Explanation |\n| --- | --- |\n| \\(x*y\\) | The value* is approximate. |\n',
         '| Expression | Explanation |\n| --- | --- |\n| \\(x*y\\) | The value *is approximate. |\n'),
        ('emphasis markdown-it reads past a link text across table rows moved',
         '| *Name | [Value*](/guide) |\n| --- | --- |\n| The value* is approximate. | Other prose |\n',
         '| *Name | [Value*](/guide) |\n| --- | --- |\n| The value *is approximate. | Other prose |\n'),
        ('a protected sentence after a closer in code markdown-it reads from a paragraph into a footnote',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\nRun `echo <!-- polish:on -->\n[^1]: done` here.\n\nRead old prose.\n',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\nRun `echo <!-- polish:on -->\n[^1]: done` here.\n\nRead new prose.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('a table cell after a bracket in a code span reworded',
         '| Token | Meaning |\n| --- | --- |\n| `[` | The old opening bracket. |\n',
         '| Token | Meaning |\n| --- | --- |\n| `[` | The new opening bracket. |\n'),
        ('a table cell after a bracket in a link title reworded',
         '| Link | Notes |\n| --- | --- |\n| [guide](/u "Use [ to open a label") | Read the old explanation. |\n',
         '| Link | Notes |\n| --- | --- |\n| [guide](/u "Use [ to open a label") | Read the new explanation. |\n'),
        ('a table cell after a star in link text reworded',
         '| Type | Notes |\n| --- | --- |\n| [*.md files](/guide) | Read the old notes*. |\n',
         '| Type | Notes |\n| --- | --- |\n| [*.md files](/guide) | Read the new notes*. |\n'),
        ('prose after a closer in a paragraph right before a footnote reworded',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\nRun <!-- polish:on --> `x`\n[^1]: done here.\n\nRead old prose.\n',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\nRun <!-- polish:on --> `x`\n[^1]: done here.\n\nRead new prose.\n')]:
    accepts("R3 " + name, src, cand)
for name, doc in (("800 tables in numbered list items", "".join("%d. | Name | Value |\n%s| --- | --- |\n%s| `code` | Ordinary prose. |\n" % (k, " " * (len(str(k)) + 2), " " * (len(str(k)) + 2)) for k in range(1, 801))),
                  ("8000 table rows after a bracket in code", "| Token | Description |\n| --- | --- |\n| `[` | An opening bracket. |\n" + "| `word` | Ordinary prose. |\n" * 8000)):
    started = time.process_time()
    accepts("R3 " + name + " unchanged", doc, doc)
    report("R3 " + name + " checked within two seconds", time.process_time() - started < 2.0,
           "%.2fs" % (time.process_time() - started))

for name, src, cand in [
        ('emphasis markdown-it reads from link text with a refused file link across table cells moved',
         '| Files | Notes |\n| --- | --- |\n| [*.md files](file:///tmp/guide) | The value* is approximate. |\n',
         '| Files | Notes |\n| --- | --- |\n| [*.md files](file:///tmp/guide) | The value *is approximate. |\n'),
        ('emphasis markdown-it reads from link text holding a link across table cells moved',
         '| Guide | Notes |\n| --- | --- |\n| [Read *[setup](/setup) instructions](/guide) | The value* is approximate. |\n',
         '| Guide | Notes |\n| --- | --- |\n| [Read *[setup](/setup) instructions](/guide) | The value *is approximate. |\n'),
        ('emphasis markdown-it reads past a resolved reference into an unresolved one across cells moved',
         '| Fields | Notes |\n| --- | --- |\n| *Required [Fields*][r] | [Optional*] |\n\n[r]: /guide\n',
         '| Fields | Notes |\n| --- | --- |\n| Required* [Fields*][r] | [Optional*] |\n\n[r]: /guide\n'),
        ('a table cell inside code markdown-it opens in TeX math reworded',
         '| Expression | Notes |\n| --- | --- |\n| \\(x `sample\\) | The old value` is approximate. |\n',
         '| Expression | Notes |\n| --- | --- |\n| \\(x `sample\\) | The new value` is approximate. |\n'),
        ('a protected sentence after a closer in code opened in TeX math that runs into a footnote',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\nRun \\(x `example\\) <!-- polish:on -->\n[^1]: done` here.\n\nRead old prose.\n',
         'See[^1].\n\nStart <!-- polish:off -->keep.\n\nRun \\(x `example\\) <!-- polish:on -->\n[^1]: done` here.\n\nRead new prose.\n'),
        ('a protected sentence after a marker in image text with a link inside TeX math',
         'Start <!-- polish:off -->keep.\n\n![Diagram \\( [sample](/guide "Use ] here") \\) <!-- polish:on -->](diagram.svg)\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n![Diagram \\( [sample](/guide "Use ] here") \\) <!-- polish:on -->](diagram.svg)\n\nRead new prose.\n'),
        ('a protected sentence after a closer in code markdown-it reads from a footnote into the next one',
         'Start <!-- polish:off -->keep.\n\n[^11]: Note `old <!-- polish:on --> y\n[^12]: The command is `echo old\n\nProse after old.\n',
         'Start <!-- polish:off -->keep.\n\n[^11]: Note `old <!-- polish:on --> y\n[^12]: The command is `echo old\n\nProse after new.\n'),
        ('a protected sentence after a closer in code markdown-it reads between quoted footnotes',
         'Start <!-- polish:off -->keep.\n\n> [^11]: Note `old <!-- polish:on --> y\n[^12]: The command is `echo old\n\nProse after old.\n',
         'Start <!-- polish:off -->keep.\n\n> [^11]: Note `old <!-- polish:on --> y\n[^12]: The command is `echo old\n\nProse after new.\n'),
        ('a protected sentence after a closer in image text markdown-it reads into the next footnote',
         'Start <!-- polish:off -->keep.\n\n[^11]: Note ![old <!-- polish:on --> y\n[^12]: The command](x.png) old\n\nProse after old.\n',
         'Start <!-- polish:off -->keep.\n\n[^11]: Note ![old <!-- polish:on --> y\n[^12]: The command](x.png) old\n\nProse after new.\n'),
        ('prose inside code that opens in TeX math reworded',
         'Use \\(x `sample\\) and the old value` here.\n',
         'Use \\(x `sample\\) and the new value` here.\n'),
        ('prose inside code that opens in TeX math reworded on the next line',
         'Use \\(x `sample\\) and the\nold value` here.\n',
         'Use \\(x `sample\\) and the\nnew value` here.\n'),
        ('a protected sentence after a closer in code that opens in TeX math',
         'Start <!-- polish:off -->keep.\n\nUse \\(x `a\\) <!-- polish:on --> b` c.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\nUse \\(x `a\\) <!-- polish:on --> b` c.\n\nRead new prose.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose next to TeX math reworded',
         'Use \\(x + y\\) and the old value here.\n',
         'Use \\(x + y\\) and the new value here.\n'),
        ('prose next to TeX math and closed code reworded',
         'Use \\(x\\) and `code` with the old value here.\n',
         'Use \\(x\\) and `code` with the new value here.\n'),
        ('prose after a closer between two footnotes with nothing running on reworded',
         'See[^11] and [^12].\n\n[^11]: Note <!-- polish:off --> keep <!-- polish:on --> y\n[^12]: The command.\n\nProse after old.\n',
         'See[^11] and [^12].\n\n[^11]: Note <!-- polish:off --> keep <!-- polish:on --> y\n[^12]: The command.\n\nProse after new.\n'),
        ('a table cell next to an undefined bracket pair reworded',
         '| Done | Task |\n| --- | --- |\n| [x] *a* | Read the old notes. |\n| [ ] b | More. |\n',
         '| Done | Task |\n| --- | --- |\n| [x] *a* | Read the new notes. |\n| [ ] b | More. |\n'),
        ('a table cell next to a reference with closed emphasis reworded',
         '| Link | Notes |\n| --- | --- |\n| [*a*][r] | Read the old notes. |\n\n[r]: /u\n',
         '| Link | Notes |\n| --- | --- |\n| [*a*][r] | Read the new notes. |\n\n[r]: /u\n')]:
    accepts("R3 " + name, src, cand)
for name, doc in (("1500 paragraphs with references before footnotes", "See[^1].\n\n" + "".join("Para [x][r%d] *e* `c`.\n[^%d]: Note *f* %d.\n\n" % (k % 3, k, k) for k in range(1500)) + "[r0]: /a\n[r1]: /b\n[r2]: /c\n"),
                  ("2000 table rows with TeX math, code and links", "| a | b |\n| --- | --- |\n" + "".join("| \\(x_%d\\) | `c` [a](/u) *e* |\n" % k for k in range(2000)))):
    started = time.process_time()
    accepts("R3 " + name + " unchanged", doc, doc)
    report("R3 " + name + " checked within two seconds", time.process_time() - started < 2.0,
           "%.2fs" % (time.process_time() - started))

for name, src, cand in [
        ('emphasis the renderers read from a star in TeX math moved',
         'Use \\(x*y\\) and the value* is approximate.\n',
         'Use \\(x*y\\) and the value *is approximate.\n'),
        ('emphasis the renderers read from a star in dollar math moved',
         'Use $2*x$ and the value* is approximate.\n',
         'Use $2*x$ and the value *is approximate.\n'),
        ('emphasis the renderers read from a star in display TeX math moved',
         'Use \\[x*y\\] and the value* now.\n',
         'Use \\[x*y\\] and the value * now.\n'),
        ('emphasis markdown-it reads through a refused file link moved',
         '*a old b* and [*.md](file:///x) then v* old.\n',
         '*a old b * and [*.md](file:///x) then v* old.\n'),
        ('emphasis markdown-it reads through a refused file link ended',
         '*a old b* and [*.md](file:///x) then v* old.\n',
         '*a old b* and [*.md](file:///x) then v * old.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose next to a star in TeX math reworded',
         'Use \\(x*y\\) and the old value here.\n',
         'Use \\(x*y\\) and the new value here.\n'),
        ('emphasis after a star in TeX math reworded',
         'Use \\(x*y\\) and *the old value* here.\n',
         'Use \\(x*y\\) and *the new value* here.\n'),
        ('underscore emphasis after subscripts in TeX math reworded',
         'Use \\(a_1 + b_2\\) and _the old value_ here.\n',
         'Use \\(a_1 + b_2\\) and _the new value_ here.\n'),
        ('emphasis around a refused file link reworded',
         'Read *the [old](file:///x) notes* here.\n',
         'Read *the [new](file:///x) notes* here.\n')]:
    accepts("R3 " + name, src, cand)
for name, src, cand in [
        ('code the renderers read in the tail of link text holding a link reworded',
         'Read [the [setup](/setup) guide](/guide "Use ` here") and old prose` now.\n',
         'Read [the [setup](/setup) guide](/guide "Use ` here") and new prose` now.\n'),
        ('code the renderers read in the tail of link text holding a reference reworded',
         'Read [the [setup] guide](/guide "Use ` here") and old prose` now.\n\n[setup]: /s\n',
         'Read [the [setup] guide](/guide "Use ` here") and new prose` now.\n\n[setup]: /s\n'),
        ('a protected sentence after a closer in code in the tail of link text holding a link',
         'Start <!-- polish:off -->keep.\n\nRead [the [setup](/setup) guide](/guide "Use ` here") <!-- polish:on --> x` now.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\nRead [the [setup](/setup) guide](/guide "Use ` here") <!-- polish:on --> x` now.\n\nRead new prose.\n'),
        ('a protected sentence after a closer in code after a resolved and an unresolved reference',
         'Start <!-- polish:off -->keep.\n\n[guide][s](/manual "Use ` here") [guide][r](/manual "Use ` here") <!-- polish:on --> more` text.\n\nRead old prose.\n\n[r]: /guide\n',
         'Start <!-- polish:off -->keep.\n\n[guide][s](/manual "Use ` here") [guide][r](/manual "Use ` here") <!-- polish:on --> more` text.\n\nRead new prose.\n\n[r]: /guide\n'),
        ('a link title across table cells after escaped parentheses in TeX math reworded',
         '| Formula | Notes |\n| --- | --- |\n| \\(x [guide](guide\\(draft\\).html "Setup | old notes")\\) |\n',
         '| Formula | Notes |\n| --- | --- |\n| \\(x [guide](guide\\(draft\\).html "Setup | new notes")\\) |\n'),
        ('a protected sentence after a marker in image text with a link to escaped parentheses in TeX math',
         'Start <!-- polish:off -->keep.\n\n![Diagram \\(see [the guide](guide\\(draft\\).html "Use ] to close")\\) <!-- polish:on -->](diagram.svg)\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\n![Diagram \\(see [the guide](guide\\(draft\\).html "Use ] to close")\\) <!-- polish:on -->](diagram.svg)\n\nRead new prose.\n'),
        ('emphasis the renderers read from a star in TeX math removed',
         'Use \\(x*y\\) and the value* today.\n',
         'Use \\(x*y\\) and the *value today.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('a table cell next to two defined references with emphasis inside reworded',
         '| Link | Notes |\n| --- | --- |\n| [*Guide*][guide] | Read the old notes. |\n| [*API*][api] | More details. |\n\n[guide]: /guide\n[api]: /api\n',
         '| Link | Notes |\n| --- | --- |\n| [*Guide*][guide] | Read the new notes. |\n| [*API*][api] | More details. |\n\n[guide]: /guide\n[api]: /api\n'),
        ('prose after a closer in a footnote in a list item before the next item reworded',
         'See[^11] and [^12].\n\nStart <!-- polish:off -->keep.\n\n1. [^11]: The ` character <!-- polish:on --> is literal.\n2. [^12]: Run `echo ok`.\n\nRead old prose.\n',
         'See[^11] and [^12].\n\nStart <!-- polish:off -->keep.\n\n1. [^11]: The ` character <!-- polish:on --> is literal.\n2. [^12]: Run `echo ok`.\n\nRead new prose.\n'),
        ('prose after a link title holding a backtick reworded',
         'Read [the guide](/guide "Use ` here") and old prose` now.\n',
         'Read [the guide](/guide "Use ` here") and new prose` now.\n'),
        ('prose after link text holding a link reworded',
         'Read [the [setup](/setup) guide](/guide) and the old prose.\n',
         'Read [the [setup](/setup) guide](/guide) and the new prose.\n'),
        ('prose after an image holding a link reworded',
         'See ![a [b](/c) d](i.png "t ` x") and old` y.\n',
         'See ![a [b](/c) d](i.png "t ` x") and new` y.\n')]:
    accepts("R3 " + name, src, cand)
for name, doc in (("3000 table rows with references", "| a | b |\n| --- | --- |\n" + "".join("| [x][r%d] *e* | [y][r%d] _f_ |\n" % (k % 3, (k + 1) % 3) for k in range(3000)) + "\n[r0]: /a\n[r1]: /b\n[r2]: /c\n"),
                  ("2000 paragraphs with TeX math and links to escaped parentheses", "".join("Use \\(x [g](g\\(d\\).html \"t\")\\) and *e* `c`.\n\n" for k in range(2000)))):
    started = time.process_time()
    accepts("R3 " + name + " unchanged", doc, doc)
    report("R3 " + name + " checked within two seconds", time.process_time() - started < 2.0,
           "%.2fs" % (time.process_time() - started))

for name, src, cand in [
        ('a protected sentence after an opener markdown-it reads past a link inside image text inside link text',
         'Read [the ![a [setup](/setup) diagram](image.png) guide](/guide "Use ` here") <!-- polish:off --> keep ` now.\n\nRead old prose.\n',
         'Read [the ![a [setup](/setup) diagram](image.png) guide](/guide "Use ` here") <!-- polish:off --> keep ` now.\n\nRead new prose.\n'),
        ('a protected sentence after a closer in code that only a mix of resolved references reads',
         'Start <!-- polish:off -->keep.\n\nRead [notes][t](/notes "Use ` here") and `sample [manual][s](/manual "Type `` here") then [guide][r](/guide "Use ` here") sample`` <!-- polish:on --> ` now.\n\nRead old prose.\n\n[r]: /guide\n[t]: /notes\n\n```markdown\n[s]: /manual\n```\n',
         'Start <!-- polish:off -->keep.\n\nRead [notes][t](/notes "Use ` here") and `sample [manual][s](/manual "Type `` here") then [guide][r](/guide "Use ` here") sample`` <!-- polish:on --> ` now.\n\nRead new prose.\n\n[r]: /guide\n[t]: /notes\n\n```markdown\n[s]: /manual\n```\n'),
        ('emphasis the renderers read from a star after a resolved reference in TeX math removed',
         'Use \\(x [guide][r](x*y)\\) and the value* is approximate.\n\n[r]: /guide\n',
         'Use \\(x [guide][r](x*y)\\) and the value *is approximate.\n\n[r]: /guide\n'),
        ('emphasis markdown-it reads from a star in a refused destination in TeX math removed',
         'Use \\(x [guide](file:///x*y)\\) and the value* is approximate.\n',
         'Use \\(x [guide](file:///x*y)\\) and the value *is approximate.\n'),
        ('emphasis markdown-it reads from a star in a refused destination removed',
         'Use [guide](file:///x*y) and the value* is approximate.\n',
         'Use [guide](file:///x*y) and the value *is approximate.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose after a refused link inside link text reworded',
         'Read [the [local copy](file:///tmp/guide.md) notes](/guide) for the old details.\n',
         'Read [the [local copy](file:///tmp/guide.md) notes](/guide) for the new details.\n'),
        ('prose after a link inside image text inside link text reworded',
         'Read [the ![a [setup](/setup) diagram](image.png) guide](/guide) for the old details.\n',
         'Read [the ![a [setup](/setup) diagram](image.png) guide](/guide) for the new details.\n'),
        ('prose after a star in a refused destination reworded',
         'Use [guide](file:///x*y) and the old value here.\n',
         'Use [guide](file:///x*y) and the new value here.\n'),
        ('an open image before a link split into text',
         'Press ![ and then [setup](/setup) to start the old run.\n',
         'Press ! [ and then [setup](/setup) to start the new run.\n'),
        ('an open image around a link across lines split into text',
         'Read <![CDATA[ alpha here\nmore beta](/gamma) words.\n',
         'Read <! [CDATA[ alpha here\nmore beta](/gamma) words.\n')]:
    accepts("R3 " + name, src, cand)
for name, doc in (("3000 open images before 3000 links", "![" * 3000 + " text " + "[a](/u) " * 3000 + "\n"),
                  ("2000 paragraphs with a link in image text in link text", "".join("Read [the ![a [s](/s) d](i.png) g](/g \"t\") and *e* `c`.\n\n" for k in range(2000)))):
    started = time.process_time()
    accepts("R3 " + name + " unchanged", doc, doc)
    report("R3 " + name + " checked within two seconds", time.process_time() - started < 2.0,
           "%.2fs" % (time.process_time() - started))

for name, src, cand in [
        ('emphasis markdown-it reads past a link inside a refused image removed',
         'Read [the ![a [setup](/setup) *diagram](file:///image.png) guide](/guide) and the value* is approximate.\n',
         'Read [the ![a [setup](/setup) *diagram](file:///image.png) guide](/guide) and the value *is approximate.\n'),
        ('emphasis after a link inside TeX math removed',
         'Use \\(x [*guide](/guide) and x*y\\) and the value* is approximate.\n',
         'Use \\(x [*guide](/guide) and x*y\\) and the value *is approximate.\n'),
        ('the destination of a link inside link text after an image with a backtick title changed',
         'Read [the [the ![diagram](image.png "Use ` here") guide](old "Guide") notes](/notes "Type ` here") now.\n',
         'Read [the [the ![diagram](image.png "Use ` here") guide](new "Guide") notes](/notes "Type ` here") now.\n'),
        ('the title of a link inside link text after an image with a backtick title changed',
         'Read [the [the ![diagram](image.png "Use ` here") guide](old "Guide") notes](/notes "Type ` here") now.\n',
         'Read [the [the ![diagram](image.png "Use ` here") guide](old "Guides") notes](/notes "Type ` here") now.\n'),
        ('a protected sentence after a closer markdown-it reads in code after nested refused images',
         'Start <!-- polish:off -->keep.\n\nRead ![overview with [the ![setup diagram](file:///setup.png "Type `") guide](/guide "Type ``")](overview.png "Type `") `sample <!-- polish:on --> more`` now.\n\nRead old prose.\n',
         'Start <!-- polish:off -->keep.\n\nRead ![overview with [the ![setup diagram](file:///setup.png "Type `") guide](/guide "Type ``")](overview.png "Type `") `sample <!-- polish:on --> more`` now.\n\nRead new prose.\n'),
        ('a protected sentence after an opener in code markdown-it reads as text after a stray bracket and backtick',
         'Press [ then `<!-- polish:off -->` and a stray ` here.\n\nThe old prose.\n',
         'Press [ then `<!-- polish:off -->` and a stray ` here.\n\nThe new prose.\n'),
        ('emphasis markdown-it reads from a star in code after a stray bracket and backtick removed',
         'Press [ then `*x` and the value* is ` here.\n',
         'Press [ then `*x` and the value *is ` here.\n')]:
    rejects("R3 " + name, src, cand)
for name, src, cand in [
        ('prose in code that ends before a refused image reworded',
         'Read [the ![a [setup](/setup) diagram](file:///image.png) guide](/guide "Use ` here") then `old prose` now.\n',
         'Read [the ![a [setup](/setup) diagram](file:///image.png) guide](/guide "Use ` here") then `new prose` now.\n'),
        ('prose after a stray bracket, code and a stray backtick reworded',
         'Press [ then `ls` and a stray ` here with the old prose.\n',
         'Press [ then `ls` and a stray ` here with the new prose.\n'),
        ('prose after a link inside TeX math reworded',
         'Use \\(x [guide](/guide) y\\) and the old value.\n',
         'Use \\(x [guide](/guide) y\\) and the new value.\n'),
        ('prose after a star in code reworded',
         'Use `*x` and the old value* here.\n',
         'Use `*x` and the new value* here.\n')]:
    accepts("R3 " + name, src, cand)
for name, doc in (("2000 paragraphs with a stray bracket, code and a stray backtick", "".join("Press [ then `ls %d` and a stray ` here with *e*.\n\n" % k for k in range(2000))),
                  ("2000 paragraphs with nested images, refused links and code", "".join("Read ![o [t ![s](file:///s.png \"T `\") g](/g \"T ``\")](o.png \"T `\") `s` *e* ``m``.\n\n" for k in range(2000)))):
    started = time.process_time()
    accepts("R3 " + name + " unchanged", doc, doc)
    report("R3 " + name + " checked within two seconds", time.process_time() - started < 2.0,
           "%.2fs" % (time.process_time() - started))

# Round 4: the ordered link sequence (R3-M1), code after an indented quote
# marker (R3-M2) and the blank lines after a footnote in a list (R3-M4).
QUOTE_FENCE = '>\n    > ```\n> Keep old text.\n> ```\n\nRead plain text.\n'
FOOTNOTE_LIST = '- Read [^n].\n  [^n]: - Note.\n\n- Next.\n'
for name, src, cand in [
        ('a reference link after link text with brackets removed',
         'Read [the [guide]][ref][ref] here.\n\n[ref]: /guide\n',
         'Read [the [guide]][ref]ref] here.\n\n[ref]: /guide\n'),
        ('a second full reference turned into text',
         'Read [a][r] and [b][r] here.\n\n[r]: /x\n',
         'Read [a][r] and [b]r] here.\n\n[r]: /x\n'),
        ('a reference image after alt text with brackets removed',
         'See ![the [pic]][r][r] now.\n\n[r]: /p.png\n',
         'See ![the [pic]][r]r] now.\n\n[r]: /p.png\n'),
        ('a failed inline link tail before a reference spaced',
         'Read [r](word][r] now.\n\n[r]: /0\n',
         'Read [r](word ][r] now.\n\n[r]: /0\n'),
        ('a failed nested tail before a reference spaced',
         'Read  *_[r](a(b)][r]  now.\n\n[r]: /0\n\n[word]: /1\n',
         'Read  *_[r](a(b) ][r]  now.\n\n[r]: /0\n\n[word]: /1\n'),
        ('code after an indented quote marker after an empty quote changed', QUOTE_FENCE,
         QUOTE_FENCE.replace('old', 'new')),
        ('a tilde fence after an indented quote marker changed', QUOTE_FENCE.replace('```', '~~~'),
         QUOTE_FENCE.replace('```', '~~~').replace('old', 'new')),
        ('an unclosed fence after an indented quote marker changed',
         '>\n    > ```\n> Keep old text.\n\nRead plain text.\n',
         '>\n    > ```\n> Keep new text.\n\nRead plain text.\n'),
        ('a fence after a tab and a quote marker changed', QUOTE_FENCE.replace('    >', '\t>', 1),
         QUOTE_FENCE.replace('    >', '\t>', 1).replace('old', 'new')),
        ('a fence after an indented nested quote marker changed',
         '> >\n    > > ```\n> > Keep old text.\n> > ```\n\nRead plain text.\n',
         '> >\n    > > ```\n> > Keep new text.\n> > ```\n\nRead plain text.\n'),
        ('a fence after an indented quote marker in a list item changed',
         '- >\n      > ```\n  > Keep old text.\n\nRead plain text.\n',
         '- >\n      > ```\n  > Keep new text.\n\nRead plain text.\n'),
        ('an HTML block after an indented quote marker changed',
         '>\n    > <div>\n> Keep old text.\n> </div>\n\nRead plain text.\n',
         '>\n    > <div>\n> Keep new text.\n> </div>\n\nRead plain text.\n'),
        ('a comment after an indented quote marker changed',
         '>\n    > <!--\n> Keep old text.\n> -->\n\nRead plain text.\n',
         '>\n    > <!--\n> Keep new text.\n> -->\n\nRead plain text.\n'),
        ('a space added to the blank line after a footnote in a list', FOOTNOTE_LIST,
         FOOTNOTE_LIST.replace('.\n\n-', '.\n \n-')),
        ('a space removed from the blank line after a footnote in a list',
         FOOTNOTE_LIST.replace('.\n\n-', '.\n \n-'), FOOTNOTE_LIST),
        ('the blank line after a footnote in a list widened past the content column',
         FOOTNOTE_LIST.replace('.\n\n-', '.\n  \n-'), FOOTNOTE_LIST.replace('.\n\n-', '.\n     \n-')),
        ('the blank line after a footnote before a continuation paragraph widened',
         '- Read [^n].\n  [^n]: - Note.\n\n  Next.\n', '- Read [^n].\n  [^n]: - Note.\n     \n  Next.\n'),
        ('the blank line after a quoted footnote in a list changed',
         '> - Read [^n].\n>   [^n]: - Note.\n>\n> - Next.\n', '> - Read [^n].\n>   [^n]: - Note.\n> \n> - Next.\n'),
        ('the blank line after a footnote in a nested list changed',
         '- a\n  - Read [^n].\n    [^n]: - Note.\n\n  - Next.\n',
         '- a\n  - Read [^n].\n    [^n]: - Note.\n  \n  - Next.\n'),
        ('the blank line after a footnote ending in a fence changed',
         '- Read [^n].\n  [^n]: ```\n  code\n  ```\n\n- Next.\n',
         '- Read [^n].\n  [^n]: ```\n  code\n  ```\n \n- Next.\n'),
        ('a fence after a quote marker and a tab changed',
         '>\n    >\t```\n> Keep old text.\n> ```\n\nRead plain text.\n',
         '>\n    >\t```\n> Keep new text.\n> ```\n\nRead plain text.\n'),
        ('indented code after the quote an indented quote marker continued changed',
         '>\n    > ```\n> plain text.\n    Keep old text.\n', '>\n    > ```\n> plain text.\n    Keep new text.\n'),
        ('a reference link next to a tag whose attribute holds "](" removed',
         '<span title="](">[r][r][` ]( ` now.\n\n[r]: /guide\n', '<span title="](">r][r][` ]( ` now.\n\n[r]: /guide\n'),
        ('a fence in a list item inside a quote an indented quote marker continued changed',
         '> -\n    >     ```\n>   Read old text.\n', '> -\n    >     ```\n>   Read new text.\n'),
        # (Kept on purpose: any fence-like text after the marker freezes
        # the quoted lines, whatever the list columns.)
        ('prose after an overindented fence-like line behind an indented quote marker reworded',
         '>\n    >     ```\n> Read old text.\n', '>\n    >     ```\n> Read new text.\n')]:
    rejects("R4 " + name, src, cand)
for name, src, cand in [
        ('link text with brackets and the prose around it reworded',
         'Read [the [guide]][ref][ref] here.\n\n[ref]: /guide\n',
         'Please read the [the [guide]][ref][ref] now.\n\n[ref]: /guide\n'),
        ('the text of a full reference link reworded',
         'Read [the guide][ref] here.\n\n[ref]: /guide\n',
         'Please read [the full guide][ref] here.\n\n[ref]: /guide\n'),
        ('prose before an autolink and a link reworded',
         '<https://example.com> and [x](y) here.\n',
         'See <https://example.com> and [x](y) here.\n'),
        ('prose after the region an indented quote marker opened reworded', QUOTE_FENCE,
         QUOTE_FENCE.replace('Read plain', 'Please read the plain')),
        ('the item after a footnote in a list reworded', FOOTNOTE_LIST,
         FOOTNOTE_LIST.replace('- Next.', '- The next one.')),
        ('the item after a footnote and a blank line with spaces reworded',
         FOOTNOTE_LIST.replace('.\n\n-', '.\n  \n-'),
         FOOTNOTE_LIST.replace('.\n\n-', '.\n  \n-').replace('- Next.', '- The next one.')),
        ('a paragraph right after the quote an indented quote marker continued reworded',
         '>\n    > ```\nRead old text.\n', '>\n    > ```\nRead new text.\n'),
        ('prose next to a reference inside a tag whose attribute holds "](" reworded',
         '<span title="](">Read [the guide][r] here.</span>\n\n[r]: /guide\n',
         '<span title="](">See [the guide][r] here.</span>\n\n[r]: /guide\n')]:
    accepts("R4 " + name, src, cand)

sys.exit(1 if FAILED else 0)
