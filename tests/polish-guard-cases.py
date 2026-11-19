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


def accepts(name, source, candidate):
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
rejects("link destination suffix after TeX-like escapes changed", "Read [guide](folder\\(old\\)tail) carefully.\n",
        "Read [guide](folder\\(old\\)evil) carefully.\n", "protected_token")
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
accepts("prose after a standalone region's polish:on stays editable",
        "Intro.\n\n<!-- polish:off -->\nKeep.\n<!-- polish:on --> Read carefully.\n",
        "Intro.\n\n<!-- polish:off -->\nKeep.\n<!-- polish:on --> Read with care.\n")
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
rejects("R3 emphasis inside references with more than four possible labels",
        "Read [*a*][r1] [*b*][r2] [*c*][r3] [*d*][r4] [*e*][r5].\n\n<!-- polish:off -->\n"
        "[r1]: /1\n[r2]: /2\n[r3]: /3\n[r4]: /4\n[r5]: /5\n<!-- polish:on -->\n",
        "See [*a*][r1] [*b*][r2] [*c*][r3] [*d*][r4] [*e*][r5].\n\n<!-- polish:off -->\n"
        "[r1]: /1\n[r2]: /2\n[r3]: /3\n[r4]: /4\n[r5]: /5\n<!-- polish:on -->\n", "inline_markup")

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
        ('an indented line after a definition reworded',
         '[ref]: /url\n    Read this.\n',
         '[ref]: /url\n    See this.\n'),
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
        ('prose at the end of emphasis around a long identifier reworded',
         'Read _load_application_configuration_from_environment_variables_and_settings_files_now old wording_ here.\n',
         'Read _load_application_configuration_from_environment_variables_and_settings_files_now old phrasing_ here.\n'),
        ('the space inside a spaced unit removed',
         'Wait 30 s now.\n',
         'Wait 30s now.\n')]:
    accepts("R3 " + name, src, cand)

sys.exit(1 if FAILED else 0)
