"""Deterministic fidelity guard for readability-only polishing.

The guard compares a source document with a candidate rewrite and accepts the
candidate only when everything that can be checked mechanically is preserved:

- block structure (headings, paragraphs, list items, table rows and so on),
  matched one-to-one and in order;
- list nesting, list markers, task boxes and blockquote depth;
- byte-identical regions (front matter, fenced and indented code, HTML
  blocks, math, footnote and reference definitions, and text between the
  ``<!-- polish:off -->`` and ``<!-- polish:on -->`` markers);
- protected tokens inside each block, with the same values in the same order;
- inline markup (HTML tags, link and image syntax, emphasis markers and hard
  line breaks);
- the set of writing scripts in each block and their approximate shares;
- per-block and per-document length ratios.

It also provides the HTML adapter: extraction of eligible visible text into
segments, splicing polished segments back by source offset, and re-parse
verification of everything that is not eligible text.

The guard cannot prove that meaning is unchanged. Same-script translation,
changed negations or obligations, and Simplified/Traditional Chinese
conversion are not detectable here and need a human or model review.

This module performs no I/O and uses only the Python standard library.
"""

import html
import html.entities
import html.parser
import re
import unicodedata

# ----------------------------------------------------------------------------
# Tunables
# ----------------------------------------------------------------------------

BLOCK_RATIO_BOUNDS = (0.5, 2.0)
DOC_RATIO_BOUNDS = (0.6, 1.8)
# Units shorter than this (in characters) are exempt from the ratio bounds.
# They are held to an absolute growth limit instead: the candidate may be at
# most max(len * high, len + SHORT_GROWTH_CHARS) characters long.
RATIO_MIN_CHARS = 40
SHORT_GROWTH_CHARS = 12
# Script shares are compared only when a block has at least this many letters.
SCRIPT_SHARE_MIN_LETTERS = 20
SCRIPT_SHARE_TOLERANCE = 0.25

POLISH_OFF = "<!-- polish:off -->"
POLISH_ON = "<!-- polish:on -->"


class GuardReject(Exception):
    """Raised when a candidate fails a fidelity check."""

    def __init__(self, reason, detail):
        Exception.__init__(self, "%s: %s" % (reason, detail))
        self.reason = reason
        self.detail = detail


class UnsupportedInput(Exception):
    """Raised when the source cannot be modeled safely."""

    def __init__(self, reason, detail):
        Exception.__init__(self, "%s: %s" % (reason, detail))
        self.reason = reason
        self.detail = detail


def parse_ratio_bounds(text, default):
    """Parse "LOW:HIGH" into a (low, high) tuple; return default if invalid."""
    if not text:
        return default
    parts = text.split(":")
    if len(parts) != 2:
        return default
    try:
        low = float(parts[0])
        high = float(parts[1])
    except ValueError:
        return default
    if low <= 0 or high <= low:
        return default
    return (low, high)


# ----------------------------------------------------------------------------
# Writing scripts
# ----------------------------------------------------------------------------


def char_script(ch):
    """Return the writing script of a letter, or None for non-letters."""
    o = ord(ch)
    if (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF
            or 0x20000 <= o <= 0x2FA1F):
        return "han"
    if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9F:
        return "kana"
    if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
        return "hangul"
    if 0x0400 <= o <= 0x052F:
        return "cyrillic"
    if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF:
        return "arabic"
    if not ch.isalpha():
        return None
    if o < 0x0250 or 0x1E00 <= o <= 0x1EFF or 0xFF21 <= o <= 0xFF5A:
        return "latin"
    return "other"


def script_profile(text):
    counts = {}
    for ch in text:
        s = char_script(ch)
        if s:
            counts[s] = counts.get(s, 0) + 1
    return counts


def check_scripts(src_text, cand_text, where):
    ps = script_profile(src_text)
    pc = script_profile(cand_text)
    if set(ps) != set(pc):
        raise GuardReject(
            "script_changed",
            "%s: writing scripts changed from %s to %s"
            % (where, ",".join(sorted(ps)) or "none", ",".join(sorted(pc)) or "none"))
    total_s = sum(ps.values())
    total_c = sum(pc.values())
    if total_s >= SCRIPT_SHARE_MIN_LETTERS and total_c > 0:
        for name in ps:
            share_s = float(ps[name]) / total_s
            share_c = float(pc[name]) / total_c
            if abs(share_s - share_c) > SCRIPT_SHARE_TOLERANCE:
                raise GuardReject(
                    "script_changed",
                    "%s: share of %s letters changed from %.2f to %.2f"
                    % (where, name, share_s, share_c))


# ----------------------------------------------------------------------------
# Protected tokens and inline markup
# ----------------------------------------------------------------------------

CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
# Inline math, using the Pandoc rule: "$" opens when followed by a non-space,
# and closes when preceded by a non-space and not followed by a digit. The
# math may continue over soft line breaks inside one prose unit. So "$2 x + y$" is math, while in "$5 or $10" the second "$" is
# preceded by a space and cannot close, and the text stays prose. "$$...$$"
# inside a line is math too; "\(...\)" and "\[...\]" are found by the inline
# scanner.
INLINE_MATH_RE = re.compile(
    r"\$\$[^$]*?[^\s$][^$]*?\$\$"
    r"|(?<![\\$])\$(?=[^\s$])[^$]*?(?<=[^\s\\])\$(?!\d)")
# Text between inline polish:off and polish:on markers, or from a polish:off
# marker to the end of the unit when the region continues past it.
INLINE_PROTECTED_RE = re.compile(r"<!--\s*polish:off\s*-->.*?(?:<!--\s*polish:on\s*-->|\Z)", re.S)
POLISH_OFF_LINE_RE = re.compile(r"^\s*<!--\s*polish:off\s*-->\s*$")
POLISH_ON_LINE_RE = re.compile(r"^\s*<!--\s*polish:on\s*-->\s*$")
POLISH_ON_RE = re.compile(r"<!--\s*polish:on\s*-->")
# Placeholder for the two characters of a backslash escape: it keeps link
# targets and URLs that contain an escape in one piece, but is not markup.
ESCAPE_HOLD = "\ue000"
# A fence opener or closer on a line, after any quote or list-marker prefix.
FENCE_LINE_RE = re.compile(r"^(?:[ \t]*>)*[ \t]*(?:(?:[-+*]|\d{1,9}[.)])[ \t]+)?(`{3,}|~{3,})(.*)$")
POLISH_OFF_RE = re.compile(r"<!--\s*polish:off\s*-->")
# ASCII punctuation that a backslash escapes in CommonMark.
ESCAPABLE = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
AUTOLINK_RE = re.compile(
    r"<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*|[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+)>")
# Inline links and images are found by _scan_links, which balances brackets
# and parentheses to any depth up to this limit.
LINK_NESTING_LIMIT = 32
REF_LINK_RE = re.compile(r"(!?)\[((?:\\.|[^\[\]\\])+)\]\[((?:\\.|[^\[\]\\])*)\]")
FOOTNOTE_REF_RE = re.compile(r"\[\^[^\]\s]+\]")
# Any other bracketed text may be a shortcut reference link whose label is
# its text, so it is protected as a whole.
SHORTCUT_REF_RE = re.compile(r"!?\[(?:\\.|[^\[\]\\])+\](?![(\[])")
# HTML tags by the CommonMark grammar: a ">" inside a quoted attribute value
# does not end the tag. A tag that does not fit the grammar falls back to the
# looser form, which ends at the first ">".
_HTML_ATTR = (r"\s+[A-Za-z_:][A-Za-z0-9_.:-]*"
              r"(?:\s*=\s*(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?")
HTML_OPEN_TAG = r"<[A-Za-z][A-Za-z0-9-]*(?:" + _HTML_ATTR + r")*\s*/?>"
HTML_CLOSE_TAG = r"</[A-Za-z][A-Za-z0-9-]*\s*>"
# Raw inline HTML that is not an element tag: comments, processing
# instructions, declarations and CDATA sections, each through its own
# terminator (they may span lines). They are kept byte for byte.
HTML_OTHER_RAW = (r"<!---?>|<!--.*?-->|<\?.*?\?>|<![A-Za-z][^>]*>"
                  r"|<!\[CDATA\[.*?\]\]>")
HTML_STRICT_TAG_RE = re.compile(HTML_OTHER_RAW + "|" + HTML_OPEN_TAG + "|" + HTML_CLOSE_TAG, re.S)
HTML_TAG_RE = re.compile(
    HTML_OTHER_RAW + "|" + HTML_OPEN_TAG + "|" + HTML_CLOSE_TAG
    + r"|</?[A-Za-z][A-Za-z0-9-]*(?:\s+[^<>]*?)?\s*/?>", re.S)
ENTITY_RE = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]{1,31}|#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6});")
URL_RE = re.compile(r"\b(?:https?|ftp|file)://[^\s<>\"'`]+|\bwww\.[^\s<>\"'`]+")

WORD_TOKEN_RE = re.compile(
    r"""
      (?P<path>(?<![\w./~-])(?:(?:~[\w.-]*|\.{1,2})?/[\w@+.-]+(?:/[\w@+.-]*)*
                                |[\w@+.-]+(?:/[\w@+.-]*)+))
    | (?P<call>[A-Za-z_][\w.]*\(\))
    | (?P<scope>[A-Za-z_]\w*(?:::\w+)+)
    | (?P<flag>(?<![\w-])--[A-Za-z0-9][\w-]*)
    | (?P<var>(?<![\w$])\$\{?[A-Za-z_]\w*\}?)
    | (?P<ident>(?<!\w)(?=\w*_)(?=\w*[A-Za-z0-9])\w+)
    | (?P<qty>(?<![\w.])\d+(?:\.\d+)?
        (?:[ ]?(?:ns|us|ms|secs?|seconds?|mins?|minutes?|hrs?|hours?|days?|weeks?
                 |months?|years?|[KMGTP]i?B|kB|bytes?|bits?|[KMG]bps|px|rem|em|pt|[kMG]?Hz)
          |(?:s|h|d|B|k|K|M|G|x|%))
        (?![\w%]))
    | (?P<dotted>[\w-]+(?:\.[\w-]+)+)
    | (?P<camel>(?![A-Z]+s\b)[A-Za-z0-9]*(?:[a-z][A-Z]|[A-Z]{2}[a-z])[A-Za-z0-9]*)
    | (?P<digit>[\w.:+/-]*\d[\w.:+/-]*)
    """,
    re.X | re.A,
)

# A run of ASCII letters, digits and path punctuation long enough to be a
# hash, encoded data or a long identifier rather than a prose word. It is one
# protected word: the word patterns would otherwise retry every alternative
# at each position of the run, which takes time quadratic in its length.
LONG_RUN_RE = re.compile(r"[\w@+.:/~-]{%d,}" % 48, re.A)

# Slash pairs that are ordinary prose rather than paths.
# Word pairs with a slash that are ordinary prose, not paths.
PROSE_SLASH_PAIRS = frozenset([
    "and/or", "either/or", "he/she", "his/her", "him/her", "s/he", "yes/no", "read/write",
    "true/false", "on/off", "input/output", "before/after", "pros/cons", "start/stop",
    "open/close", "online/offline", "if/then", "if/else", "plus/minus"])
# Dotted abbreviations made of one-letter segments that are ordinary prose.
PROSE_ABBREVIATIONS = frozenset(["e.g", "i.e", "a.k.a", "n.b", "p.s", "a.m", "p.m", "u.s", "u.k"])
# Emphasis delimited by underscores, such as "_word_" or "__two words__".
UNDERSCORE_EMPHASIS_RE = re.compile(r"(?<![\w\\])(_{1,2})(?=[^\s_])(?:(?!\1).)+?(?<=[^\s_])\1(?!\w)")
MARKUP_TOKEN_KINDS = ("tag", "rawtag", "link", "image", "reflink", "autolink", "footnote", "escape")


def _mask(chars, start, end):
    for k in range(start, end):
        if chars[k] != "\n":
            chars[k] = " "


def _normalize_tag(tag):
    """Collapse whitespace in an element tag outside quoted attribute values.
    Comments, processing instructions, declarations and CDATA are kept as
    written."""
    if tag.startswith(("<!", "<?")):
        return tag
    parts = re.split(r"(\"[^\"]*\"|'[^']*')", tag)
    for k in range(0, len(parts), 2):
        parts[k] = re.sub(r"\s+", " ", parts[k])
    return "".join(parts)


def _strip_url(url):
    url = url.rstrip(".,;:!?'\"")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1].rstrip(".,;:!?'\"")
    return url


def _skip_space(text, i):
    while i < len(text) and text[i] in " \t\n":
        i += 1
    return i


OPAQUE_RE = re.compile(AUTOLINK_RE.pattern + "|" + HTML_STRICT_TAG_RE.pattern, re.S)


def _opaque_end(text, i):
    """End of the code span, autolink or raw HTML that starts at ``i``, or
    None. These bind more tightly than link brackets, so a bracket inside
    them is text. A backtick run with no closing run is skipped as text."""
    if text[i] == "`":
        run = 1
        while i + run < len(text) and text[i + run] == "`":
            run += 1
        j = i + run
        while j < len(text):
            if text[j] != "`":
                j += 1
                continue
            k = j
            while k < len(text) and text[k] == "`":
                k += 1
            if k - j == run:
                return k
            j = k
        return i + run
    if text[i] == "<":
        m = OPAQUE_RE.match(text, i)
        if m:
            return m.end()
    return None


def _label_end(text, start):
    """Index of the "]" closing the label opened at ``start``, or -1 (-2 when nested too deep)."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch in "`<":
            end = _opaque_end(text, i)
            if end is not None:
                i = end
                continue
        if ch == "[":
            depth += 1
            if depth > LINK_NESTING_LIMIT:
                return -2
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _link_tail(text, open_paren):
    """Parse "(destination title)" starting at ``open_paren``.

    Returns (end, target) for a link, (None, False) when the text is not a
    link, and (None, True) when it is nested beyond LINK_NESTING_LIMIT.
    """
    n = len(text)
    i = _skip_space(text, open_paren + 1)
    dest_start = i
    if i < n and text[i] == "<":
        i += 1
        while i < n and text[i] not in "<>\n":
            i += 2 if (text[i] == "\\" and i + 1 < n) else 1
        if i >= n or text[i] != ">":
            return None, False
        i += 1
    else:
        depth = 0
        while i < n:
            ch = text[i]
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == "(":
                depth += 1
                if depth > LINK_NESTING_LIMIT:
                    return None, True
            elif ch == ")":
                if depth == 0:
                    break
                depth -= 1
            elif ch in " \t\n" or ord(ch) < 32:
                break
            i += 1
        if depth:
            return None, False
    dest_end = i
    j = _skip_space(text, i)
    if j < n and j > dest_end and text[j] in "\"'(":
        close = ")" if text[j] == "(" else text[j]
        k = j + 1
        while k < n and text[k] != close:
            if text[k] == "\\" and k + 1 < n:
                k += 2
                continue
            if close == ")" and text[k] == "(":
                return None, False
            k += 1
        if k >= n:
            return None, False
        j = _skip_space(text, k + 1)
    if j < n and text[j] == ")":
        return j + 1, text[dest_start:j].strip()
    return None, False


def _scan_links(text, resolve=None, original=None):
    """Find inline links and images, with balanced brackets and parentheses.

    Returns (links, unmodeled): ``links`` holds (start, label_start, label_end,
    end, kind, target) tuples, where ``target`` is the destination with its
    optional title; ``unmodeled`` is True when a link-shaped construct is
    nested beyond LINK_NESTING_LIMIT.

    With ``resolve`` (see _scan_refs), a full or collapsed reference whose
    label is defined is a link of its own: its reference label is not read
    as the text of an inline link (in "[a][b](c)" with "b" defined, "(c)" is
    text). ``original`` (same length as ``text``) gives the label text.
    """
    if original is None:
        original = text
    links = []
    unmodeled = False
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch in "`<":
            opaque = _opaque_end(text, i)
            if opaque is not None:
                i = opaque
                continue
        if ch != "[":
            i += 1
            continue
        close = _label_end(text, i)
        if close == -2:
            unmodeled = True
            break
        if resolve is not None and close >= 0 and close + 1 < n and text[close + 1] == "[":
            second = _ref_label_close(text, close + 1)
            if second is not None:
                label = original[close + 2:second]
                if not label and not re.search(r"[\[\]]", text[i + 1:close]):
                    label = original[i + 1:close]
                inner, inner_unmodeled = _scan_links(text[i + 1:close], resolve, original[i + 1:close])
                if (label.strip() and resolve(label) == "yes"
                        and not any(k == "link" for _, _, _, _, k, _ in inner)):
                    for (a, b, c, d, kind, target) in inner:
                        links.append((a + i + 1, b + i + 1, c + i + 1, d + i + 1, kind, target))
                    if inner_unmodeled:
                        unmodeled = True
                        break
                    i = second + 1
                    continue
        if close < 0 or close + 1 >= n or text[close + 1] != "(":
            i += 1
            continue
        end, info = _link_tail(text, close + 1)
        if end is None:
            if info:
                unmodeled = True
                break
            i += 1
            continue
        start = i - 1 if i > 0 and text[i - 1] == "!" else i
        links.append((start, i + 1, close, end, "image" if start < i else "link", info))
        # Links and images inside the label (an image inside a link, for
        # example) have destinations of their own.
        inner, inner_unmodeled = _scan_links(text[i + 1:close], resolve, original[i + 1:close])
        for (a, b, c, d, kind, target) in inner:
            links.append((a + i + 1, b + i + 1, c + i + 1, d + i + 1, kind, target))
        if inner_unmodeled:
            unmodeled = True
            break
        i = end
    return links, unmodeled


REF_LABEL_LIMIT = 999


def _ref_label_close(text, open_bracket):
    """Index of the "]" ending the link label (no unescaped brackets, at most
    999 characters) that opens at ``open_bracket``, or None."""
    i = open_bracket + 1
    while i < len(text) and i - open_bracket <= REF_LABEL_LIMIT + 1:
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2
            continue
        if ch == "[":
            return None
        if ch == "]":
            return i
        i += 1
    return None


def _scan_refs(masked, original, resolve, offset=0):
    """Reference links and images in ``masked`` (a prose unit whose code,
    autolinks and inline link syntax are already masked; ``original`` has the
    same length and gives the label text).

    ``resolve`` maps a label to "yes", "maybe" or "no". Returns
    (label_start, label_end, kind, status, key) for every full, collapsed or
    shortcut reference whose label is, or may be, defined; ``key`` is the
    normalized label that decides whether it resolves. Their link text is
    scanned for nested references too.
    """
    out = []
    n = len(masked)
    i = 0
    while i < n:
        ch = masked[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch in "`<":
            opaque = _opaque_end(masked, i)
            if opaque is not None:
                i = opaque
                continue
        if ch != "[":
            i += 1
            continue
        close = _label_end(masked, i)
        if close < 0:
            i += 1
            continue
        # A collapsed or shortcut reference uses the link text as its label,
        # which then may not hold brackets.
        text_label = None if re.search(r"[\[\]]", masked[i + 1:close]) else original[i + 1:close]
        end = close + 1
        label = text_label
        second = _ref_label_close(masked, end) if end < n and masked[end] == "[" else None
        if second is not None:
            # "[text][label]" (full) or "[text][]" (collapsed). A label of
            # only whitespace is not a label, and the text is no link.
            inner = original[end + 1:second]
            label = inner if inner.strip() else (text_label if not inner else None)
            end = second + 1
        status = resolve(label) if label is not None and label.strip() else "no"
        if status == "no":
            i += 1
            continue
        kind = "image" if i > 0 and masked[i - 1] == "!" else "link"
        out.append((offset + i + 1, offset + close, kind, status, normalize_label(label)))
        out.extend(_scan_refs(masked[i + 1:close], original[i + 1:close], resolve,
                              offset + i + 1))
        i = end
    return out


def _scan_inline(text):
    """Find code spans, TeX math and backslash escapes in one left-to-right pass.

    Returns (kind, start, end, value) tuples. Scanning in order gets escape
    parity right: in "\\\\*" the backslash is escaped and the star is active,
    an escaped backtick never opens a code span, and backslashes inside a
    code span are literal.
    """
    out = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt in "([":
                closer = "\\)" if nxt == "(" else "\\]"
                end = text.find(closer, i + 2)
                if end >= 0:
                    out.append(("math", i, end + 2, text[i:end + 2]))
                    i = end + 2
                    continue
            if nxt in ESCAPABLE:
                out.append(("escape", i, i + 2, text[i:i + 2]))
                i += 2
                continue
            i += 1
            continue
        if ch == "`":
            run = 1
            while i + run < n and text[i + run] == "`":
                run += 1
            j = i + run
            close = -1
            while j < n:
                if text[j] == "`":
                    k = j
                    while k < n and text[k] == "`":
                        k += 1
                    if k - j == run:
                        close = j
                        break
                    j = k
                else:
                    j += 1
            if close >= 0:
                out.append(("code", i, close + run, text[i + run:close]))
                i = close + run
            else:
                i += run
            continue
        i += 1
    return out


def extract_tokens(text, labels=None, refs=None, maybe=None):
    """Return (tokens, masked) for a prose fragment.

    ``tokens`` is an ordered list of (kind, value) pairs. ``masked`` is the
    text with every token replaced by spaces, so the remaining characters are
    the editable prose; emphasis markers inside a protected reference label
    are kept, as they still pair with others.

    ``labels`` collects the label spans of links and images, which are
    boundaries for emphasis. ``refs`` is the document's (definite, possible)
    reference labels, or None when the fragment stands alone (a segment);
    the labels of references that may or may not resolve go to ``maybe``,
    each as (start, end, key): labels with the same key resolve together.
    """
    chars = list(text)
    found = []
    unhide = []

    def resolve(label):
        if refs is None:
            return "maybe"
        norm = normalize_label(label)
        if norm in refs[0]:
            return "yes"
        return "maybe" if norm in refs[1] else "no"

    def current():
        return "".join(chars)

    for kind, start, end, value in _scan_inline(current()):
        found.append((start, kind, value))
        if kind == "escape":
            # Hide the escaped punctuation from the markup patterns but keep
            # the position occupied, so a link target or URL that contains an
            # escape is still one token.
            chars[start] = ESCAPE_HOLD
            chars[start + 1] = ESCAPE_HOLD
        else:
            _mask(chars, start, end)

    # After code spans, so a marker quoted inside inline code is just text.
    for m in INLINE_PROTECTED_RE.finditer(current()):
        found.append((m.start(), "protected", m.group(0)))
        _mask(chars, m.start(), m.end())

    for m in INLINE_MATH_RE.finditer(current()):
        found.append((m.start(), "math", m.group(0)))
        _mask(chars, m.start(), m.end())

    for m in AUTOLINK_RE.finditer(current()):
        found.append((m.start(), "autolink", m.group(0)))
        _mask(chars, m.start(), m.end())

    links, _ = _scan_links(current(), resolve, text)
    for start, label_start, label_end, end, kind, target in links:
        found.append((start, kind, target))
        # Keep the link text editable; mask the syntax and the target.
        _mask(chars, start, label_start)
        _mask(chars, label_end, end)

    if labels is not None:
        # Link and image labels are boundaries for emphasis: inline links,
        # and reference links whose label the document defines (with the
        # same bracket scanner). CommonMark does not nest links, so a "link"
        # that holds another link is text, and its brackets are no boundary
        # (its destination is still protected here). A reference that may
        # or may not resolve gives a possible boundary; one whose boundary
        # also depends on references inside it gets a key of its own, so
        # every combination is checked.
        spans = [(ls, le, kind, "yes", None) for _, ls, le, _, kind, _ in links]
        spans += _scan_refs(current(), text, resolve)
        nested = 0
        for ls, le, kind, status, key in spans:
            if kind == "link":
                inner = [s[3] for s in spans
                         if s[2] == "link" and ls <= s[0] and s[1] <= le and (s[0], s[1]) != (ls, le)]
                if "yes" in inner:
                    continue
                if inner:
                    status = "maybe"
                    key = ("nested", nested)
                    nested += 1
            if status == "yes":
                labels.append((ls, le))
            elif maybe is not None:
                maybe.append((ls, le, key))

    snapshot = current()
    for m in REF_LINK_RE.finditer(snapshot):
        kind = "reflink"
        if not m.group(3).strip():
            # Collapsed reference "[label][]": the text is the label.
            found.append((m.start(), kind, m.group(0)))
            unhide.extend((k, snapshot[k]) for k in range(m.start(), m.end()) if snapshot[k] in "*_~")
            _mask(chars, m.start(), m.end())
            continue
        found.append((m.start(), kind, (m.group(1) or "") + "[" + m.group(3) + "]"))
        # The reference label is protected. When it does not resolve, the
        # brackets are text and its emphasis markers pair with others; when
        # it may resolve, it is also a possible boundary.
        status = resolve(m.group(3))
        if status != "yes":
            unhide.extend((k, snapshot[k]) for k in range(m.end(2), m.end()) if snapshot[k] in "*_~")
            if status == "maybe" and maybe is not None:
                maybe.append((m.start(3), m.end(3), normalize_label(m.group(3))))
        _mask(chars, m.start(), m.start(2))
        _mask(chars, m.end(2), m.end())

    for m in FOOTNOTE_REF_RE.finditer(current()):
        found.append((m.start(), "footnote", m.group(0)))
        _mask(chars, m.start(), m.end())

    snapshot = current()
    for m in SHORTCUT_REF_RE.finditer(snapshot):
        found.append((m.start(), "reflink", m.group(0)))
        # The bracketed text is protected as a whole, as it may be a link
        # label; its emphasis markers still pair with those around it when
        # it is not a link.
        unhide.extend((k, snapshot[k]) for k in range(m.start(), m.end()) if snapshot[k] in "*_~")
        _mask(chars, m.start(), m.end())

    for m in HTML_TAG_RE.finditer(current()):
        found.append((m.start(), "tag", _normalize_tag(m.group(0))))
        _mask(chars, m.start(), m.end())

    for m in ENTITY_RE.finditer(current()):
        found.append((m.start(), "entity", m.group(0)))
        _mask(chars, m.start(), m.end())

    for m in URL_RE.finditer(current()):
        url = _strip_url(m.group(0))
        found.append((m.start(), "url", url))
        _mask(chars, m.start(), m.start() + len(url))

    for m in LONG_RUN_RE.finditer(current()):
        value = m.group(0).rstrip(".:,;-")
        found.append((m.start(), "word", value))
        _mask(chars, m.start(), m.start() + len(value))

    # Hide underscore emphasis delimiters from the identifier patterns so
    # "_some text_" stays prose, then restore them for the emphasis count.
    # Dunder names such as "__init__" stay identifiers.
    hidden = []
    for m in UNDERSCORE_EMPHASIS_RE.finditer(current()):
        delim = m.group(1)
        if delim == "__" and re.fullmatch(r"__\w+__", m.group(0), re.A):
            continue
        width = len(delim)
        for k in list(range(m.start(), m.start() + width)) + list(range(m.end() - width, m.end())):
            hidden.append((k, chars[k]))
            chars[k] = "\x01"

    for m in WORD_TOKEN_RE.finditer(current()):
        kind = m.lastgroup
        value = m.group(0)
        if kind == "path" and value.lower() in PROSE_SLASH_PAIRS:
            continue
        if kind in ("digit", "dotted", "path"):
            value = value.rstrip(".:,;")
        if kind == "dotted" and value.lower() in PROSE_ABBREVIATIONS:
            continue
        if kind == "qty":
            value = value.replace(" ", "")
            found.append((m.start(), "word", value))
            _mask(chars, m.start(), m.end())
            continue
        if not value:
            continue
        found.append((m.start(), "word", value))
        _mask(chars, m.start(), m.start() + len(value))

    for k, ch in hidden:
        chars[k] = ch
    for k, ch in unhide:
        chars[k] = ch

    # Link destinations, autolinks and URLs are read again from the original
    # text: code-span, math or escape syntax inside a destination is part of
    # the destination, so masking it above must not leave the rest editable.
    links, unmodeled = _scan_links(text)
    for start, _, _, _, _, target in links:
        found.append((start, "dest", target))
    if unmodeled:
        # A link nested beyond the scanner's limit: the whole unit is frozen.
        found.append((0, "frozen", text))
    for m in AUTOLINK_RE.finditer(text):
        found.append((m.start(), "dest", m.group(0)))
    # HTML tags that fit the strict grammar, read from the original text too,
    # so code or math masking elsewhere in the unit cannot split a tag.
    for m in HTML_STRICT_TAG_RE.finditer(text):
        found.append((m.start(), "rawtag", _normalize_tag(m.group(0))))
    for m in URL_RE.finditer(text):
        found.append((m.start(), "dest", _strip_url(m.group(0))))

    found.sort(key=lambda item: item[0])
    tokens = [(kind, value) for _, kind, value in found]
    return tokens, "".join(chars)


EMPHASIS_RUN_RE = re.compile(r"\*+|_+|~+")


def _flank_class(ch):
    if ch is None or ch.isspace():
        return "space"
    if unicodedata.category(ch)[0] in "PS":
        return "punct"
    return "other"


def _delimiter_runs(original, masked):
    """Emphasis delimiter runs in ``masked`` (so markers inside code, math or
    URLs are text), each with whether it can open or close emphasis by the
    CommonMark flanking rules, read against the characters of ``original``."""
    ref = original if len(original) == len(masked) else masked
    runs = []
    for m in EMPHASIS_RUN_RE.finditer(masked):
        ch, size = m.group(0)[0], len(m.group(0))
        if ch == "~" and size != 2:
            continue
        before = _flank_class(ref[m.start() - 1] if m.start() > 0 else None)
        after = _flank_class(ref[m.end()] if m.end() < len(ref) else None)
        left = after != "space" and (after != "punct" or before != "other")
        right = before != "space" and (before != "punct" or after != "other")
        if ch == "_":
            if before == "other" and after == "other":
                # An underscore inside a word is text.
                continue
            can_open = left and (not right or before == "punct")
            can_close = right and (not left or after == "punct")
        else:
            can_open, can_close = left, right
        runs.append({"ch": ch, "pos": m.start(), "orig": size, "count": size,
                     "open": can_open, "close": can_close})
    return runs


def _pair_delimiters(stack, spans, literal):
    """Pair the delimiter runs in ``stack`` (in text order) with the CommonMark
    "process emphasis" rules, including the rule of three; ``~~`` pairs as
    strikethrough. Adds (start, end, kind) to ``spans`` and counts the
    delimiters that stay literal in ``literal``."""

    def drop(run):
        if run["count"]:
            key = run["ch"] if run["ch"] != "~" else "~~"
            literal[key] = literal.get(key, 0) + (run["count"] if run["ch"] != "~" else 1)

    ci = 0
    while ci < len(stack):
        closer = stack[ci]
        if not closer["close"]:
            ci += 1
            continue
        found = None
        for oi in range(ci - 1, -1, -1):
            opener = stack[oi]
            if opener["ch"] != closer["ch"] or not opener["open"]:
                continue
            if closer["ch"] == "~":
                found = oi
                break
            if ((opener["close"] or closer["open"])
                    and (opener["orig"] + closer["orig"]) % 3 == 0
                    and not (opener["orig"] % 3 == 0 and closer["orig"] % 3 == 0)):
                continue
            found = oi
            break
        if found is None:
            if not closer["open"]:
                drop(closer)
                del stack[ci]
            else:
                ci += 1
            continue
        opener = stack[found]
        if closer["ch"] == "~":
            use, kind = 2, "del"
        elif opener["count"] >= 2 and closer["count"] >= 2:
            use, kind = 2, "strong" + closer["ch"]
        else:
            use, kind = 1, "em" + closer["ch"]
        span_start = opener["pos"] + opener["count"] - use
        span_end = closer["pos"] + (closer["orig"] - closer["count"]) + use
        spans.append((span_start, span_end, kind))
        opener["count"] -= use
        closer["count"] -= use
        for run in stack[found + 1:ci]:
            drop(run)
        del stack[found + 1:ci]
        ci = found + 1
        if opener["count"] == 0:
            del stack[found]
            ci -= 1
        if closer["count"] == 0:
            del stack[ci]
    for run in stack:
        drop(run)


def emphasis_structure(original, masked, labels=()):
    """The emphasis a prose unit renders, independent of the words inside.

    Delimiter runs are paired with the CommonMark rules. Runs inside a link
    or image label pair only with each other (innermost label first), as a
    label is closed before the text around it. The result is the nesting of
    the spans (em and strong with their delimiter character, and del), with
    siblings in sorted order so emphasis can move with its words, plus the
    delimiters that stay literal. Moving a marker away from its word,
    regrouping markers, or swapping ``*`` and ``_`` changes the result.
    """
    runs = _delimiter_runs(original, masked)
    spans = []
    literal = {}
    used = set()
    for label_start, label_end in sorted(labels, key=lambda lb: lb[1] - lb[0]):
        inside = [r for r in runs if id(r) not in used and label_start <= r["pos"] < label_end]
        used.update(id(r) for r in inside)
        _pair_delimiters(inside, spans, literal)
    _pair_delimiters([r for r in runs if id(r) not in used], spans, literal)

    # Spans nest properly; build the forest and describe it without order.
    spans.sort(key=lambda sp: (sp[0], -sp[1]))
    children = {None: []}
    open_spans = []
    for idx, (a, b, kind) in enumerate(spans):
        while open_spans and not (a >= spans[open_spans[-1]][0] and b <= spans[open_spans[-1]][1]):
            open_spans.pop()
        parent = open_spans[-1] if open_spans else None
        children.setdefault(parent, []).append(idx)
        children[idx] = []
        open_spans.append(idx)

    def describe(idx):
        inner = sorted(describe(c) for c in children[idx])
        return spans[idx][2] + "(" + ",".join(inner) + ")"

    forest = sorted(describe(c) for c in children[None])
    return forest, sorted(literal.items())


def _blank_out(chars, start, end, fill):
    for k in range(start, end):
        if chars[k] != "\n":
            chars[k] = fill


def hard_break_count(text):
    """The number of hard line breaks in a prose unit: a line end after two
    or more spaces, or after an odd number of backslashes (in an even run the
    backslashes escape each other). Line ends inside code spans, math,
    autolinks or raw HTML are not breaks, so those spans are replaced by a
    non-space character first."""
    chars = list(text)
    for kind, start, end, _ in _scan_inline(text):
        if kind in ("code", "math"):
            _blank_out(chars, start, end, "\x02")
    for regex in (INLINE_MATH_RE, AUTOLINK_RE, HTML_STRICT_TAG_RE):
        for m in regex.finditer("".join(chars)):
            _blank_out(chars, m.start(), m.end(), "\x02")
    count = 0
    for line in "".join(chars).split("\n")[:-1]:
        body = line.rstrip(" ")
        if len(line) - len(body) >= 2:
            count += 1
        elif len(body) == len(line) and (len(body) - len(body.rstrip("\\"))) % 2 == 1:
            count += 1
    return count


def visible_length(text):
    return len(re.sub(r"\s+", " ", text).strip())


def check_ratio(src_len, cand_len, bounds, where):
    if src_len <= 0:
        return
    if src_len < RATIO_MIN_CHARS:
        limit = max(int(src_len * bounds[1]), src_len + SHORT_GROWTH_CHARS)
        if cand_len > limit:
            raise GuardReject(
                "length_ratio",
                "%s: a %d-character unit grew to %d characters (limit %d)"
                % (where, src_len, cand_len, limit))
        return
    ratio = float(cand_len) / float(src_len)
    if ratio < bounds[0] or ratio > bounds[1]:
        raise GuardReject(
            "length_ratio",
            "%s: length ratio %.2f is outside %.2f-%.2f" % (where, ratio, bounds[0], bounds[1]))


def _first_token_difference(a, b):
    for idx in range(max(len(a), len(b))):
        x = a[idx] if idx < len(a) else None
        y = b[idx] if idx < len(b) else None
        if x != y:
            return idx, x, y
    return None


AMBIGUOUS_LABEL_LIMIT = 4


def _check_emphasis(src, src_masked, src_labels, src_maybe,
                    cand, cand_masked, cand_labels, cand_maybe, where):
    """Compare emphasis with every combination of the possible link labels
    (references that may or may not resolve) as boundaries. A possible label
    matters only when emphasis markers sit inside it. Labels that share a
    reference label resolve together, so the combinations are taken over
    the distinct reference labels."""
    if [m[2] for m in src_maybe] != [m[2] for m in cand_maybe]:
        raise GuardReject("inline_markup", "%s: bracketed text changed" % where)

    def has_markers(masked, span):
        return bool(re.search(r"[*_~]", masked[span[0]:span[1]]))

    relevant = [k for k in range(len(src_maybe))
                if has_markers(src_masked, src_maybe[k]) or has_markers(cand_masked, cand_maybe[k])]
    keys = []
    for k in relevant:
        if src_maybe[k][2] not in keys:
            keys.append(src_maybe[k][2])
    if len(keys) > AMBIGUOUS_LABEL_LIMIT:
        raise GuardReject(
            "inline_markup",
            "%s: emphasis markers inside bracketed texts with more than %d different labels that may "
            "be links" % (where, AMBIGUOUS_LABEL_LIMIT))
    for bits in range(1 << len(keys)):
        on = [key for idx, key in enumerate(keys) if bits >> idx & 1]
        chosen = [k for k in relevant if src_maybe[k][2] in on]
        if (emphasis_structure(src, src_masked, src_labels + [src_maybe[k][:2] for k in chosen])
                != emphasis_structure(cand, cand_masked, cand_labels + [cand_maybe[k][:2] for k in chosen])):
            raise GuardReject("inline_markup", "%s: emphasis markers changed" % where)


def compare_prose(src, cand, where, block_ratio=BLOCK_RATIO_BOUNDS, markup_chars=False, refs=None):
    """Compare one prose unit (a paragraph, heading, list item, cell or segment).

    ``refs`` is the document's (definite, possible) reference labels; None
    for a segment, whose references may or may not resolve."""
    if markup_chars:
        for ch in "<>":
            if cand.count(ch) > src.count(ch):
                raise GuardReject("markup_in_text", "%s: candidate adds %r" % (where, ch))
    src_labels, cand_labels, src_maybe, cand_maybe = [], [], [], []
    src_tokens, src_masked = extract_tokens(src, src_labels, refs, src_maybe)
    cand_tokens, cand_masked = extract_tokens(cand, cand_labels, refs, cand_maybe)
    if src_tokens != cand_tokens:
        idx, x, y = _first_token_difference(src_tokens, cand_tokens)
        kinds = set()
        if x:
            kinds.add(x[0])
        if y:
            kinds.add(y[0])
        if "protected" in kinds:
            reason = "region_changed"
        elif kinds & set(MARKUP_TOKEN_KINDS):
            reason = "inline_markup"
        else:
            reason = "protected_token"
        raise GuardReject(
            reason,
            "%s: protected token %d differs (source %r, candidate %r)" % (where, idx + 1, x, y))
    _check_emphasis(src, src_masked, src_labels, src_maybe,
                    cand, cand_masked, cand_labels, cand_maybe, where)
    if hard_break_count(src) != hard_break_count(cand):
        raise GuardReject("inline_markup", "%s: hard line breaks changed" % where)
    check_scripts(src_masked, cand_masked, where)
    src_len = visible_length(src)
    check_ratio(src_len, visible_length(cand), block_ratio, where)
    return src_len, visible_length(cand)


# ----------------------------------------------------------------------------
# Markdown and text block model
# ----------------------------------------------------------------------------

RAW_KINDS = ("frontmatter", "fence", "math", "html", "protected", "footnote_def",
             "refdef", "hr", "table_sep", "table_raw", "indented_code", "quote_raw")

QUOTE_PREFIX_RE = re.compile(r"^((?:[ ]{0,3}>[ ]?)+)")
FENCE_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})(.*)$")
ATX_RE = re.compile(r"^[ ]{0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
HR_RE = re.compile(r"^[ ]{0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
SETEXT_RE = re.compile(r"^[ ]{0,3}(=+|-+)[ \t]*$")
LIST_ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-+*]|\d{1,9}[.)])(?:[ \t]+|$)"
    r"(?P<task>\[[ xX]\](?:[ \t]+|$))?(?P<rest>.*)$")
TABLE_SEP_RE = re.compile(r"^[ \t]*\|?[ \t]*:?-{1,}:?[ \t]*(?:\|[ \t]*:?-{1,}:?[ \t]*)*\|?[ \t]*$")
FOOTNOTE_DEF_RE = re.compile(r"^[ ]{0,3}\[\^[^\]]+\]:")
# The start of a link reference definition: a label and a colon. The
# destination may be on the next line.
REFDEF_RE = re.compile(r"^[ ]{0,3}\[(?!\^)(?:\\[\s\S]|[^\[\]\\])+\]:")
# A line that may start a definition whose label continues on the next line.
REFDEF_START_RE = re.compile(r"^[ ]{0,3}\[(?!\^)")
# A complete definition: label, colon, destination (on the same or the next
# line) and an optional title, which may start on the next line and continue
# over several lines. It must end at the end of a line. ``_match_definition``
# reads it as cmark-gfm does; the destination needs a scanner of its own.
_REFDEF_HEAD_RE = re.compile(r"[ ]{0,3}\[(?:\\[\s\S]|[^\[\]\\])+\]:[ \t]*\n?[ \t]*")
_POINTY_DEST_RE = re.compile(r"<(?:\\.|[^<>\n\\])*>")
# An optional title, separated from the destination by spaces or a line end,
# then the end of the line (a backslash before the closing delimiter is a
# backslash, as in cmark-gfm). Without a title that ends its line, the
# destination must end the line itself.
_REFDEF_TAIL_RE = re.compile(
    r"(?:(?:[ \t]*\n[ \t]*|[ \t]+)"
    r"(?:\"(?:\\[\s\S]|\\|[^\"\\])*\"|'(?:\\[\s\S]|\\|[^'\\])*'|\((?:\\[\s\S]|\\|[^()\\])*\)))?"
    r"[ \t]*(?:\n|$)")
_ASCII_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_ASCII_SPACE = frozenset(" \t\n\x0b\x0c\r")


def _scan_destination(text, pos):
    """End of the link destination that starts at ``pos``, or None, as
    cmark-gfm scans one: inside angle brackets, or a bare run that ends at
    ASCII whitespace or at a closing parenthesis with none open. A backslash
    escapes ASCII punctuation; at most 32 parentheses may be open, and
    parentheses still open where the run ends are allowed."""
    if text.startswith("<", pos):
        m = _POINTY_DEST_RE.match(text, pos)
        return m.end() if m else None
    i, depth = pos, 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in _ASCII_PUNCT:
            i += 2
            continue
        if ch == "(":
            depth += 1
            if depth > 32:
                return None
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
        elif ch in _ASCII_SPACE:
            break
        i += 1
    return i if i > pos else None


def _match_definition(text):
    """End of the definition at the start of ``text`` (after the newline
    that ends it), or None when it is not one."""
    m = _REFDEF_HEAD_RE.match(text)
    if not m:
        return None
    end = _scan_destination(text, m.end())
    if end is None:
        return None
    tail = _REFDEF_TAIL_RE.match(text, end)
    return tail.end() if tail else None


# The label of a definition, which may continue over lines.
REFDEF_LABEL_RE = re.compile(r"[ ]{0,3}\[((?:\\[\s\S]|[^\[\]\\])+)\]:")
# A line in a protected region or footnote that may be a definition: the
# label after any quote or list markers.
LOOSE_REFDEF_RE = re.compile(
    r"^[ \t>]*(?:(?:[-+*]|\d{1,9}[.)])[ \t]+)*\[(?!\^)((?:\\[\s\S]|[^\[\]\\])+)\]:", re.M)
# HTML block start conditions 1 to 6 (CommonMark, with the type 6 tag
# names cmark-gfm uses); these may interrupt a paragraph.
HTML_BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|"
    "details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|"
    "h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|"
    "optgroup|option|p|param|section|source|summary|table|tbody|td|tfoot|th|thead|title|tr|"
    "track|ul")
HTML_BLOCK_RE = re.compile(
    r"^[ ]{0,3}(?:<(?:!--|!\[CDATA\[|![A-Za-z]|\?)|<(?:script|pre|style|textarea)(?:\s|>|$)"
    r"|</?(?:" + HTML_BLOCK_TAGS + r")(?:\s|/?>|$))",
    re.I)
HTML_TYPE1_RE = re.compile(r"<(?:script|pre|style|textarea)(?:\s|>|$)", re.I)
HTML_TYPE1_END_RE = re.compile(r"</(?:script|pre|style|textarea)\s*>", re.I)
# HTML block start condition 7: any other complete tag alone on its line
# (cmark-gfm also counts a closing script, pre, style or textarea tag). It
# cannot interrupt a paragraph.
HTML_LINE_TAG_RE = re.compile(
    r"^[ ]{0,3}(?:" + HTML_OPEN_TAG + "|" + HTML_CLOSE_TAG
    + r"|</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>)[ \t]*$")


class Block(object):
    __slots__ = ("kind", "attrs", "raw", "units", "line", "ref")

    def __init__(self, kind, attrs, raw, units, line, ref=None):
        self.kind = kind
        self.attrs = attrs
        self.raw = raw
        self.units = units
        self.line = line
        # For a reference definition: (normalized label, whether the parser
        # read the whole definition); for a footnote definition: how its
        # content ends. Not part of the comparison.
        self.ref = ref

    def describe(self):
        return "block at line %d (%s)" % (self.line, self.kind)


def _quote_walk(line, limit=None):
    """Read up to ``limit`` blockquote markers at the start of ``line``.

    Columns follow CommonMark: tab stops every four columns, up to three
    columns of indentation before each marker, and a tab right after a marker
    counts as the marker's optional space plus the rest of the tab (which
    then counts toward the indentation that follows). Returns the indentation
    before each marker, the end of each marker, the position after the last
    marker and its optional space, the column there, and the columns of a
    partly used tab that still belong to the text.
    """
    cols, ends = [], []
    pos = col = pending = 0
    while limit is None or len(cols) < limit:
        k, c, ind = pos, col, pending
        while k < len(line) and line[k] in " \t":
            width = 1 if line[k] == " " else 4 - c % 4
            c += width
            ind += width
            k += 1
        if ind > 3 or k >= len(line) or line[k] != ">":
            break
        cols.append(ind)
        ends.append(k + 1)
        pos, col, pending = k + 1, c + 1, 0
        if pos < len(line) and line[pos] == " ":
            pos += 1
            col += 1
        elif pos < len(line) and line[pos] == "\t":
            width = 4 - col % 4
            pos += 1
            col += width
            pending = width - 1
    return cols, ends, pos, col, pending


def _quote_depth(line):
    cols, _, pos, _, _ = _quote_walk(line)
    return len(cols), line[pos:]


def _strip_quote(line, depth):
    """Remove up to ``depth`` blockquote markers from ``line``.

    The leading whitespace of the rest is expanded to spaces at its true
    columns, so the indentation of a list item or code block inside a quote
    is measured as CommonMark measures it.
    """
    _, _, pos, col, pending = _quote_walk(line, depth)
    out = [" " * pending]
    k = pos
    while k < len(line) and line[k] in " \t":
        width = 1 if line[k] == " " else 4 - col % 4
        out.append(" " * width)
        col += width
        k += 1
    return "".join(out) + line[k:]


def _quote_rest(line, depth):
    """``line`` after up to ``depth`` quote markers, with its bytes unchanged
    (the text of a prose unit keeps its exact whitespace)."""
    return line[_quote_walk(line, depth)[2]:]


def _loose_quote_end(line, depth):
    """Position in ``line`` after ``depth`` quote markers and the optional
    space or tab after each one. Any indentation may come before a marker:
    a quote inside a list item can sit four or more columns into the line.
    Used on original lines, whose structure is already known, to find where
    their content bytes start."""
    pos = 0
    for _ in range(depth):
        k = pos
        while k < len(line) and line[k] in " \t":
            k += 1
        if k >= len(line) or line[k] != ">":
            break
        pos = k + 1
        if pos < len(line) and line[pos] in " \t":
            pos += 1
    return pos


def _quote_prefix(line, depth):
    """The first ``depth`` quote markers of ``line`` and the indentation
    before them, without the optional space after the last one."""
    _, ends, _, _, _ = _quote_walk(line, depth)
    return line[:ends[-1]] if ends else ""


def _is_html_start(body, interrupt=False):
    """Whether ``body`` starts an HTML block; with ``interrupt``, whether it
    can interrupt a paragraph (start conditions 1 to 6 only)."""
    if POLISH_OFF_LINE_RE.match(body) or POLISH_ON_LINE_RE.match(body):
        return False
    if HTML_BLOCK_RE.match(body):
        return True
    return not interrupt and bool(HTML_LINE_TAG_RE.match(body))


def _split_cells(row):
    # GFM splits a row at every pipe that is not escaped, also inside a
    # code span ("`x|y`" is two cells; "`x\\|y`" is one).
    masked = row
    positions = [k for k, ch in enumerate(masked)
                 if ch == "|" and (k == 0 or masked[k - 1] != "\\")]
    stripped_start = len(row) - len(row.lstrip())
    stripped_end = len(row.rstrip())
    cuts = [p for p in positions]
    cells = []
    prev = stripped_start
    if cuts and cuts[0] == stripped_start:
        prev = stripped_start + 1
        cuts = cuts[1:]
    if cuts and cuts[-1] == stripped_end - 1:
        last = cuts[-1]
        cuts = cuts[:-1]
    else:
        last = stripped_end
    for c in cuts:
        cells.append(row[prev:c].strip())
        prev = c + 1
    cells.append(row[prev:last].strip())
    return cells


def _is_table_sep(line):
    """A GFM delimiter row (``line`` past its containers): cells of dashes
    with optional colons, separated by pipes. A lone run of dashes is a
    setext underline (cmark-gfm reads that first) and a line that starts a
    list item is one; ":---" and "---|" are delimiter rows."""
    return ("-" in line and bool(TABLE_SEP_RE.match(line)) and not SETEXT_RE.match(line)
            and not LIST_ITEM_RE.match(line))


def _is_table_start(header, sep, lazy=False):
    """GFM: a table starts with a header row and a delimiter row that have
    the same number of cells; otherwise neither line is part of a table.
    The header row needs no pipe ("Name" above ":---" is a one-column
    table). cmark-gfm keeps the leading whitespace of a lazy line, so a
    lazy header row that starts with whitespace and then a pipe has an
    empty first cell there."""
    cells = len(_split_cells(header))
    if lazy and header[:1] in (" ", "\t") and header.lstrip(" \t").startswith("|"):
        cells += 1
    return _is_table_sep(sep) and cells == len(_split_cells(sep))


def _starts_block(body, in_paragraph):
    """True when ``body`` would start a new block instead of continuing prose.

    ``in_paragraph``: the line reaches every container of the paragraph, so
    the paragraph itself is what a new block would interrupt (cmark-gfm). A
    list item then interrupts it only when it has content and, if ordered,
    starts at 1, and an HTML block of start condition 7 cannot start;
    otherwise the line continues the paragraph. A lazy line (fewer
    containers) can start either."""
    if not body.strip():
        return True
    if POLISH_OFF_LINE_RE.match(body) or POLISH_ON_LINE_RE.match(body):
        return True
    if _indent_of(body) >= 4:
        # Four columns past the container: indented code cannot interrupt a
        # paragraph and nothing else starts there, so the line continues it.
        return False
    if FENCE_RE.match(body) or ATX_RE.match(body) or HR_RE.match(body):
        return True
    if _is_html_start(body, interrupt=in_paragraph):
        return True
    lm = LIST_ITEM_RE.match(body)
    if lm:
        if not in_paragraph:
            return True
        marker = lm.group("marker")
        if not body[lm.end("marker"):].strip():
            return False
        return marker[-1] not in ".)" or int(marker[:-1]) == 1
    # A reference definition starts only where a paragraph could start (it
    # is read from the paragraph's first lines), and a table takes it as a
    # row; a footnote definition interrupts a paragraph (cmark-gfm).
    if FOOTNOTE_DEF_RE.match(body):
        return True
    # A "$$" line does not interrupt a paragraph: display math written inside
    # a paragraph ("Use $$\na + b\n$$ here.") stays one protected math token.
    return False


# Bounds on reading footnote content (see ``footnote_end``): parses per
# definition, content lines parsed in all, at least this many and two per
# line of the document, and definitions nested inside each other.
FOOTNOTE_PARSE_LIMIT = 50
FOOTNOTE_LINE_BUDGET = 5000
FOOTNOTE_DEPTH_LIMIT = 8


def _plain_text_line(text):
    """Whether ``text`` can only be paragraph text: it starts no block, no
    quote, no setext underline and no table delimiter row at any
    indentation."""
    t = text.lstrip(" \t")
    return bool(t) and not (_starts_block(t, False) or _starts_quote(t) or SETEXT_RE.match(t)
                            or _is_table_sep(t))


# A content line that may start a reference definition, after any quote and
# list markers.
MAYBE_REFDEF_LINE_RE = re.compile(r"^[ \t>]*(?:(?:[-+*]|\d{1,9}[.)])[ \t]+)*\[(?!\^)")


def _lazy_stand_in(lazy):
    """Plain text that continues a paragraph as the lazy line ``lazy`` does
    in cmark-gfm, with as many cells if it ends up a table's header row (the
    line keeps its leading whitespace there, so a pipe after it opens an
    empty first cell)."""
    body = lazy.lstrip(" \t")
    cells = len(_split_cells(body))
    if body != lazy and body.startswith("|"):
        cells += 1
    return "|".join(["x"] * cells)


def _end_state(blocks, nlines):
    """How the last of ``nlines`` lines parsed into ``blocks`` leaves its
    content: "paragraph" when it ends in a paragraph that a lazy line may
    continue (also one that holds only reference definitions so far, or
    one kept byte for byte because another parser reads a table in it),
    "raw_open" when it ends inside an unclosed fence or raw HTML block of
    types 1 to 5, "unread" when it ends in a footnote definition too long
    to read (see ``footnote_end``), else "closed"."""
    if not blocks:
        return "closed"
    b = blocks[-1]
    end = b.line - 1 + b.raw.count("\n")
    if end != nlines - 1:
        return "closed"
    if b.kind in ("paragraph", "refdef") or (b.kind == "table_raw" and b.attrs.get("table_elsewhere")):
        return "paragraph"
    if b.kind == "footnote_def":
        return b.ref or "closed"
    raw_lines = [_strip_quote(line, b.attrs.get("quote", 0)) for line in b.raw.split("\n")]
    if b.kind == "fence":
        return "closed" if b.attrs.get("fence_closed") else "raw_open"
    if b.kind == "html":
        end_re = _html_end_marker(raw_lines[0].lstrip(" "))
        if end_re is not None and not end_re.search("\n".join(raw_lines)):
            return "raw_open"
    return "closed"

FENCE_CLOSE_RE = re.compile(r"^(`{3,}|~{3,})[ \t]*$")


def _is_fence_open(text):
    fm = FENCE_RE.match(text)
    if not fm:
        return None
    if fm.group(2)[0] == "`" and "`" in fm.group(3):
        return None
    return fm.group(2)


def _html_end_marker(body):
    """The end condition of the HTML block that ``body`` starts: a pattern
    for raw-text elements, comments, processing instructions, declarations
    and CDATA (CommonMark types 1 to 5), which end at their closing marker
    even across blank lines, or None for types 6 and 7, which end before a
    blank line."""
    stripped = body.lstrip(" ")
    if HTML_TYPE1_RE.match(stripped):
        return HTML_TYPE1_END_RE
    if stripped.startswith("<!--"):
        return re.compile(re.escape("-->"))
    if stripped.startswith("<?"):
        return re.compile(re.escape("?>"))
    if stripped.startswith("<![CDATA["):
        return re.compile(re.escape("]]>"))
    if re.match(r"<![A-Za-z]", stripped):
        return re.compile(">")
    return None


def _not_a_definition(line):
    """Whether ``line``, which starts with a label and a colon, can only be
    paragraph text whatever follows it: a destination starts on the line
    and cannot be read, or is followed on the line by something other than
    spaces and the start of a title."""
    m = REFDEF_LABEL_RE.match(line)
    if not m:
        return False
    pos = m.end()
    while pos < len(line) and line[pos] in " \t":
        pos += 1
    if pos == len(line):
        return False
    end = _scan_destination(line, pos)
    if end is None:
        return True
    rest = line[end:]
    after = rest.lstrip(" \t")
    if not after:
        return False
    return after == rest or after[0] not in "\"'("


def _read_definitions(content, parsed_only=False):
    """Read the reference definitions at the start of a paragraph whose
    lines are ``content`` (leading whitespace is ignored), as CommonMark
    does when the paragraph closes. Return a list of (first, end, label,
    parsed) entries in line indices, and the index of the first line after
    them. A line that starts like a definition this parser cannot read is
    kept with the lines up to the next one that starts a definition, as an
    unparsed definition, unless it can only be text (``_not_a_definition``),
    where reading stops. With ``parsed_only``, reading stops there instead
    (cmark-gfm checks a setext underline against the definitions it can
    read; a line it cannot read as one is paragraph text)."""
    parts = [line.lstrip(" \t") for line in content]
    out = []
    k = 0
    while k < len(parts):
        if FOOTNOTE_DEF_RE.match(parts[k]) or not REFDEF_START_RE.match(parts[k]):
            break
        joined = "\n".join(parts[k:])
        dm = _match_definition(joined)
        lm = REFDEF_LABEL_RE.match(joined)
        label = lm.group(1) if lm else None
        if dm is not None:
            end = k + joined[:dm].rstrip("\n").count("\n") + 1
            out.append((k, end, label, True))
            k = end
            continue
        if parsed_only or not REFDEF_RE.match(parts[k]) or _not_a_definition(parts[k]):
            break
        end = k + 1
        while (end < len(parts) and not REFDEF_RE.match(parts[end])
               and not FOOTNOTE_DEF_RE.match(parts[end])):
            end += 1
        out.append((k, end, label, False))
        k = end
    return out, k


def _expand_indent(text):
    """Expand tabs in the leading whitespace only; the content keeps its bytes."""
    lead = len(text) - len(text.lstrip(" \t"))
    return text[:lead].expandtabs(4) + text[lead:]


def _indent_of(text):
    expanded = _expand_indent(text)
    return len(expanded) - len(expanded.lstrip(" "))


def _past_container(text, base):
    """``text`` with up to ``base`` columns of container indentation removed."""
    expanded = _expand_indent(text)
    return expanded[min(base, _indent_of(expanded)):]


def _leaves_list_item(cols, quote, level_stacks):
    """True when one of the first ``quote`` quote markers of a line (their
    columns are ``cols``) does not reach the content column of a list item
    that encloses the deeper quote, so the line closes that item instead of
    continuing inside it."""
    for level in range(min(quote, len(cols), len(level_stacks))):
        stack = level_stacks[level]
        if stack and cols[level] < stack[-1][1]:
            return True
    return False


def _quote_marker_cols(line, depth):
    """Column of each of the first ``depth`` quote markers, each measured in
    the text that remains after the markers before it."""
    return _quote_walk(line, depth)[0]


# The structural start of a line: indentation, quote markers and list
# markers. CommonMark treats tabs there as spaces up to the next multiple of
# four columns.
STRUCT_PREFIX_RE = re.compile(r"^(?:[ \t]*(?:>|(?:[-+*]|[0-9]{1,9}[.)])(?=[ \t]|$)))*[ \t]*")
# Raw kinds whose text is a run of whole source lines.
RAW_LINE_KINDS = ("frontmatter", "fence", "math", "html", "footnote_def", "refdef",
                  "indented_code", "table_raw")


def _starts_quote(text):
    """Whether ``text`` (a line past its containers) starts a blockquote: a
    ``>`` after at most three columns of indentation."""
    stripped = text.lstrip(" ")
    return stripped.startswith(">") and len(text) - len(stripped) < 4


def _expand_structure(line):
    """``line`` with the tabs in its structural start replaced by spaces at
    their true columns; the rest of the line keeps its bytes."""
    m = STRUCT_PREFIX_RE.match(line)
    head = m.group(0)
    if "\t" not in head:
        return line
    out = []
    col = 0
    for ch in head:
        if ch == "\t":
            width = 4 - col % 4
            out.append(" " * width)
            col += width
        else:
            out.append(ch)
            col += 1
    return "".join(out) + line[m.end():]


def parse_blocks(text, spec_blank_items=False, inner=False, _budget=None):
    """Split Markdown or plain text into an ordered list of blocks.

    By default the parser follows cmark-gfm (GitHub). With
    ``spec_blank_items`` it follows the CommonMark text where cmark-gfm
    differs: a list item that starts empty and is followed by a line of
    only whitespace ends there even when that whitespace reaches the item's
    content column. ``check_document`` compares documents in that mode too
    when the difference applies, so a change must be safe under both.
    ``inner`` parses the content of a container (a footnote definition):
    there is no front matter. ``_budget`` is shared by those inner parses
    (see ``footnote_end``).

    List items are containers: a ``list_item`` block carries the marker, its
    nesting depth, and whether a blank line separates it from the previous
    item. The rest of the marker line is then read again as the first line of
    the item's content, so headings, code, HTML, quotes, definitions and
    nested items that start on a marker line are classified like any other
    block. ``container`` gives the open list items at each blockquote level,
    outermost first, so a list that encloses a quote is still part of the
    ancestry of every block inside and after that quote.
    """
    # Column computations read ``lines``, whose structural tabs are expanded
    # and whose quote and list prefixes may be moved; raw blocks and prose
    # units read the original bytes in ``orig_lines``. A line cut after a
    # polish:on marker is cut in both copies.
    orig_lines = text.split("\n")
    lines = [_expand_structure(line) for line in orig_lines]
    n = len(lines)
    # [content lines left to parse, definitions open around this parse]
    budget = _budget if _budget is not None else [max(FOOTNOTE_LINE_BUDGET, 2 * n), 0]
    blocks = []
    i = 0

    if not inner and n > 1 and lines[0] in ("---", "+++"):
        closer = lines[0]
        for j in range(1, n):
            if lines[j] == closer or (closer == "---" and lines[j] == "..."):
                blocks.append(Block("frontmatter", {}, "\n".join(lines[0:j + 1]), [], 1))
                i = j + 1
                break

    # Open list items per blockquote level, as (marker_indent, content_column)
    # measured in that level's text. A block belongs to every open item at its
    # own level whose content column it reaches. Entering a deeper quote keeps
    # the lists that enclose it; leaving a quote closes what was opened inside.
    level_stacks = [[]]
    # The true column of a quote marker inside a list item that was moved
    # left to stay within reach of the quote prefix parser:
    # line index -> {level: column}.
    marker_quote_col = {}

    def qcols_of(k, depth):
        cols = _quote_marker_cols(lines[k], depth)
        for level, col in marker_quote_col.get(k, {}).items():
            if level < len(cols):
                cols[level] = col
        return cols

    def in_container(k, quote, depth, base):
        """Whether line ``k`` stays inside the quotes and list items of the
        current block (no lazy continuation): same quote depth, quote markers
        that reach the enclosing items, indentation that reaches the item,
        and no new quote."""
        if not lines[k].strip() or relocate_quotes(k, quote) != quote:
            return False
        if quote and _leaves_list_item(qcols_of(k, quote), quote, level_stacks):
            return False
        kb = _strip_quote(lines[k], quote)
        if depth > 0 and _indent_of(kb) < base:
            return False
        rel = _past_container(kb, base)
        # Four columns past the container make the line indented code.
        return _indent_of(rel) < 4 and not _starts_quote(rel)

    def containers(quote, indent, qcols):
        """Close the list items a line at quote depth ``quote`` leaves. An
        ``indent`` of None (a line holding only quote markers) keeps the
        items at its own level open, as a blank line does."""
        del level_stacks[quote + 1:]
        while len(level_stacks) <= quote:
            level_stacks.append([])
        # A quote marker closes the list items at its level whose content
        # column it does not reach, and with them the quotes opened inside
        # those items and every list in those quotes.
        for level in range(quote):
            outer = level_stacks[level]
            closed = False
            while outer and qcols[level] < outer[-1][1]:
                outer.pop()
                closed = True
            if closed:
                for deeper in range(level + 1, len(level_stacks)):
                    level_stacks[deeper] = []
        stack = level_stacks[quote]
        while indent is not None and stack and indent < stack[-1][1]:
            stack.pop()
        base = stack[-1][1] if stack else 0
        return len(stack), base, tuple(len(level) for level in level_stacks)

    # The open blockquotes, outermost first. Each entry is the number of open
    # list items at every enclosing level when the quote opened: the quote
    # ends when a line has fewer markers, when one of those list items
    # closes, or at a blank line. Every quote that opens is a block of its
    # own ("quote"), so merging, splitting, adding or removing a quote,
    # including an empty one, changes the structure.
    open_quotes = []

    def past_matched(body, level):
        """``body`` (a line after ``level`` quote markers) past the open list
        items at that level that its indentation reaches. CommonMark matches
        list items outermost first; a new block would start after the last
        item the line reaches, so a lazy line is read from there."""
        reach = 0
        if level < len(level_stacks):
            ind = _indent_of(body)
            for _, content in level_stacks[level]:
                if ind < content:
                    break
                reach = content
        return _past_container(body, reach)

    def relocate_quotes(k, limit):
        """Move the quote markers of line ``k`` that sit four or more columns
        into the line but within every open list item at their level (as the
        relocation below does for a new quote), up to ``limit`` markers in
        all, and return the line's quote depth afterwards. Such a marker
        continues the open quote inside those items: CommonMark matches the
        items first and the marker after them."""
        depth_now = _quote_depth(lines[k])[0]
        while depth_now < limit and depth_now < len(level_stacks) and level_stacks[depth_now]:
            if depth_now and _leaves_list_item(qcols_of(k, depth_now), depth_now, level_stacks):
                break
            kb = _strip_quote(lines[k], depth_now)
            kind = _indent_of(kb)
            content = level_stacks[depth_now][-1][1]
            if kind < content or not _starts_quote(_past_container(kb, content)):
                break
            marker_quote_col.setdefault(k, {})[depth_now] = kind
            lines[k] = ((_quote_prefix(lines[k], depth_now) + " ") if depth_now else "") \
                + " " * min(kind, 3) + kb.lstrip(" ")
            depth_now = _quote_depth(lines[k])[0]
        return depth_now

    def blank_line_before(k, depth):
        """Whether the line before line ``k`` is blank inside ``depth``
        quotes (read from the original bytes)."""
        if k <= 0:
            return False
        prev = orig_lines[k - 1]
        return not prev[_loose_quote_end(prev, depth):].strip()

    def track_quotes(qdepth, ancestry, line_no):
        keep = 0
        while (keep < min(len(open_quotes), qdepth)
               and open_quotes[keep] == ancestry[:keep + 1]):
            keep += 1
        del open_quotes[keep:]
        for level in range(keep + 1, qdepth + 1):
            open_quotes.append(ancestry[:level])
            quote_attrs = {"level": level, "container": ancestry[:level]}
            if any(ancestry[:level]):
                quote_attrs["gap"] = blank_line_before(line_no - 1, level - 1)
            blocks.append(Block("quote", quote_attrs, "", [], line_no))

    def fence_end(start, quote, depth, base, fence):
        """Index of the last line of the fence opened on line ``start - 1``:
        the closing fence, or the last line before the fence's blockquote or
        list item ends (fenced code has no lazy continuation lines). A
        closing fence is indented at most three columns past its container.
        Blank and whitespace-only lines inside the container are code too.
        Returns the index and whether a closing fence ends the block."""
        last = start - 1
        j = start
        while j < n:
            if not lines[j].strip():
                if quote:
                    break
                last = j
                j += 1
                continue
            if relocate_quotes(j, quote) < quote:
                break
            if quote and _leaves_list_item(qcols_of(j, quote), quote, level_stacks):
                break
            kb = _strip_quote(lines[j], quote)
            if kb.strip():
                if depth > 0 and _indent_of(kb) < base:
                    break
                rel = _past_container(kb, base)
                cm = FENCE_CLOSE_RE.match(rel.lstrip(" "))
                if (cm and _indent_of(rel) < 4 and cm.group(1)[0] == fence[0]
                        and len(cm.group(1)) >= len(fence)):
                    return j, True
            last = j
            j += 1
        return last, False

    def html_end(start, quote, depth, base, body):
        """Index of the last line of the HTML block that starts on line
        ``start`` with ``body``: the line with its end marker, the last line
        before a blank line (types 6 and 7), or the last line before the
        block's blockquote or list item ends. HTML blocks have no lazy
        continuation lines, so a line that leaves those containers ends the
        block however it ends otherwise."""
        end_re = _html_end_marker(body)
        if end_re is not None and end_re.search(body):
            return start
        last = start
        j = start + 1
        while j < n:
            if not lines[j].strip():
                # A blank line ends a blockquote and an HTML block of type 6
                # or 7; the other types run on inside a list item.
                if end_re is None or quote:
                    break
                last = j
                j += 1
                continue
            if relocate_quotes(j, quote) < quote:
                break
            if quote and _leaves_list_item(qcols_of(j, quote), quote, level_stacks):
                break
            kb = _strip_quote(lines[j], quote)
            if not kb.strip():
                # Only quote markers: a blank line inside the quote.
                if end_re is None:
                    break
                last = j
                j += 1
                continue
            if depth > 0 and _indent_of(kb) < base:
                break
            last = j
            if end_re is not None and end_re.search(kb):
                return j
            j += 1
        return last

    def footnote_end(start, quote, base, first):
        """Index of the last line of the footnote definition that starts on
        line ``start``, whose first line holds ``first`` after the label.

        cmark-gfm reads a footnote definition as a container: a line
        belongs to it when it is indented four columns past the
        definition's own container, or when it is empty (a line of only
        spaces, or a quote line with only its marker, counts only when it
        is indented four columns too). While the definition's content ends
        in an open paragraph, a line with less indentation or fewer quote
        markers continues it lazily, unless it starts a block of its own or
        leaves an enclosing list item. Whether a paragraph is open is read
        by parsing the content so far, so lists, quotes, headings, fences,
        HTML and tables inside the definition count as they do outside.
        Blank lines at its end belong to it only when its content ends
        inside an unclosed fence or raw HTML block. Returns the index and
        how the content ends (see ``_end_state``).

        The content keeps each line's whitespace past the definition's
        column; a blank line that is not empty (cmark-gfm then checks the
        indentation of a definition nested inside) keeps at least one space.
        A lazy line is paragraph text, but read again inside the content it
        could start a block, a setext underline or a table delimiter row, or
        (with its leading whitespace dropped) be a header row with a
        different number of cells. Such a line enters the content as plain
        text with the same number of cells (``_lazy_stand_in``), unless the
        content may hold a reference definition, whose reading depends on
        the text; then the state is "unread". It is "unread" too past the
        bounds on parsing (``FOOTNOTE_PARSE_LIMIT`` parses per definition,
        a budget of content lines shared by every parse of the document,
        ``FOOTNOTE_DEPTH_LIMIT`` nested definitions). Whether an "unread"
        definition continues on a lazy line is not known, and that line
        decides how the lines after it read, so the definition then runs to
        the end of the text, kept byte for byte. Its trailing blank lines
        belong to it too."""
        content = [first]
        last = start
        pending = []  # (index, text in the content)
        state = None  # cached: "paragraph", "raw_open", "closed" or "unread"
        parses = [0]
        unread = [False]

        def content_state():
            if (unread[0] or parses[0] >= FOOTNOTE_PARSE_LIMIT or budget[1] >= FOOTNOTE_DEPTH_LIMIT
                    or budget[0] < len(content)):
                unread[0] = True
                return "unread"
            parses[0] += 1
            budget[0] -= len(content)
            budget[1] += 1
            try:
                return _content_end_state(content)
            finally:
                budget[1] -= 1

        k = start + 1
        while k < n:
            if not lines[k]:
                if quote:
                    break
                pending.append((k, ""))
                k += 1
                continue
            if not lines[k].strip():
                if quote or _indent_of(lines[k]) - base < 4:
                    break
                pending.append((k, _past_container(lines[k], base + 4) or " "))
                k += 1
                continue
            kq = relocate_quotes(k, quote)
            if kq > quote:
                break
            if kq > 0 and _leaves_list_item(qcols_of(k, kq), kq, level_stacks):
                break
            kb = _strip_quote(lines[k], kq)
            if kq == quote and _indent_of(kb) - base >= 4:
                if not kb.strip():
                    pending.append((k, _past_container(kb, base + 4) or " "))
                    k += 1
                    continue
                inner_line = _past_container(kb, base + 4)
                # A line that cannot start or end a block continues an open
                # paragraph wherever it sits, so the state needs no parse.
                if pending or state != "paragraph" or not _plain_text_line(inner_line):
                    state = None
                content.extend(text for _, text in pending)
                pending = []
                content.append(inner_line)
                last = k
                k += 1
                continue
            if pending or not kb.strip():
                break
            lazy = past_matched(kb, kq)
            if _starts_quote(lazy) or _starts_block(lazy, False):
                break
            if state is None:
                state = content_state()
            if state == "unread":
                return n - 1, state
            if state != "paragraph":
                break
            if not _plain_text_line(lazy) or (lazy[:1] in (" ", "\t")
                                              and lazy.lstrip(" \t").startswith("|")):
                if any(MAYBE_REFDEF_LINE_RE.match(line) for line in content):
                    unread[0] = True
                    return n - 1, "unread"
                content.append(_lazy_stand_in(lazy))
            else:
                content.append(lazy.lstrip(" \t"))
            last = k
            k += 1
        # Only a parse of footnote content reads the state of a definition
        # that ends without trailing blank lines.
        if state is None and (pending or inner):
            state = content_state()
        if pending:
            if state in ("raw_open", "unread"):
                last = pending[-1][0]
            else:
                state = "closed"
        return last, state

    def _content_end_state(content):
        inner_blocks = parse_blocks("\n".join(content), spec_blank_items, inner=True, _budget=budget)
        return _end_state(inner_blocks, len(content))

    def emit_table(i, quote, depth, base, attrs):
        """Emit the table whose header row is line ``i`` and whose delimiter
        row is the next line, and return the index after it. Body rows run
        until a blank line, the start of another block, or a line that
        leaves the table's quote or list item, with or without pipes."""
        rows = [i]
        j = i + 2
        while j < n and in_container(j, quote, depth, base):
            if _starts_block(_past_container(_strip_quote(lines[j], quote), base), False):
                break
            rows.append(j)
            j += 1
        has_html = any(HTML_TAG_RE.search(_strip_quote(lines[r], quote)) for r in rows)
        for idx, r in enumerate(rows):
            row_body = _strip_quote(lines[r], quote)
            cells = _split_cells(row_body)
            if has_html:
                blocks.append(Block("table_raw", attrs(), lines[r], [], r + 1))
            elif idx == 0:
                # markdown-it needs a pipe in the header row; cmark-gfm does
                # not ("Name" above ":---" is a table there only).
                blocks.append(Block("table_row", attrs(cols=len(cells), piped="|" in row_body),
                                    lines[r], cells, r + 1))
            else:
                blocks.append(Block("table_row", attrs(cols=len(cells)), lines[r], cells, r + 1))
            if idx == 0:
                sep = _strip_quote(lines[i + 1], quote)
                sep_norm = re.sub(r"[ \t]", "", sep).strip("|")
                blocks.append(Block("table_sep", attrs(), sep_norm, [], i + 2))
        return j

    # Paragraph lines that head a table and are read with the paragraph's
    # containers, by line index: (quote, depth, base, ancestry, mark), where
    # mark is "lazy", "indented" or "".
    table_headers = {}

    while i < n:
        line = lines[i]
        quote, body = _quote_depth(line)
        if not body.strip():
            if not line.strip():
                # A blank line closes every blockquote and the list items
                # inside them.
                del level_stacks[1:]
                del open_quotes[:]
            else:
                # A line with only quote markers stays inside its quotes
                # (and their list items) and may open new ones.
                ancestry = containers(quote, None, qcols_of(i, quote))[2]
                track_quotes(quote, ancestry, i + 1)
            i += 1
            continue
        start_line = i + 1

        def attrs(**extra):
            out = {"quote": quote, "container": ancestry}
            if any(ancestry):
                # Inside a list item, a blank line between two blocks makes
                # the list loose.
                out["gap"] = blank_line_before(i, quote)
            out.update(extra)
            return out

        forced = table_headers.pop(i, None)
        if forced is not None:
            # GFM takes a table's header row from the paragraph above the
            # delimiter row, also when that line was a lazy continuation
            # line or indented four columns: the table belongs to the
            # paragraph's containers. Other parsers (markdown-it) read
            # neither as a header row, so a header that becomes or stops
            # being lazy or indented is also a structure change.
            quote, depth, base, ancestry, mark = forced
            marks = {mark + "_header": True} if mark else {}
            i = emit_table(i, quote, depth, base, lambda **extra: attrs(**dict(marks, **extra)))
            continue
        ebody = _strip_quote(line, quote)
        indent = len(ebody) - len(ebody.lstrip(" "))
        # Column of each quote marker in the text of its level: a quote
        # marker that does not reach a list item's content column closes that
        # item, so a quote moved into or out of a list item changes the
        # container tuple at every level.
        qcols = qcols_of(i, quote)
        depth, base, ancestry = containers(quote, indent, qcols)
        cbody = ebody[base:] if indent >= base else ebody.lstrip(" ")
        if not (depth > 0 and _starts_quote(cbody)):
            # (A quote marker indented into a list item is moved below and
            # the line read again; its quotes are tracked then.)
            track_quotes(quote, ancestry, start_line)

        if indent - base < 4 and POLISH_OFF_LINE_RE.match(cbody):
            j = i + 1
            while j < n and not POLISH_ON_RE.search(lines[j]):
                j += 1
            if j >= n:
                blocks.append(Block("protected", attrs(base=base), "\n".join(lines[i:]), [], start_line))
                i = n
                continue
            on = POLISH_ON_RE.search(lines[j])
            rest = lines[j][on.end():]
            if not rest.strip():
                blocks.append(Block("protected", attrs(base=base), "\n".join(lines[i:j + 1]), [], start_line))
                i = j + 1
                continue
            # The region ends at the polish:on marker; the rest of that line is
            # read again as ordinary content, keeping its quote prefix and
            # indentation.
            blocks.append(Block("protected", attrs(base=base), "\n".join(lines[i:j] + [lines[j][:on.end()]]),
                                [], start_line))
            jq, after = _quote_depth(lines[j])
            prefix = lines[j][:len(lines[j]) - len(after)]
            lead = after[:len(after) - len(after.lstrip(" \t"))]
            lines[j] = prefix + lead + rest.lstrip(" \t")
            # The same cut on the original bytes: the rest of the line after
            # the marker is unchanged by tab expansion or moved markers.
            orig = orig_lines[j]
            head = _loose_quote_end(orig, jq)
            head += len(orig[head:]) - len(orig[head:].lstrip(" \t"))
            orig_lines[j] = orig[:head] + orig[len(orig) - len(rest):].lstrip(" \t")
            i = j
            continue

        if indent - base >= 4:
            # Indented code block: every following line that is blank or
            # indented four columns past the container belongs to it.
            j = i
            k = i + 1
            while k < n:
                kq, _ = _quote_depth(lines[k])
                if kq != quote:
                    break
                kb = _strip_quote(lines[k], quote).expandtabs(4)
                if not kb.strip():
                    k += 1
                    continue
                if len(kb) - len(kb.lstrip(" ")) - base >= 4:
                    j = k
                    k += 1
                    continue
                break
            blocks.append(Block("indented_code", attrs(base=base), "\n".join(lines[i:j + 1]), [], start_line))
            i = j + 1
            continue

        if depth > 0 and _starts_quote(cbody):
            # A blockquote inside a list item whose marker sits beyond the
            # reach of the quote prefix parser (four or more columns into the
            # line). Move each marker line of the quote left, keep the
            # marker's true column for the container check, and read the
            # lines again, so the quote is parsed like any other and stays
            # inside its list items. The loop stops at the first line that
            # is not such a marker line: whether that line continues the
            # quote lazily depends on the blocks inside the quote, and the
            # paragraph parser decides it (moving later markers itself).
            k = i
            while k < n and lines[k].strip() and _quote_depth(lines[k])[0] == quote:
                kb = _strip_quote(lines[k], quote)
                kind = _indent_of(kb)
                rel = _past_container(kb, base)
                if k > i and quote and _leaves_list_item(qcols_of(k, quote), quote, level_stacks):
                    break
                if kind >= base and _starts_quote(rel):
                    marker_quote_col.setdefault(k, {})[quote] = kind
                    lines[k] = ((_quote_prefix(lines[k], quote) + " ") if quote else "") \
                        + " " * min(kind, 3) + kb.lstrip(" ")
                else:
                    break
                k += 1
            continue

        fence = _is_fence_open(cbody)
        if fence:
            end, closed = fence_end(i + 1, quote, depth, base, fence)
            blocks.append(Block("fence", attrs(fence_closed=closed), "\n".join(lines[i:end + 1]), [],
                                start_line))
            i = end + 1
            continue

        if cbody.lstrip().startswith("$$"):
            j = i
            opener = cbody.strip()
            if not (len(opener) > 2 and opener.endswith("$$")):
                j = i + 1
                while j < n and "$$" not in lines[j]:
                    j += 1
            end = min(j, n - 1)
            blocks.append(Block("math", attrs(), "\n".join(lines[i:end + 1]), [], start_line))
            i = end + 1
            continue

        if _is_html_start(cbody):
            end = html_end(i, quote, depth, base, cbody)
            blocks.append(Block("html", attrs(base=base), "\n".join(lines[i:end + 1]), [], start_line))
            i = end + 1
            continue

        fm = FOOTNOTE_DEF_RE.match(cbody)
        if fm:
            end, end_state = footnote_end(i, quote, base, cbody[fm.end():].lstrip(" \t"))
            # The block remembers how its content ends, so a definition
            # inside another one can keep that one's paragraph open.
            blocks.append(Block("footnote_def", attrs(base=base), "\n".join(lines[i:end + 1]), [], start_line,
                                end_state))
            i = end + 1
            continue

        hm = ATX_RE.match(cbody)
        if hm:
            blocks.append(Block("heading", attrs(level=len(hm.group(1))), line,
                                [hm.group(2) or ""], start_line))
            i += 1
            continue

        if HR_RE.match(cbody):
            blocks.append(Block("hr", attrs(), cbody.strip(), [], start_line))
            i += 1
            continue

        # A list marker comes before a table: "- | A | B |" is a list item
        # that holds a table, not a table whose first cell starts with "-".
        lm = LIST_ITEM_RE.match(ebody)
        if lm:
            marker = lm.group("marker")
            col0 = indent + len(marker)
            after_marker = ebody[col0:]
            ws_raw = after_marker[:len(after_marker) - len(after_marker.lstrip(" \t"))]
            rest_raw = after_marker[len(ws_raw):]
            ws = len((" " * col0 + ws_raw).expandtabs(4)) - col0
            gap = 1 if (ws >= 5 or not rest_raw.strip()) else ws
            content_col = col0 + gap
            task = lm.group("task")
            # Whether a blank line comes before the item (it makes a list
            # loose). Recorded for every item, so adding or removing one is
            # visible however the previous block is nested.
            seen_content = any(b.kind != "quote" for b in blocks)
            blank_before = bool(seen_content and i > 0 and not _strip_quote(lines[i - 1], quote).strip())
            level_stacks[quote].append((indent, content_col))
            empty_item = False
            ws_open = False
            if not task and not rest_raw.strip():
                if i + 1 >= n:
                    empty_item = True
                else:
                    next_body = _strip_quote(lines[i + 1], quote)
                    if not next_body.strip():
                        # cmark-gfm keeps the empty item open while each
                        # blank line reaches its content column.
                        ws_open = True
                        j = i + 1
                        while j < n and not _strip_quote(lines[j], quote).strip():
                            if not (_quote_depth(lines[j])[0] == quote
                                    and _indent_of(_strip_quote(lines[j], quote)) >= content_col):
                                ws_open = False
                                break
                            j += 1
                        empty_item = spec_blank_items or not ws_open
            blocks.append(Block("list_item", {
                "quote": quote,
                "depth": depth,
                "container": ancestry,
                "ordered": marker[-1] in ".)",
                "marker": marker,
                "task": task.strip().lower() if task else "",
                "blank_before": blank_before,
                "ws_open": ws_open,
            }, line, [], start_line))
            if empty_item:
                # An item may start with at most one blank line: one that
                # starts empty and is followed by a blank line is empty, and
                # what follows is outside it. cmark-gfm keeps the item open
                # when every blank line after it holds whitespace up to the
                # item's content column.
                level_stacks[quote].pop()
            # Read the rest of the marker line again as the item's first
            # content line, at the item's content column.
            if task:
                new_body = " " * content_col + lm.group("rest")
            else:
                pad = col0 + ws
                if ws < 5 and rest_raw.startswith(">") and pad > 3:
                    # Keep a quote that opens on the marker line within reach
                    # of the quote prefix parser, and remember its column.
                    marker_quote_col.setdefault(i, {})[quote] = pad
                    pad = 3
                new_body = " " * pad + rest_raw
            lines[i] = ((_quote_prefix(line, quote) + " ") if quote else "") + new_body
            continue

        if (i + 1 < n and in_container(i + 1, quote, depth, base)
                and _is_table_start(cbody, _past_container(_strip_quote(lines[i + 1], quote), base))):
            i = emit_table(i, quote, depth, base, attrs)
            continue

        # Paragraph, possibly a setext heading. An underline only counts when
        # it sits in the same blockquote and the same list item as the
        # paragraph; a lazy "---" line outside them is a thematic break.
        # Unit lines keep their bytes after the leading indentation of the
        # first line, so whitespace inside a code span or math that spans
        # lines is compared exactly. Whitespace outside tokens is not compared.
        # Reference definitions are read from the start of the paragraph
        # once its lines are known, as CommonMark does: a line after a
        # definition continues the same paragraph (an indented line is text,
        # not code), and an underline below nothing but definitions is text.
        content = [cbody.lstrip(" \t")]
        j = i + 1
        setext_level = 0

        def sep_after(k):
            """Whether line ``k + 1`` is a delimiter row inside the
            paragraph's containers."""
            return (k + 1 < n and in_container(k + 1, quote, depth, base)
                    and _is_table_sep(_past_container(_strip_quote(lines[k + 1], quote), base)))

        # cmark-gfm tries a table once per delimiter row inside a
        # paragraph; after one whose header row does not match, no later
        # line of the paragraph starts a table.
        tables_off = sep_after(i)
        table_elsewhere = False
        while j < n:
            nxt = lines[j]
            if not nxt.strip():
                break
            nq = relocate_quotes(j, quote)
            nxt = lines[j]
            if nq > quote:
                break
            nbody = _strip_quote(nxt, nq)
            if not nbody.strip():
                break
            # A line with fewer quote markers is a lazy continuation line,
            # unless one of its markers leaves a list item (then the marker
            # opens a new quote).
            if nq > 0 and _leaves_list_item(qcols_of(j, nq), nq, level_stacks):
                break
            same_container = nq == quote and (depth == 0 or _indent_of(nbody) >= base)
            # A lazy line, or one that leaves some of the paragraph's list
            # items, is read past the items it does reach.
            nbc = past_matched(nbody, nq)
            if _starts_quote(nbc):
                # A quote marker indented into a list item starts a quote,
                # which interrupts the paragraph.
                break
            sm = SETEXT_RE.match(nbc)
            if sm and same_container:
                if _read_definitions(content, parsed_only=True)[1] < len(content):
                    setext_level = 1 if sm.group(1)[0] == "=" else 2
                    j += 1
                    break
            elif _starts_block(nbc, same_container):
                break
            sep_text = (_past_container(_strip_quote(lines[j + 1], quote), base)
                        if sep_after(j) else None)
            gfm_table = (sep_text is not None and not tables_off
                         and _is_table_start(nbc, sep_text, lazy=not same_container))
            if sep_text is not None and not gfm_table and _is_table_start(nbc, sep_text):
                # Other parsers (markdown-it) start a table here and
                # cmark-gfm does not (one try per paragraph, or the empty
                # first cell of a lazy header row): the paragraph is kept
                # byte for byte below. (cmark-gfm tried a table at the next
                # line, so no later line of the paragraph starts one.)
                table_elsewhere = True
                tables_off = True
                content.append(orig_lines[j][_loose_quote_end(orig_lines[j], nq):])
                j += 1
                continue
            if gfm_table:
                # A delimiter row that matches the paragraph's containers
                # turns this line into a table's header row. One that does
                # not is lazy paragraph text, and so is this line. The header
                # row is read as one with the paragraph's containers, also
                # when it is a lazy line, is indented four columns (no code
                # block can start inside a paragraph), or looks like a list
                # item that cannot interrupt the paragraph ("2. Header.").
                if not same_container:
                    mark = "lazy"
                elif _indent_of(nbc) >= 4:
                    mark = "indented"
                else:
                    mark = ""
                table_headers[j] = (quote, depth, base, ancestry, mark)
                break
            # The original bytes after the line's quote markers, also when a
            # marker was moved for parsing: a tab inside a code span or math
            # that spans lines is compared as written.
            content.append(orig_lines[j][_loose_quote_end(orig_lines[j], nq):])
            if sep_after(j):
                tables_off = True
            j += 1
        defs, rest = _read_definitions(content, parsed_only=bool(setext_level))
        # cmark-gfm does not read definitions in the lines above a table's
        # header row (they render as text), while markdown-it does: such a
        # definition only possibly defines its label, and is marked, so a
        # blank line added or removed before the header changes structure.
        above_table = j in table_headers
        for first, last, label, parsed in defs:
            ref = (normalize_label(label), parsed and not above_table) if label is not None else None
            marks = {"above_table": True} if above_table else {}
            blocks.append(Block("refdef", attrs(**marks), "\n".join(lines[i + first:i + last]), [],
                                i + first + 1, ref))
        if defs and rest == len(content) and depth > 0 and j < n and not _strip_quote(lines[j], quote).strip():
            # cmark-gfm drops a paragraph of definitions when the blank line
            # after it closes it. A list item that held nothing else is then
            # empty again, and stays open only while each further blank line
            # reaches its content column.
            empty = False
            for b in reversed(blocks):
                if b.kind == "list_item" and b.attrs.get("quote") == quote and b.attrs.get("depth") == depth - 1:
                    empty = True
                    break
                if b.kind != "refdef":
                    break
            m = j + 1
            while empty and m < n and not _strip_quote(lines[m], quote).strip():
                if not (_quote_depth(lines[m])[0] == quote
                        and _indent_of(_strip_quote(lines[m], quote)) >= base):
                    level_stacks[quote].pop()
                    break
                m += 1
        if rest < len(content) and table_elsewhere:
            blocks.append(Block("table_raw", attrs(table_elsewhere=True), "\n".join(lines[i + rest:j]),
                                [], i + rest + 1))
        elif rest < len(content):
            units = ["\n".join([content[rest].lstrip(" \t")] + content[rest + 1:])]
            if setext_level:
                blocks.append(Block("heading", attrs(level=setext_level),
                                    "\n".join(lines[i + rest:j]), units, i + rest + 1))
            else:
                blocks.append(Block("paragraph", attrs(), "\n".join(lines[i + rest:j]), units,
                                    i + rest + 1))
        i = j

    # Raw blocks are compared byte for byte against the original lines; a
    # line cut after a polish:on marker keeps its cut text.
    for block in blocks:
        if block.kind in RAW_LINE_KINDS:
            first = block.line - 1
            last = first + block.raw.count("\n")
            block.raw = "\n".join(orig_lines[first:last + 1])
    return blocks


def normalize_label(label):
    """A link label as CommonMark matches it: case-folded, with runs of
    whitespace collapsed and the ends trimmed."""
    return " ".join(label.split()).casefold()


def reference_labels(blocks):
    """The link reference labels a document defines, as (definite, possible):
    labels of definitions the parser read, and labels that may be defined
    (in a polish:off region, a footnote, or a definition the parser could
    not read in full)."""
    definite, possible = set(), set()
    for block in blocks:
        if block.kind == "refdef" and block.ref:
            (definite if block.ref[1] else possible).add(block.ref[0])
        elif block.kind in ("protected", "footnote_def"):
            for m in LOOSE_REFDEF_RE.finditer(block.raw):
                possible.add(normalize_label(m.group(1)))
    return definite, possible - definite


def prose_block_count(text):
    return len([b for b in parse_blocks(text)
                if b.kind not in RAW_KINDS and any(u.strip() for u in b.units)])


def _mask_code(text, segments=False):
    """``text`` with code blanked out (same length), so markers in code are text.

    Fenced and indented code blocks come from the block parser, so fences
    behind several list markers count too. Code spans are matched only inside
    one block (or one segment line), because a code span cannot cross a block
    boundary; a stray backtick elsewhere cannot hide a real marker.
    """
    lines = text.split("\n")
    masked = list(lines)
    if segments:
        chunks = [(k, k) for k in range(len(lines))]
    else:
        chunks = []
        for block in parse_blocks(text):
            if block.kind == "quote":
                continue
            first = block.line - 1
            last = min(first + block.raw.count("\n"), len(lines) - 1)
            if block.kind in ("fence", "indented_code"):
                for k in range(first, last + 1):
                    masked[k] = " " * len(lines[k])
            elif block.kind not in RAW_KINDS:
                chunks.append((first, last))
    for first, last in chunks:
        chunk = "\n".join(masked[first:last + 1])
        chars = list(chunk)
        for kind, start, end, _ in _scan_inline(chunk):
            if kind == "code":
                _mask(chars, start, end)
        masked[first:last + 1] = "".join(chars).split("\n")
    return "\n".join(masked)


def protected_slices(text, segments=False):
    """Exact source slices covered by polish:off regions, in order.

    A region runs from a polish:off marker to the next polish:on marker, or to
    the end of the text when it is never closed. Markers inside code are text.
    """
    masked = _mask_code(text, segments)
    slices = []
    pos = 0
    while True:
        m = POLISH_OFF_RE.search(masked, pos)
        if not m:
            break
        e = POLISH_ON_RE.search(masked, m.end())
        end = e.end() if e else len(text)
        slices.append(text[m.start():end])
        pos = end
    return slices


def check_regions(source, candidate, segments=False):
    """Reject any change to text inside polish:off regions, including whitespace."""
    src = protected_slices(source, segments)
    cand = protected_slices(candidate, segments)
    if src != cand:
        if len(src) != len(cand):
            detail = "the number of polish:off regions changed from %d to %d" % (len(src), len(cand))
        else:
            idx = next(k for k in range(len(src)) if src[k] != cand[k])
            detail = "polish:off region %d changed" % (idx + 1)
        raise GuardReject("region_changed", detail)


def check_document(source, candidate, block_ratio=BLOCK_RATIO_BOUNDS, doc_ratio=DOC_RATIO_BOUNDS):
    """Verify a Markdown or text candidate against its source. Raises GuardReject."""
    if candidate.count("\r") != source.count("\r"):
        raise GuardReject("structure", "carriage-return line endings changed")
    check_regions(source, candidate)
    src_blocks = parse_blocks(source)
    cand_blocks = parse_blocks(candidate)
    total_src, total_cand = _compare_blocks(src_blocks, cand_blocks, block_ratio)
    if any(b.kind == "list_item" and b.attrs.get("ws_open") for b in src_blocks + cand_blocks):
        # cmark-gfm and the CommonMark text read the lines after such an
        # item differently: the candidate must be safe under both.
        _compare_blocks(parse_blocks(source, spec_blank_items=True),
                        parse_blocks(candidate, spec_blank_items=True), block_ratio)
    check_ratio(total_src, total_cand, doc_ratio, "document")


def _compare_blocks(src_blocks, cand_blocks, block_ratio):
    """Compare two block lists; return the prose lengths (source, candidate).
    Raises GuardReject."""
    if len(src_blocks) != len(cand_blocks):
        detail = "source has %d blocks, candidate has %d" % (len(src_blocks), len(cand_blocks))
        for a, b in zip(src_blocks, cand_blocks):
            if a.kind != b.kind or a.attrs != b.attrs:
                detail += "; first difference at source line %d (%s vs %s)" % (a.line, a.kind, b.kind)
                break
        raise GuardReject("structure", detail)
    # Reference definitions are raw blocks, so the source's labels hold for
    # the candidate too (a changed definition is rejected below).
    refs = reference_labels(src_blocks)
    total_src = 0
    total_cand = 0
    for a, b in zip(src_blocks, cand_blocks):
        where = a.describe()
        if a.kind != b.kind:
            raise GuardReject("structure", "%s: candidate has %s" % (where, b.kind))
        if a.attrs != b.attrs:
            raise GuardReject("structure", "%s: attributes changed from %r to %r" % (where, a.attrs, b.attrs))
        if a.kind in RAW_KINDS:
            if a.raw != b.raw:
                raise GuardReject("region_changed", "%s: protected region changed" % where)
            continue
        if len(a.units) != len(b.units):
            raise GuardReject("structure", "%s: cell count changed" % where)
        for k, (su, cu) in enumerate(zip(a.units, b.units)):
            unit_where = where if len(a.units) == 1 else "%s cell %d" % (where, k + 1)
            s_len, c_len = compare_prose(su, cu, unit_where, block_ratio, refs=refs)
            total_src += s_len
            total_cand += c_len
    return total_src, total_cand


# ----------------------------------------------------------------------------
# Segments
# ----------------------------------------------------------------------------

SEGMENT_RE = re.compile(r"^\[\[([A-Za-z0-9_.:-]{1,64})\]\](?: (.*))?$")


def parse_segments(text):
    """Parse "[[ID]] text" lines. Raises ValueError on malformed input."""
    segments = []
    seen = set()
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        m = SEGMENT_RE.match(raw.rstrip("\r"))
        if not m:
            raise ValueError("line is not a [[ID]] segment: %r" % raw[:60])
        seg_id = m.group(1)
        if seg_id in seen:
            raise ValueError("duplicate segment ID %s" % seg_id)
        seen.add(seg_id)
        segments.append((seg_id, m.group(2) or ""))
    if not segments:
        raise ValueError("no segments")
    return segments


def format_segments(segments):
    return "\n".join("[[%s]] %s" % (seg_id, text) for seg_id, text in segments)


def check_segments(source_text, candidate_text, html_mode=False,
                   block_ratio=BLOCK_RATIO_BOUNDS, doc_ratio=DOC_RATIO_BOUNDS):
    """Verify a segments candidate. Returns the candidate segments list."""
    src = parse_segments(source_text)
    try:
        cand = parse_segments(candidate_text)
    except ValueError as exc:
        raise GuardReject("segment_mismatch", str(exc))
    check_regions(source_text, candidate_text, segments=True)
    src_ids = [s[0] for s in src]
    cand_ids = [c[0] for c in cand]
    if src_ids != cand_ids:
        missing = [x for x in src_ids if x not in cand_ids]
        extra = [x for x in cand_ids if x not in src_ids]
        if missing or extra:
            detail = "missing IDs %s, extra IDs %s" % (",".join(missing) or "none", ",".join(extra) or "none")
        else:
            detail = "segment IDs are out of order"
        raise GuardReject("segment_mismatch", detail)
    total_src = 0
    total_cand = 0
    for (seg_id, s_text), (_, c_text) in zip(src, cand):
        if not c_text.strip() and s_text.strip():
            raise GuardReject("segment_mismatch", "segment %s is empty in the candidate" % seg_id)
        s_len, c_len = compare_prose(s_text, c_text, "segment %s" % seg_id, block_ratio,
                                     markup_chars=html_mode)
        total_src += s_len
        total_cand += c_len
    check_ratio(total_src, total_cand, doc_ratio, "document")
    return cand


# ----------------------------------------------------------------------------
# HTML adapter
# ----------------------------------------------------------------------------

EXCLUDED_ELEMENTS = frozenset(
    ["script", "style", "template", "code", "pre", "kbd", "samp", "noscript",
     "textarea", "svg", "math", "xmp", "listing", "plaintext", "iframe", "noembed",
     "noframes"])
# Inside these, a self-closing tag is legitimate (foreign content).
FOREIGN_ELEMENTS = frozenset(["svg", "math"])
ELIGIBLE_ATTRS = ("alt", "title", "aria-label", "placeholder")
VOID_ELEMENTS = frozenset(
    ["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
     "param", "source", "track", "wbr"])
TEMPLATE_MARKERS = ("{{", "}}", "{%", "%}", "${", "<%", "%>")
ATTR_RE = re.compile(
    r"""([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?""")
ELIGIBLE_MARK = "\x00eligible\x00"
# Text that still looks like markup means the parser fell back to treating
# markup as data (for example a tag truncated at the end of the file).
UNMAPPED_MARKUP_RE = re.compile(r"<[A-Za-z/!?]")
# HTML whitespace (not NBSP or other Unicode spaces).
HTML_WS = " \t\n\r\f"
WHITESPACE_STYLE_RE = re.compile(r"white-space\s*:\s*(?:pre|break-spaces)", re.I)
AMP_REF_RE = re.compile(r"&(#[0-9]+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*)(;?)")
LEGACY_ENTITY_NAMES = frozenset(k for k in html.entities.html5 if not k.endswith(";"))


def _has_semicolonless_ref(text):
    """True when ``text`` has a character reference a browser decodes without ";"."""
    for m in AMP_REF_RE.finditer(text):
        if m.group(2):
            continue
        name = m.group(1)
        if name.startswith("#"):
            return True
        for k in range(len(name), 1, -1):
            if name[:k] in LEGACY_ENTITY_NAMES:
                return True
    return False


class _EventCollector(html.parser.HTMLParser):
    def __init__(self, source):
        html.parser.HTMLParser.__init__(self, convert_charrefs=False)
        self.source = source
        self.line_starts = [0]
        for m in re.finditer("\n", source):
            self.line_starts.append(m.end())
        self.events = []

    def _offset(self):
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        self.events.append(("start", self._offset(), tag, self.get_starttag_text(), attrs))

    def handle_startendtag(self, tag, attrs):
        self.events.append(("startend", self._offset(), tag, self.get_starttag_text(), attrs))

    def handle_endtag(self, tag):
        self.events.append(("end", self._offset(), tag, None, None))

    def handle_data(self, data):
        self.events.append(("data", self._offset(), None, data, None))

    def handle_entityref(self, name):
        self.events.append(("ref", self._offset(), None, name, None))

    def handle_charref(self, name):
        self.events.append(("ref", self._offset(), None, name, None))

    def handle_comment(self, data):
        self.events.append(("comment", self._offset(), None, data, None))

    def handle_decl(self, decl):
        self.events.append(("decl", self._offset(), None, decl, None))

    def handle_pi(self, data):
        self.events.append(("pi", self._offset(), None, data, None))

    def unknown_decl(self, data):
        self.events.append(("udecl", self._offset(), None, data, None))


class HtmlSpan(object):
    __slots__ = ("start", "end", "kind", "lead", "core", "trail", "quote")

    def __init__(self, start, end, kind, lead, core, trail, quote=""):
        self.start = start
        self.end = end
        self.kind = kind
        self.lead = lead
        self.core = core
        self.trail = trail
        self.quote = quote


def _find_end(source, needle, start):
    pos = source.find(needle, start)
    return -1 if pos < 0 else pos + len(needle)


def _event_end(source, kind, off, payload):
    """Return the source offset just after one parser event."""
    if kind == "data":
        return off + len(payload)
    if kind in ("start", "startend"):
        return off + len(payload or "")
    if kind == "ref":
        base = off + (2 if source.startswith("&#", off) else 1) + len(payload)
        return base + 1 if source[base:base + 1] == ";" else base
    if kind == "comment" and source.startswith("<!--", off):
        for closer in ("-->", "--!>"):
            end = _find_end(source, closer, off + 4)
            if end >= 0:
                return end
        return len(source)
    if kind == "udecl" and source.startswith("<![", off):
        end = _find_end(source, "]]>", off)
        return end if end >= 0 else len(source)
    end = _find_end(source, ">", off)
    return end if end >= 0 else len(source)


def _has_template_syntax(text):
    return any(marker in text for marker in TEMPLATE_MARKERS)


def collapse_ws(text):
    """Collapse HTML whitespace runs; NBSP and other Unicode spaces are kept."""
    return re.sub(r"[ \t\n\r\f]+", " ", text).strip(HTML_WS)


def _analyze_html(source):
    """Return (spans, skeleton) for an HTML document.

    ``spans`` lists eligible text and attribute values with source offsets.
    ``skeleton`` lists every non-eligible construct exactly, plus a marker for
    each eligible span, so two documents can be compared for everything except
    eligible text.
    """
    parser = _EventCollector(source)
    try:
        parser.feed(source)
        parser.close()
    except Exception as exc:  # html.parser is lenient; treat any failure as unsupported
        raise UnsupportedInput("unsupported_html", "parser error: %s" % exc)

    events = parser.events
    cursor = 0
    for kind, off, tag, payload, _ in events:
        if kind == "data" and source[off:off + len(payload)] != payload:
            raise UnsupportedInput("unsupported_html", "text offsets do not map to the source")
        if kind in ("start", "startend") and payload and source[off:off + len(payload)] != payload:
            raise UnsupportedInput("unsupported_html", "tag offsets do not map to the source")
        if off != cursor:
            raise UnsupportedInput("unsupported_html",
                                   "the parser skipped bytes near offset %d" % cursor)
        cursor = _event_end(source, kind, off, payload)
    if source[cursor:]:
        raise UnsupportedInput("unsupported_html",
                               "the parser did not consume the input after offset %d" % cursor)

    has_body = re.search(r"<body[\s>/]", source, re.I) is not None
    spans = []
    skeleton = []
    excluded = []
    # "protected" is set between <!-- polish:off --> and <!-- polish:on -->.
    state = {"body": False, "head": False, "title": 0, "protected": False}

    def eligible_context():
        if excluded or state["protected"]:
            return False
        if state["title"]:
            return True
        if has_body:
            return state["body"]
        return not state["head"]

    def flush_run(run_start, run_end):
        raw = source[run_start:run_end]
        if not excluded:
            stray = UNMAPPED_MARKUP_RE.search(raw)
            if stray:
                raise UnsupportedInput(
                    "unsupported_html",
                    "markup the parser could not map near offset %d" % (run_start + stray.start()))
        core = raw.strip(HTML_WS)
        if eligible_context() and core and not _has_template_syntax(core):
            if _has_semicolonless_ref(core):
                raise UnsupportedInput(
                    "unsupported_html",
                    "character reference without a semicolon near offset %d" % run_start)
            lead = raw[:len(raw) - len(raw.lstrip(HTML_WS))]
            trail = raw[len(raw.rstrip(HTML_WS)):]
            spans.append(HtmlSpan(run_start, run_end, "text", lead, core, trail))
            skeleton.append(("text", ELIGIBLE_MARK))
        else:
            skeleton.append(("text", raw))

    run_start = None
    for idx, (kind, off, tag, payload, parsed_attrs) in enumerate(events):
        if kind in ("data", "ref"):
            if run_start is None:
                run_start = off
            continue
        if run_start is not None:
            flush_run(run_start, off)
            run_start = None
        if kind in ("start", "startend"):
            lowered = tag.lower()
            in_foreign = any(x in FOREIGN_ELEMENTS for x in excluded)
            if kind == "startend" and lowered not in VOID_ELEMENTS and not in_foreign:
                # Browsers ignore the slash, so "<script/>" still opens a script.
                raise UnsupportedInput(
                    "unsupported_html",
                    "self-closing <%s/> on a non-void element near offset %d" % (lowered, off))
            attr_sig = []
            regex_attrs = []
            # Attribute eligibility does not depend on where text nodes are
            # eligible: the eligible attributes count on any element that is
            # not excluded or inside an excluded element or a polish:off
            # region, including <html>, <body> and elements in <head>.
            # Unquoted values count too.
            tag_eligible = (not excluded and not state["protected"]
                            and lowered not in EXCLUDED_ELEMENTS
                            and not state["title"])
            raw_tag = payload or ""
            name_match = re.match(r"<[^\s/>]+", raw_tag)
            pos = name_match.end() if name_match else 0
            for am in ATTR_RE.finditer(raw_tag, pos):
                name = am.group(1).lower()
                if name in ("/",):
                    continue
                if am.group(2) is not None:
                    value, vstart, quote = am.group(2), am.start(2), '"'
                elif am.group(3) is not None:
                    value, vstart, quote = am.group(3), am.start(3), "'"
                else:
                    value, vstart, quote = am.group(4), am.start(4), ""
                regex_attrs.append((name, None if value is None else html.unescape(value)))
                if (tag_eligible and name in ELIGIBLE_ATTRS and value is not None
                        and value.strip(HTML_WS) and not _has_template_syntax(value)):
                    core = value.strip(HTML_WS)
                    if _has_semicolonless_ref(core):
                        raise UnsupportedInput(
                            "unsupported_html",
                            "character reference without a semicolon near offset %d" % off)
                    lead = value[:len(value) - len(value.lstrip(HTML_WS))]
                    trail = value[len(value.rstrip(HTML_WS)):]
                    start = off + vstart
                    spans.append(HtmlSpan(start, start + len(value), "attr", lead, core, trail, quote))
                    attr_sig.append((name, ELIGIBLE_MARK))
                else:
                    attr_sig.append((name, value))
            if regex_attrs != [(k.lower(), v) for k, v in (parsed_attrs or [])]:
                raise UnsupportedInput(
                    "unsupported_html",
                    "ambiguous attribute syntax in <%s> near offset %d" % (lowered, off))
            skeleton.append((kind, lowered, tuple(attr_sig)))
            if kind == "start":
                preserves_ws = any(k.lower() == "style" and v and WHITESPACE_STYLE_RE.search(v)
                                   for k, v in (parsed_attrs or []))
                if (lowered in EXCLUDED_ELEMENTS or preserves_ws
                        or (excluded and lowered not in VOID_ELEMENTS)):
                    # Track nesting inside excluded regions so the region ends
                    # at its own closing tag.
                    excluded.append(lowered)
                elif lowered == "body":
                    state["body"] = True
                elif lowered == "head":
                    state["head"] = True
                elif lowered == "title":
                    state["title"] += 1
        elif kind == "end":
            lowered = tag.lower()
            skeleton.append(("end", lowered))
            if lowered in excluded:
                while excluded:
                    if excluded.pop() == lowered:
                        break
            elif lowered == "body":
                state["body"] = False
            elif lowered == "head":
                state["head"] = False
            elif lowered == "title" and state["title"]:
                state["title"] -= 1
        else:
            skeleton.append((kind, payload))
            if kind == "comment" and not excluded:
                if re.fullmatch(r"\s*polish:off\s*", payload or ""):
                    state["protected"] = True
                elif re.fullmatch(r"\s*polish:on\s*", payload or ""):
                    state["protected"] = False
    if run_start is not None:
        flush_run(run_start, len(source))
    return spans, skeleton


def html_extract(source):
    """Return (spans, segments_text) or raise UnsupportedInput."""
    spans, _ = _analyze_html(source)
    segments = [("s%d" % (k + 1), collapse_ws(span.core)) for k, span in enumerate(spans)]
    return spans, (format_segments(segments) if segments else "")


# Characters that would end or split an unquoted attribute value.
UNQUOTED_ESCAPES = {'"': "&quot;", "'": "&#39;", "=": "&#61;", "`": "&#96;",
                    " ": "&#32;", "\t": "&#9;", "\n": "&#10;", "\f": "&#12;", "\r": "&#13;"}


def _escape_text(text, quote="", unquoted=False):
    out = re.sub(r"&(?!(?:[A-Za-z][A-Za-z0-9]{1,31}|#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6});)", "&amp;", text)
    out = out.replace("<", "&lt;").replace(">", "&gt;")
    if quote == '"':
        out = out.replace('"', "&quot;")
    elif quote == "'":
        out = out.replace("'", "&#39;")
    elif unquoted:
        out = "".join(UNQUOTED_ESCAPES.get(ch, ch) for ch in out)
        if out.endswith("/"):
            # "value/>" would read as a self-closing slash.
            out = out[:-1] + "&#47;"
    return out


def html_splice(source, spans, polished):
    """Return the source with each span's text replaced by its polished text.

    ``polished`` is a list of strings in span order. A span whose polished text
    equals its collapsed source text keeps its original bytes.
    """
    if len(polished) != len(spans):
        raise GuardReject("segment_mismatch", "segment count does not match the page")
    pieces = []
    cursor = 0
    for span, new_text in zip(spans, polished):
        pieces.append(source[cursor:span.start])
        if new_text == collapse_ws(span.core):
            pieces.append(source[span.start:span.end])
        else:
            unquoted = span.kind == "attr" and not span.quote
            pieces.append(span.lead + _escape_text(new_text, span.quote, unquoted) + span.trail)
        cursor = span.end
    pieces.append(source[cursor:])
    return "".join(pieces)


def html_verify(original, modified):
    """Raise GuardReject unless ``modified`` differs from ``original`` only in eligible text."""
    try:
        o_spans, o_skel = _analyze_html(original)
        m_spans, m_skel = _analyze_html(modified)
    except UnsupportedInput as exc:
        raise GuardReject("html_mismatch", exc.detail)
    if len(o_spans) != len(m_spans):
        raise GuardReject("html_mismatch", "eligible span count changed from %d to %d"
                          % (len(o_spans), len(m_spans)))
    if o_skel != m_skel:
        for idx, (a, b) in enumerate(zip(o_skel, m_skel)):
            if a != b:
                raise GuardReject("html_mismatch", "page structure differs at item %d" % (idx + 1))
        raise GuardReject("html_mismatch", "page structure length changed")
    # Bytes outside the eligible spans must be identical.
    cursor_o = 0
    cursor_m = 0
    for so, sm in zip(o_spans, m_spans):
        if so.kind != sm.kind or so.lead != sm.lead or so.trail != sm.trail:
            raise GuardReject("html_mismatch", "whitespace around eligible text changed")
        if original[cursor_o:so.start] != modified[cursor_m:sm.start]:
            raise GuardReject("html_mismatch", "bytes outside eligible text changed")
        cursor_o = so.end
        cursor_m = sm.end
    if original[cursor_o:] != modified[cursor_m:]:
        raise GuardReject("html_mismatch", "bytes outside eligible text changed")
