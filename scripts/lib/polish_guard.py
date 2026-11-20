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

import bisect
import html
import html.entities
import html.parser
import hashlib
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
FENCE_LINE_RE = re.compile(r"^(?:[ \t]*>)*[ \t]*(?:(?:[-+*]|[0-9]{1,9}[.)])[ \t]+)?(`{3,}|~{3,})(.*)$")
POLISH_OFF_RE = re.compile(r"<!--\s*polish:off\s*-->")
# Either marker, split so it can be renamed to an ordinary comment of the
# same length ("polish-on"), which is how the renderers read it.
POLISH_MARKER_RE = re.compile(r"(<!--\s*polish):(o(?:n|ff)\s*-->)")
# How many lines _md_starts_anew looks back for the quote depth of a
# paragraph markdown-it may have open (past that, it may be open).
MD_ANEW_LOOKBACK = 256
# A line that starts with a list marker (past its indentation).
LIST_MARKER_START_RE = re.compile(r"[ \t]*(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)")
# A line markdown-it may read as a setext heading underline.
SETEXT_LIKE_RE = re.compile(r"[ \t]{0,3}(?:=+|-+)[ \t]*$")
# How many groups of bracket pairs that may be references (by label)
# _emphasis_spans reads each way in every combination.
MAYBE_LABEL_GROUPS = 3
# ASCII punctuation that a backslash escapes in CommonMark.
ESCAPABLE = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
AUTOLINK_RE = re.compile(
    r"<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*|[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+)>")
# Inline links and images are found by _scan_links, which balances brackets
# and parentheses to any depth up to this limit.
LINK_NESTING_LIMIT = 32
REF_LINK_RE = re.compile(r"(!?)\[((?:\\.|[^\[\]\\])*)\]\[((?:\\.|[^\[\]\\])*)\]")
FOOTNOTE_REF_RE = re.compile(r"\[\^[^\]\s]+\]")
# Any other bracketed text may be a shortcut reference link whose label is
# its text, so it is protected as a whole (also before a "(" that starts no
# inline link, or before a "[" that opens no label: inline links and full
# references are masked before this pattern runs).
SHORTCUT_REF_RE = re.compile(r"!?\[(?:\\.|[^\[\]\\])+\](?!\[(?:\\.|[^\[\]\\])*\])")
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
_ELEMENT_TAG_RE = re.compile(HTML_OPEN_TAG + "|" + HTML_CLOSE_TAG, re.S)
# A malformed tag the strict grammar refuses (written so that a long run
# of whitespace inside it is matched one way only, in linear time).
_LOOSE_TAG = r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>"
HTML_TAG_RE = re.compile(
    HTML_OTHER_RAW + "|" + HTML_OPEN_TAG + "|" + HTML_CLOSE_TAG + "|" + _LOOSE_TAG, re.S)
_LOOSE_TAG_RE = re.compile(_LOOSE_TAG, re.S)
ENTITY_RE = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]{1,31}|#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6});")
URL_RE = re.compile(r"\b(?:https?|ftp|file)://[^\s<>\"'`]+|\bwww\.[^\s<>\"'`]+")

WORD_TOKEN_RE = re.compile(
    r"""
      (?P<path>(?<![\w./~-])(?:(?:~[\w.-]*|\.{1,2})?/[\w@+.-]+(?:/[\w@+.-]*)*
                                |[\w@+.-]+(?:/[\w@+.-]*)+))
    | (?P<call>[A-Za-z_][\w.]*\(\)(?:\(\)|(?:\.|::)\w+)*)
    | (?P<scope>[A-Za-z_][\w.]*(?:::[\w.]+)+(?:\(\)(?:\(\)|(?:\.|::)\w+)*)?)
    | (?P<flag>(?<![\w-])--[A-Za-z0-9][\w-]*)
    | (?P<var>(?<![\w$])\$\{?[A-Za-z_]\w*\}?(?:\w+(?=\(\)))?(?:\(\)|(?:\.|::)\w+)*)
    | (?P<ident>(?<!\w)(?=\w*_)(?=\w*[A-Za-z0-9])\w+)
    | (?P<qty>(?<![\w.])\d+(?:\.\d+)?
        [ \t\u00a0\u2007\u2009\u200a\u202f]*(?:\n[ \t\u00a0\u2007\u2009\u200a\u202f]*)?(?:ns|us|ms|secs?|seconds?|mins?|minutes?|hrs?|hours?|days?|weeks?
               |months?|years?|[KMGTP]i?B|kB|bytes?|bits?|[KMG]bps|px|rem|em|pt|[kMG]?Hz
               |s|h|d|B|k|K|M|G|x|%)
        (?![\w%]))
    | (?P<dotted>[\w-]+(?:\.[\w-]+)+)
    | (?P<camel>(?![A-Z]+s\b)[A-Za-z0-9]*(?:[a-z][A-Z]|[A-Z]{2}[a-z])[A-Za-z0-9]*)
    | (?P<digit>[\w.:+/-]*\d[\w.:+/-]*)
    """,
    re.X | re.A,
)

# A run of ASCII letters, digits and path punctuation long enough to be a
# hash, encoded data or a long identifier rather than prose, with the token
# syntax next to it (a "$" or "${" before it, "()" or "}" after it, or a unit
# after a number). It is one protected word: the word patterns would
# otherwise retry every alternative at each position of the run, which takes
# time quadratic in its length.
LONG_RUN_RE = re.compile(
    r"(?:\$\{?)?[\w@+.:/~-]{80,}(?:\}?\(\)(?:\(\)|(?:\.|::)\w+)*|\}(?:\(\)|(?:\.|::)\w+)*"
    r"|(?<=\d)[ \t\u00a0\u2007\u2009\u200a\u202f]*"
    r"(?:\n[ \t\u00a0\u2007\u2009\u200a\u202f]*)?"
    r"(?:ns|us|ms|secs?|seconds?|mins?|minutes?|hrs?|hours?|days?|weeks?|months?|years?"
    r"|[KMGTP]i?B|kB|bytes?|bits?|[KMG]bps|px|rem|em|pt|[kMG]?Hz|s|h|d|B|k|K|M|G|x|%)(?![\w%]))?",
    re.A)

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
        m = AUTOLINK_RE.match(text, i)
        if m:
            return m.end()
        return _html_end(text, i)
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
            # cmark-gfm takes a destination that leaves parentheses open
            # when whitespace ends it ("[w](a(b )" links to "a(b");
            # markdown-it does not: the unit is kept byte for byte.
            return (None, True) if i < n else (None, False)
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
                status = resolve(label, _label_ok(label))
                if status not in ("yes", "no") and second + 1 < n and text[second + 1] == "(":
                    # "[text][label](dest)": a reference to one renderer or
                    # reading, text and an inline link to the other. The
                    # whole unit is kept byte for byte.
                    unmodeled = True
                    break
                if (status == "yes"
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


REF_LABEL_LIMIT = 1000


def _ref_label_close(text, open_bracket):
    """Index of the "]" ending the link label (no unescaped brackets) that
    opens at ``open_bracket``, or None. The label may be of any length, as
    markdown-it has no limit; the caller checks cmark-gfm's limit in bytes
    and its whitespace with ``_label_ok`` on the original text."""
    i = open_bracket + 1
    while i < len(text):
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


def _indented_quote_marker(line):
    """Whether a quote marker in the run of markers that starts ``line`` has
    four or more columns of spaces or tabs before it: markdown-it may read it
    as a marker where cmark-gfm reads text or code (a marker with less before
    it is a marker to both)."""
    run = re.match(r"(?:[ \t]*>)+", line)
    return bool(run) and any(len(gap.expandtabs(4)) >= 4 for gap in re.findall(r"([ \t]*)>", run.group(0)))


def _quoted_line(line):
    """Whether ``line`` starts with a quote marker, also behind list
    markers."""
    rest = re.sub(r"^[ \t]*(?:(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]+|$))+", "", line)
    return rest.lstrip(" \t").startswith(">")


def _unpaired_bracket(masked):
    """True when ``masked`` holds a square bracket with no partner outside
    code spans, autolinks and raw HTML (backslash escapes skipped)."""
    depth = 0
    i = 0
    n = len(masked)
    while i < n:
        ch = masked[i]
        if ch == "\\":
            i += 2
            continue
        if ch in "`<":
            opaque = _opaque_end(masked, i)
            if opaque is not None:
                i = opaque
                continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            if depth == 0:
                return True
            depth -= 1
        i += 1
    return depth != 0


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
        cm_valid = True
        second = _ref_label_close(masked, end) if end < n and masked[end] == "[" else None
        if second is None and end < n and masked[end] != "[" and original[end] == "[":
            # (The text of an inline link right after it, masked above, is
            # still a label after it: "[text]" is then no shortcut.)
            second = _ref_label_close(original, end)
        md_full = False
        if second is None and end < n and masked[end] == "[":
            # The next brackets hold brackets: no label for cmark-gfm, so
            # "[text]" is a shortcut there, while markdown-it balances them
            # into a label that no definition can have, so "[text]" is no
            # link there. (Brackets that do not close within the window
            # count as such a label too.)
            window = masked[end:end + 4000]
            close_at = _label_end(window, 0)
            md_full = close_at >= 0 or len(window) == 4000
        if second is not None:
            # "[text][label]" (full) or "[text][]" (collapsed). A label of
            # only whitespace is not a label for cmark-gfm, and the text is
            # no link there; markdown-it may still read the label (it has no
            # length limit, and other whitespace is whitespace to it).
            inner = original[end + 1:second]
            if inner:
                label, cm_valid = inner, _label_ok(inner)
            end = second + 1
        status = resolve(label, cm_valid and _label_ok(label)) if label is not None else "no"
        if md_full:
            status = {"yes": "cm", "cm": "cm", "md": "no", "maybe": "maybe", "no": "no"}[status]
        if status == "no":
            i += 1
            continue
        kind = "image" if i > 0 and masked[i - 1] == "!" else "link"
        out.append((offset + i + 1, offset + close, kind, status, normalize_label(label)))
        out.extend(_scan_refs(masked[i + 1:close], original[i + 1:close], resolve,
                              offset + i + 1))
        if second is not None and text_label is None and end - close > 3:
            # When the link text holds a link, the text is no link, and its
            # label "[label]" is a shortcut reference of its own; otherwise
            # the label is not parsed. Either way its markers pair only with
            # each other.
            short = original[close + 2:second]
            short_status = resolve(short, _label_ok(short))
            if short_status != "no":
                out.append((offset + close + 2, offset + second, "link", short_status,
                            normalize_label(short)))
        i = end
    return out


_HTML_TERMS = {}


def _html_terms(text):
    """Where the last terminator of each kind of raw HTML starts in
    ``text`` (-1 when there is none). Cached by the text object itself (an
    equal text compared by value would cost its length on every call)."""
    hit = _HTML_TERMS.get(id(text))
    if hit is not None and hit[0] is text:
        return hit[1]
    if len(_HTML_TERMS) >= 16:
        _HTML_TERMS.clear()
    terms = {term: text.rfind(term) for term in ("-->", "?>", "]]>", ">")}
    _HTML_TERMS[id(text)] = (text, terms)
    return terms


def _html_end(text, i):
    """End of the raw inline HTML that starts at ``text[i]`` (a "<"), by the
    grammar of HTML_STRICT_TAG_RE, or None. An opener that no terminator
    follows fails at once, so many of them do not each scan to the end of
    the text (as the lazy patterns of HTML_STRICT_TAG_RE do)."""
    if text.startswith("<!-->", i):
        return i + 5
    if text.startswith("<!--->", i):
        return i + 6
    for head, term in (("<!--", "-->"), ("<?", "?>"), ("<![CDATA[", "]]>")):
        if text.startswith(head, i):
            if _html_terms(text)[term] < i + len(head):
                return None
            return text.find(term, i + len(head)) + len(term)
    if text.startswith("<!", i) and text[i + 2:i + 3].isalpha():
        if _html_terms(text)[">"] < i + 2:
            return None
        return text.find(">", i + 2) + 1
    m = _ELEMENT_TAG_RE.match(text, i)
    return m.end() if m else None


def _iter_html(text, loose=False):
    """(start, end) of each raw inline HTML element in ``text``, as
    HTML_STRICT_TAG_RE (or, with ``loose``, HTML_TAG_RE) finds them, in
    linear time."""
    i = text.find("<")
    while i >= 0:
        end = _html_end(text, i)
        if end is None and loose:
            m = _LOOSE_TAG_RE.match(text, i)
            end = m.end() if m else None
        if end is not None:
            yield i, end
            i = text.find("<", end)
        else:
            i = text.find("<", i + 1)


# The readings of a text whose inline syntax the two renderers, or the
# definitions it depends on, may read in two ways (see _inline_constructs).
READ_REF = 1
READ_MD = 2
# (A reading with TeX math read as text, as the renderers read it: "\\("
# and "\\[" are escapes there. See _inline_readings.)
READ_TEX = 4


def _mdit_bad_link(dest):
    """Whether markdown-it refuses ``dest`` (a link destination without its
    angle brackets, escapes and character references decoded) as a link:
    a "javascript:", "vbscript:", "file:" or "data:" link, images in data
    links excepted."""
    dest = dest.strip().lower()
    return bool(_MDIT_BAD_PROTO_RE.match(dest)) and not _MDIT_GOOD_DATA_RE.match(dest)


def _mdit_bad_tail(text, open_paren):
    """Whether markdown-it refuses the destination of the inline link tail
    that opens at ``open_paren``."""
    pos = _skip_space(text, open_paren + 1)
    end = _mdit_scan_destination(text, pos, len(text))
    if end is None or end == pos:
        return False
    dest = text[pos:end]
    if dest.startswith("<") and dest.endswith(">"):
        dest = dest[1:-1]
    return _mdit_bad_link(_mdit_unescape(dest))


# markdown-it-py's inline HTML pattern (read at a position) and its autolink
# and e-mail patterns, for _mdit_inline.
_MDIT_HTML_ATTR = (r"(?:\s+[a-zA-Z_:][a-zA-Z0-9:._-]*"
                   r"(?:\s*=\s*(?:[^\"'=<>`\x00-\x20]+|'[^']*'|\"[^\"]*\"))?)")
_MDIT_HTML_RE = re.compile(
    r"(?:<[A-Za-z][A-Za-z0-9\-]*" + _MDIT_HTML_ATTR + r"*\s*/?>|</[A-Za-z][A-Za-z0-9\-]*\s*>"
    r"|<!---?>|<!--(?:[^-]|-[^-]|--[^>])*-->|<[?][\s\S]*?[?]>|<![A-Za-z][^>]*>"
    r"|<!\[CDATA\[[\s\S]*?\]\]>)")
_MDIT_AUTOLINK_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]{1,31}):([^<>\x00-\x20]*)$")
_MDIT_EMAIL_RE = re.compile(
    r"^([a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*)$")
MDIT_MAX_NESTING = 20
_MDIT_MEMO = {}
_MDIT_SYNTAX_RE = re.compile(r"[`<\\\[]")
# (The characters a rule of _mdit_inline starts at, and those that also
# matter while looking for the end of link text; the others are text.)
_MDIT_RULE_RE = re.compile(r"[\\`\[!<]")
_MDIT_LABEL_RE = re.compile(r"[\\`\[\]!<]")


def _mdit_destination(s, pos, mx):
    """markdown-it's link destination at ``pos`` (reading ``s[:mx]``):
    (ok, end, raw text without angle brackets)."""
    start = pos
    if pos < len(s) and s[pos] == "<":
        pos += 1
        while pos < mx:
            c = s[pos]
            if c == "\n" or c == "<":
                return False, 0, ""
            if c == ">":
                return True, pos + 1, s[start + 1:pos]
            if c == "\\" and pos + 1 < mx:
                pos += 2
                continue
            pos += 1
        return False, 0, ""
    level = 0
    while pos < mx:
        c = s[pos]
        if c == " " or c < " " or c == "\x7f":
            break
        if c == "\\" and pos + 1 < mx:
            if s[pos + 1] == " ":
                break
            pos += 2
            continue
        if c == "(":
            level += 1
            if level > 32:
                return False, 0, ""
        if c == ")":
            if level == 0:
                break
            level -= 1
        pos += 1
    if start == pos or level != 0:
        return False, 0, ""
    return True, pos, s[start:pos]


def _mdit_title_end(s, pos, mx):
    """End of markdown-it's link title at ``pos`` (reading ``s[:mx]``), or
    None."""
    if pos >= mx or s[pos] not in "\"'(":
        return None
    marker = ")" if s[pos] == "(" else s[pos]
    pos += 1
    while pos < mx:
        c = s[pos]
        if c == marker:
            return pos + 1
        if c == "(" and marker == ")":
            return None
        if c == "\\" and pos + 1 < mx:
            pos += 1
        pos += 1
    return None


class _MditState:
    """The state of one markdown-it inline parse (see _mdit_inline)."""
    __slots__ = ("src", "pos", "max", "level", "cache", "ticks", "scanned", "resolves", "has_refs",
                 "out", "base", "found")

    def __init__(self, src, resolves, has_refs, base=0):
        self.src = src
        self.pos = 0
        self.max = len(src)
        self.level = 0
        # (skipToken's cache, and the backtick rule's: the last position
        # seen of each closer length, and whether a scan reached the end.)
        self.cache = {}
        self.ticks = {}
        self.scanned = False
        self.resolves = resolves
        self.has_refs = has_refs
        self.out = []
        self.base = base
        self.found = {}

    def find(self, needle, start):
        """``src.find(needle, start)``, remembered, so that many raw HTML
        openers without an end take linear time."""
        known = self.found.get(needle)
        if known is not None and known[0] <= start and (known[1] < 0 or known[1] >= start):
            return known[1]
        at = self.src.find(needle, start)
        self.found[needle] = (start, at)
        return at


def _mdit_space(c):
    return c == " " or c == "\t"


def _mdit_backtick(st, silent):
    src = st.src
    start = pos = st.pos
    pos += 1
    mx = st.max
    while pos < mx and src[pos] == "`":
        pos += 1
    run = pos - start
    if st.scanned and st.ticks.get(run, 0) <= start:
        # A scan reached the end without a closer of this length past the
        # last one seen: the run is text, even where an earlier look-ahead
        # (link text) set this and a closer follows.
        st.pos += run
        return True
    end = pos
    while True:
        close = src.find("`", end)
        if close < 0:
            break
        end = close + 1
        while end < mx and src[end] == "`":
            end += 1
        if end - close == run:
            if not silent:
                st.out.append(("code", st.base + start, st.base + end, src[pos:close]))
            st.pos = end
            return True
        st.ticks[end - close] = close
    st.scanned = True
    st.pos += run
    return True


def _mdit_escape(st, silent):
    src = st.src
    pos = st.pos + 1
    mx = st.max
    if pos >= mx:
        return False
    if src[pos] == "\n":
        pos += 1
        while pos < mx and _mdit_space(src[pos]):
            pos += 1
        st.pos = pos
        return True
    if not silent and src[pos] in ESCAPABLE:
        st.out.append(("escape", st.base + pos - 1, st.base + pos + 1, src[pos - 1:pos + 1]))
    st.pos = pos + 1
    return True


def _mdit_label(st, start, no_nesting):
    """parseLinkLabel: the end of the link text that opens at ``start``,
    or -1."""
    old = st.pos
    found = False
    st.pos = start + 1
    level = 1
    src = st.src
    while st.pos < st.max:
        marker = src[st.pos]
        if marker == "]":
            level -= 1
            if level == 0:
                found = True
                break
        elif marker not in "\\`[!<" and st.level < MDIT_MAX_NESTING:
            # (Text up to the next character that matters, remembered as
            # skipToken remembers it: past the nesting limit, skipping a
            # character it has not seen ends the text.)
            m = _MDIT_LABEL_RE.search(src, st.pos + 1, st.max)
            end = m.start() if m else st.max
            st.cache.setdefault(st.pos, end)
            st.pos = st.cache[st.pos]
            continue
        prev = st.pos
        _mdit_skip(st)
        if marker == "[":
            if prev == st.pos - 1:
                level += 1
            elif no_nesting:
                st.pos = old
                return -1
    end = st.pos if found else -1
    st.pos = old
    return end


def _mdit_link(st, silent, image=False):
    src = st.src
    old = st.pos
    mx = st.max
    if image:
        if st.pos + 1 < st.max and src[st.pos + 1] != "[":
            return False
        label_start = st.pos + 2
        label_end = _mdit_label(st, st.pos + 1, False)
    else:
        label_start = st.pos + 1
        label_end = _mdit_label(st, st.pos, True)
    if label_end < 0:
        return False
    pos = label_end + 1
    reference = True
    tail = None
    if pos < mx and src[pos] == "(":
        reference = False
        tail = pos
        pos += 1
        while pos < mx and (_mdit_space(src[pos]) or src[pos] == "\n"):
            pos += 1
        if pos >= mx:
            return False
        ok, end, raw = _mdit_destination(src, pos, st.max)
        if ok and not _mdit_bad_link(_mdit_unescape(raw)):
            pos = end
        start = pos
        while pos < mx and (_mdit_space(src[pos]) or src[pos] == "\n"):
            pos += 1
        end = _mdit_title_end(src, pos, st.max)
        if pos < mx and start != pos and end is not None:
            pos = end
            while pos < mx and (_mdit_space(src[pos]) or src[pos] == "\n"):
                pos += 1
        if pos >= mx or src[pos] != ")":
            if image:
                st.pos = old
                return False
            reference = True
            tail = None
        pos += 1
    if reference:
        if not st.has_refs:
            return False
        label = None
        if pos < mx and src[pos] == "[":
            start = pos + 1
            pos = _mdit_label(st, pos, False)
            if pos >= 0:
                label = src[start:pos]
                pos += 1
            else:
                pos = label_end + 1
        else:
            pos = label_end + 1
        if not st.resolves(label or src[label_start:label_end]):
            st.pos = old
            return False
    if not silent:
        if tail is not None:
            st.out.append(("linktail", st.base + tail, st.base + pos, src[tail:pos]))
        if image:
            # (Image text is parsed on its own, with fresh caches.)
            sub = _MditState(src[label_start:label_end], st.resolves, st.has_refs, st.base + label_start)
            _mdit_tokenize(sub)
            st.out += sub.out
        else:
            st.pos = label_start
            st.max = label_end
            st.level += 1
            _mdit_tokenize(st)
            st.level -= 1
    st.pos = pos
    st.max = mx
    return True


def _mdit_angle(st, silent):
    """markdown-it's autolink rule, then its inline HTML rule."""
    src = st.src
    start = pos = st.pos
    mx = st.max
    while True:
        pos += 1
        if pos >= mx or src[pos] == "<":
            url = None
            break
        if src[pos] == ">":
            url = src[start + 1:pos]
            break
    if url is not None and (_MDIT_AUTOLINK_RE.search(url) or _MDIT_EMAIL_RE.search(url)):
        full = url if _MDIT_AUTOLINK_RE.search(url) else "mailto:" + url
        if not _mdit_bad_link(full):
            if not silent:
                st.out.append(("autolink", st.base + start, st.base + pos + 1, src[start:pos + 1]))
            st.pos = pos + 1
            return True
    if start + 2 >= mx:
        return False
    c = src[start + 1]
    if c not in "!?/" and not "a" <= chr(ord(c) | 0x20) <= "z":
        return False
    # (Each form that runs to an end marker needs one ahead.)
    if c == "?" and st.find("?>", start + 2) < 0:
        return False
    if c == "!":
        if src.startswith("<!--", start):
            if st.find("-->", start + 4) < 0 and not src.startswith(("<!-->", "<!--->"), start):
                return False
        elif src.startswith("<![CDATA[", start):
            if st.find("]]>", start + 9) < 0:
                return False
        elif st.find(">", start + 2) < 0:
            return False
    m = _MDIT_HTML_RE.match(src, start)
    if not m:
        return False
    if not silent:
        st.out.append(("html", st.base + start, st.base + m.end(), m.group(0)))
    st.pos = m.end()
    return True


def _mdit_rule(st, silent):
    c = st.src[st.pos]
    if c == "\\":
        return _mdit_escape(st, silent)
    if c == "`":
        return _mdit_backtick(st, silent)
    if c == "[":
        return _mdit_link(st, silent)
    if c == "!":
        return _mdit_link(st, silent, True)
    if c == "<":
        return _mdit_angle(st, silent)
    return False


def _mdit_skip(st):
    pos = st.pos
    if pos in st.cache:
        st.pos = st.cache[pos]
        return
    ok = False
    if st.level < MDIT_MAX_NESTING:
        st.level += 1
        ok = _mdit_rule(st, True)
        st.level -= 1
    else:
        st.pos = st.max
    if not ok:
        st.pos += 1
    st.cache[pos] = st.pos


def _mdit_tokenize(st):
    end = st.max
    src = st.src
    while st.pos < end:
        if src[st.pos] not in "\\`[!<":
            m = _MDIT_RULE_RE.search(src, st.pos + 1, end)
            st.pos = m.start() if m else end
            continue
        if st.level < MDIT_MAX_NESTING and _mdit_rule(st, False):
            if st.pos >= end:
                break
            continue
        st.pos += 1


def _mdit_inline(text, resolve=None, reading=0, seen=None):
    """The code spans, raw HTML, autolinks, inline link tails and backslash
    escapes markdown-it reads in ``text`` (one inline content), as
    _inline_constructs gives them, sorted: an emulation of markdown-it-py's
    inline parser, reduced to the rules that decide them (escapes, code
    spans with the backtick rule's scan cache, links and images with their
    look-ahead over the link text and its cache, autolinks, inline HTML; the
    others only step over text). Where that cache was set by a look-ahead
    over link text, a later backtick run is text although a closer follows.
    A label that may or may not resolve (``resolve``) resolves in the
    READ_REF reading; READ_REF goes to ``seen`` where that changes the
    parse. TeX math is text."""
    out, met = _mdit_parse(text, resolve, reading)
    if met and seen is not None and READ_REF not in seen:
        if _mdit_parse(text, resolve, reading ^ READ_REF)[0] != out:
            seen.add(READ_REF)
    return out


def _mdit_parse(text, resolve, reading):
    """(constructs, whether a label that may or may not resolve was asked
    about) for _mdit_inline, remembered by text and answers."""
    has_refs = resolve is None or getattr(resolve, "mdit_refs", None) is not False
    ask = getattr(resolve, "probe", resolve)
    answers = {}

    def resolves(label):
        if label not in answers:
            status = ask(label) if ask is not None else "maybe"
            if status in ("yes", "md"):
                answers[label] = (True, False)
            elif status in ("no", "cm"):
                answers[label] = (False, False)
            else:
                answers[label] = (bool(reading & READ_REF), True)
        return answers[label][0]

    entries = _MDIT_MEMO.get((text, has_refs))
    for asked, out in entries or ():
        # (The same answers to the labels asked give the same parse.)
        if all(resolves(label) == value for label, value in asked):
            return out, any(answers[label][1] for label, _ in asked)
    st = _MditState(text, resolves, has_refs)
    _mdit_tokenize(st)
    out = sorted(st.out, key=lambda c: c[1])
    if len(_MDIT_MEMO) > 4096:
        _MDIT_MEMO.clear()
    _MDIT_MEMO.setdefault((text, has_refs), []).append(
        (tuple((label, value) for label, (value, _) in answers.items()), out))
    return out, any(m for _, m in answers.values())


def _inline_constructs(text, reading=0, seen=None, resolve=None):
    """Code spans, raw HTML, autolinks, inline link tails, TeX math and
    backslash escapes, in one left-to-right pass, as (kind, start, end,
    value) tuples (kinds "code", "html", "autolink", "linktail", "math",
    "escape"). Scanning in order gets escape parity right (in "\\\\*" the
    backslash is escaped and the star is active, an escaped backtick never
    opens a code span, and backslashes inside a code span are literal) and
    precedence too, as CommonMark has it: whichever of a code span, raw HTML
    or an autolink starts first wins, so a backtick inside a tag's attribute
    opens no code span, and the destination and title after "](" that close
    an open bracket belong to the link, not to a code span. A link (inline,
    or a reference that resolves) deactivates the brackets open before it
    that open no image, as in CommonMark: their closing brackets start no
    link, so what looks like a destination and title after them is text.

    Two choices depend on more than the text, and ``reading`` (bits) makes
    them; the bit of each choice met goes to ``seen``:

    - READ_REF: "[text][label](...)" is a reference link followed by
      parentheses (text that may hold a code span) when the label is
      defined, and "[label](...)" an inline link when it is not; the label
      of a reference link is not read either (a backtick in it opens no
      code span). A reference inside link text that may resolve
      deactivates the brackets open before it only in this reading.
      ``resolve`` (see extract_tokens) decides when it can.
    - READ_MD: markdown-it's reading, from _mdit_inline (it refuses links
      to "javascript:", "vbscript:", "file:" and "data:" destinations,
      finds the end of link text by looking ahead, reads an image as one
      token and keeps a backtick scan cache across that look-ahead). The
      choice is met where it differs from this scan (outside TeX math).

    With READ_TEX in ``reading``, TeX math is text, as the renderers read
    it: "\\(" and "\\[" are escapes.
    """
    if reading & READ_MD:
        return _mdit_inline(text, resolve, reading, seen)
    out = []
    n = len(text)
    opens = []
    # (For each open bracket: [opens an image, inactive, walked]. A link
    # deactivates the brackets open before it that open no image, so their
    # closing brackets start no link. Each walk stops where an earlier one
    # did, so the work stays linear.)
    state = []
    escaped = set()

    def deactivate():
        for entry in reversed(state):
            if entry[2]:
                break
            entry[2] = True
            entry[1] = entry[1] or not entry[0]
    i = 0
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt in "([" and not reading & READ_TEX:
                closer = "\\)" if nxt == "(" else "\\]"
                end = text.find(closer, i + 2)
                if end >= 0:
                    out.append(("math", i, end + 2, text[i:end + 2]))
                    i = end + 2
                    continue
            if nxt in ESCAPABLE:
                out.append(("escape", i, i + 2, text[i:i + 2]))
                escaped.add(i + 1)
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
        if ch == "<":
            end = _html_end(text, i)
            kind = "html"
            if end is None:
                m = AUTOLINK_RE.match(text, i)
                end = m.end() if m else None
                kind = "autolink"
            if end is not None:
                out.append((kind, i, end, text[i:end]))
                i = end
                continue
            i += 1
            continue
        if ch == "[":
            image = i > 0 and text[i - 1] == "!" and i - 1 not in escaped
            opens.append(i)
            state.append([image, False, False])
        elif ch == "]" and opens:
            start = opens.pop()
            image, inactive, _ = state.pop()
            if inactive:
                # (An inactive opener: the bracket is text.)
                i += 1
                continue
            second = _ref_label_close(text, i + 1) if i + 2 < n and text[i + 1] == "[" else None
            if second is not None:
                # (It matters where parentheses follow, or where the label
                # holds a backtick or "<", which are not read as code or
                # HTML when the label is consumed.)
                if ((second + 1 < n and text[second + 1] == "("
                     and _link_tail(text, second + 1)[0] is not None)
                        or "`" in text[i + 2:second] or "<" in text[i + 2:second]):
                    label = text[i + 2:second] or text[start + 1:i]
                    status = resolve(label, _label_ok(label)) if resolve is not None else "maybe"
                    if status not in ("yes", "no") and seen is not None:
                        seen.add(READ_REF)
                    if status == "yes" or (status != "no" and reading & READ_REF):
                        # A reference link: its label is not read, and the
                        # parentheses after it are text.
                        if not image:
                            deactivate()
                        i = second + 1
                        continue
            if i + 1 < n and text[i + 1] == "(":
                end, _ = _link_tail(text, i + 1)
                if end is not None:
                    out.append(("linktail", i + 1, end, text[i + 1:end]))
                    if not image:
                        deactivate()
                    i = end
                    continue
            if not image and state:
                # A reference link (full, collapsed or shortcut) deactivates
                # the brackets open before it too.
                label = (text[i + 2:second] if second is not None else "") or text[start + 1:i]
                status = resolve(label, _label_ok(label)) if resolve is not None else "maybe"
                if status not in ("yes", "no") and seen is not None:
                    seen.add(READ_REF)
                if status == "yes" or (status != "no" and reading & READ_REF):
                    deactivate()
                    if second is not None:
                        i = second + 1
                        continue
        i += 1
    if seen is not None and READ_MD not in seen and _MDIT_SYNTAX_RE.search(text):
        # markdown-it's reading is one of its own where it differs from this
        # one outside TeX math (inside it, the readings with math as text
        # compare).
        math = [(s, e) for kind, s, e, _ in out if kind == "math"]
        theirs = _mdit_inline(text, resolve, reading | READ_MD, seen)
        if math:
            theirs = [c for c in theirs if not any(a <= c[1] and c[2] <= b for a, b in math)]
        if theirs != [c for c in out if c[0] != "math"]:
            seen.add(READ_MD)
    return out


def _inline_readings(text, resolve=None, tex=False):
    """(reading, constructs) for every reading of ``text`` (see
    _inline_constructs) that a choice it meets makes: the first is reading
    0, and there are others only when a choice is met. With ``tex``, TeX
    math is read as text in each (READ_TEX, which the reading numbers
    leave out)."""
    seen = set()
    extra = READ_TEX if tex else 0
    readings = {0: _inline_constructs(text, extra, seen, resolve)}
    while True:
        bits = sum(seen)
        todo = [r for r in range(1, 4) if r & bits == r and r not in readings]
        if not todo:
            break
        for r in todo:
            readings[r] = _inline_constructs(text, r | extra, seen, resolve)
    return sorted(readings.items())


def _expanded_readings(readings):
    """Readings 0 to 3 of an _inline_readings result, as (reading,
    constructs): a reading whose choice the text never meets is the reading
    without that choice. So a text that meets a choice that changes
    nothing, and one that does not meet it, read the same."""
    table = dict(readings)
    bits = 0
    for r in table:
        bits |= r
    return [(r, table[r & bits]) for r in range(4)]


def _reading_variants(readings):
    """The expanded readings 1 to 3 (see _expanded_readings) that differ
    from reading 0."""
    expanded = _expanded_readings(readings)
    return [(r, constructs) for r, constructs in expanded[1:] if constructs != expanded[0][1]]


def _ref_readings(text, resolve=None, tex=False):
    """_inline_readings of ``text`` with every combination of the labels
    that may or may not resolve (``resolve``, see _doc_label_resolver; None:
    any may) resolving or not, not only all or none of them, up to
    MAYBE_LABEL_GROUPS such labels (also those that only some combination
    reaches); None past that (unknown)."""
    keys = []

    def make(chosen):
        def fixed(label, cm_valid=True):
            status = resolve(label, cm_valid) if resolve is not None else "maybe"
            if status in ("yes", "no"):
                return status
            key = normalize_label(label)
            if key not in keys:
                keys.append(key)
            if chosen is None:
                return status
            return "yes" if key in chosen else "no"

        def probe(label):
            # (For markdown-it's reading: a label only it asks about is not
            # enumerated; it resolves with the others or not at all.)
            status = resolve(label) if resolve is not None else "maybe"
            if status in ("yes", "no") or chosen is None:
                return status
            return "yes" if normalize_label(label) in chosen else "no"
        fixed.probe = probe
        fixed.mdit_refs = getattr(resolve, "mdit_refs", None)
        return fixed
    while True:
        out = list(_inline_readings(text, make(None), tex))
        known = list(keys)
        if len(known) > MAYBE_LABEL_GROUPS:
            return None
        for pick in range(1, (1 << len(known)) - 1) if len(known) > 1 else ():
            out.extend(_inline_readings(text, make({known[b] for b in range(len(known)) if pick >> b & 1}), tex))
            if len(keys) > MAYBE_LABEL_GROUPS:
                return None
        if len(keys) == len(known):
            return out

def _scan_inline(text, resolve=None):
    """Find code spans, TeX math and backslash escapes (see
    _inline_constructs, which also reads raw HTML, autolinks and link tails
    so that no code span starts inside them)."""
    return [c for c in _inline_constructs(text, resolve=resolve) if c[0] in ("code", "math", "escape")]


def extract_tokens(text, labels=None, refs=None, maybe=None, url_marks=None, alt_masks=None):
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

    Underscores and tildes inside a protected word (an identifier such as
    ``_private``, a path such as ``~/file``, a long run) stay in ``masked``:
    the renderers do not know these words, so a marker at the edge of one
    may pair with another (one between letters never does). ``url_marks`` collects the positions and
    characters of the emphasis markers inside bare URLs, which renderers
    without autolinks read as markers and GitHub reads as part of a link.
    ``alt_masks`` collects (reading, masked) for each reading of the text
    (see _inline_readings, also with TeX math read as text) in which text
    that ``masked`` hides is text to the renderers: emphasis markers inside
    inline math, and inside what looks like an inline link's destination or
    title where that reading has no link there (markdown-it refuses it, or
    link text before it holds a link, or a reference resolves before it).
    """
    chars = list(text)
    found = []
    unhide = []

    def resolve(label, cm_valid=True):
        """"yes", "maybe" or "no": whether a reference label resolves, or
        "cm" or "md" when only cmark-gfm or only markdown-it resolves it."""
        if refs is None:
            return "maybe"
        cm = "no"
        if cm_valid:
            norm = normalize_label(label)
            cm = "yes" if norm in refs[0] else ("maybe" if norm in refs[1] else "no")
        if len(refs) < 4:
            return cm
        key = mdit_label_key(label)
        md = "yes" if key and key in refs[2] else ("maybe" if key and key in refs[3] else "no")
        if cm == md:
            return cm
        if "maybe" in (cm, md):
            return "maybe"
        # Only one renderer resolves it: "cm" for cmark-gfm, "md" for
        # markdown-it. Each reading then takes its own renderer's links.
        return "cm" if cm == "yes" else "md"

    def current():
        return "".join(chars)

    readings = _inline_readings(current(), resolve)
    tex = _renderer_readings(current(), resolve, readings)
    # (Where the renderers may read text that the masks below hide: see
    # alt_masks.)
    exposable = []
    # (Only the readings that differ, with the choices the text does not
    # meet read as not taken: see _expanded_readings.)
    others = _reading_variants(readings) + ([(READ_TEX | r, constructs) for r, constructs in
                                             tex[:1] + _reading_variants(tex)]
                                            if tex is not readings else [])
    for reading, constructs in others:
        # Where the text reads in two ways (a reference label that may or
        # may not be defined, a link that only cmark-gfm takes), the code,
        # raw HTML, autolinks and link tails of the other reading are
        # protected too; so are those of the readings with TeX math read
        # as text, as the renderers read it (a code span may open inside
        # it and close past it).
        alt = list(text)
        for kind, start, end, _ in constructs:
            if kind != "escape":
                _mask(alt, start, end)
        alt = "".join(alt)
        stray = tuple(re.findall(r"`+", alt))
        found.append((0, "reading", (reading, tuple(
            (kind, value) for kind, _, _, value in constructs if kind not in ("math", "escape")),
            # (Backtick strings no code span of that reading takes, and,
            # next to one, its brackets: see compare_prose.)
            stray, tuple(re.findall(r"[][]", alt)) if stray else ())))
    for kind, start, end, value in readings[0][1]:
        if kind not in ("code", "math", "escape"):
            continue
        found.append((start, kind, value))
        if kind in ("math", "code"):
            # (Text in a reading where it is no math or code span there: in
            # markdown-it's, a code span after its backtick cache is set.)
            exposable.append((start, end))
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
        exposable.append((m.start(), m.end()))

    # The link tails of the text as read here are protected as they stand
    # (the link scan below may miss one among nested brackets).
    for kind, start, end, value in readings[0][1]:
        if kind == "linktail":
            # (Whitespace inside the parentheses at either end is syntax.)
            found.append((start, "tail", "(" + value[1:-1].strip(" \t\n") + ")"))
    math_spans = [(s, e) for s, e in exposable]
    if math_spans and re.search(r"[*_~]", text) and any(
            kind == "linktail" and any(a <= start < b for a, b in math_spans)
            for _, constructs in readings + (tex if tex is not readings else [])
            for kind, start, _, _ in constructs):
        # A link inside TeX math with emphasis markers around: its text is an
        # emphasis boundary in the readings with math as text, which the
        # emphasis checks below do not model. The unit is kept byte for byte.
        found.append((0, "frozen", text))

    for m in AUTOLINK_RE.finditer(current()):
        found.append((m.start(), "autolink", m.group(0)))
        _mask(chars, m.start(), m.end())

    links, ambiguous = _scan_links(current(), resolve, text)
    if ambiguous:
        found.append((0, "frozen", text))
    for start, label_start, label_end, end, kind, target in links:
        found.append((start, kind, target))
        # Keep the link text editable; mask the syntax and the target.
        _mask(chars, start, label_start)
        _mask(chars, label_end, end)
        exposable.append((label_end + 1, end))

    if labels is not None:
        # Link and image labels are boundaries for emphasis: inline links,
        # and reference links whose label the document defines (with the
        # same bracket scanner). A reference that may or may not resolve
        # gives a possible boundary. Links do not nest, so link text that
        # holds a link is no boundary; a unit whose link text holds a link
        # that may or may not resolve is kept byte for byte.
        # (An inline link or image markdown-it refuses, such as one to a
        # "file:" destination, is a boundary in cmark-gfm's reading only.)
        spans = [(ls, le, kind, "cm" if text[le + 1:le + 2] == "(" and _mdit_bad_tail(text, le + 1) else "yes",
                  None) for _, ls, le, _, kind, _ in links]
        ref_spans = _scan_refs(current(), text, resolve)
        spans += ref_spans
        if ref_spans and _unpaired_bracket(current()):
            # An unpaired bracket next to a reference that may resolve: what
            # the brackets around it become (link text, a label, a failed
            # inline link tail) depends on details the bracket scanner does
            # not model. The unit is kept byte for byte.
            found.append((0, "frozen", text))
        # The ordered links and images of the unit, from the same bracket
        # scanner: kind, whether they resolve, and the label that decides it,
        # in order of their opening bracket. It is compared on its own (after
        # every other token), as link text that holds brackets can hide a
        # changed sequence from the reference patterns below.
        sequence = [(sp[2], sp[3], sp[4]) for sp in sorted(spans, key=lambda sp: (sp[0], -sp[1])) if sp[3] != "no"]
        if sequence:
            found.append((len(text) + 1, "linkseq", repr(sequence)))
        # The statuses of the links inside each link, found in one pass over
        # the spans sorted by start (bracket spans nest or stay apart), so
        # many links in one paragraph take linear time.
        order = sorted(range(len(spans)), key=lambda k: (spans[k][0], -spans[k][1]))
        inside = {}
        for pos, k in enumerate(order):
            ls, le = spans[k][0], spans[k][1]
            found_inner = []
            # (The ends of the images inside, around the spans that follow:
            # markdown-it reads an image as one token, so a link inside one
            # leaves the link around it alone there.)
            image_ends = []
            nxt = pos + 1
            while nxt < len(order) and spans[order[nxt]][0] <= le:
                sp = spans[order[nxt]]
                while image_ends and image_ends[-1] <= sp[0]:
                    image_ends.pop()
                if sp[2] == "link" and sp[1] <= le and (sp[0], sp[1]) != (ls, le):
                    found_inner.append((sp[3], bool(image_ends)))
                elif sp[2] == "image" and sp[3] not in ("no", "cm") and sp[1] <= le:
                    # (Not one markdown-it refuses: it is no image there.)
                    image_ends.append(sp[1])
                nxt += 1
            inside[k] = found_inner
        for ls, le, kind, status, key in spans:
            if kind == "image" and status != "no":
                # "![" of an image (also one whose alt text holds brackets,
                # which the reference patterns above do not take).
                found.append((ls - 2, "image_open", "!["))
        for k, (ls, le, kind, status, key) in enumerate(spans):
            if kind == "link" and inside[k]:
                # Links do not nest: link text that holds a link is text, in
                # cmark-gfm also where the link is inside an image, and each
                # renderer reads its own links ("cm", "md").
                inner = [(st, img) for st, img in inside[k] if st != "no"]
                in_cm = status in ("yes", "cm") and not any(st in ("yes", "cm") for st, _ in inner)
                in_md = status in ("yes", "md") and not any(st in ("yes", "md") and not img for st, img in inner)
                if not in_cm and not in_md:
                    continue
                if ((in_cm and any(st not in ("yes", "cm", "md") for st, _ in inner))
                        or (in_md and any(st not in ("yes", "cm", "md") and not img for st, img in inner))):
                    # Link text that holds a reference that may or may not be
                    # a link: what the outer brackets and the label after
                    # them become then depends on it and on the renderer.
                    # The unit is kept byte for byte.
                    found.append((0, "frozen", text))
                    break
                status = "yes" if in_cm and in_md else ("cm" if in_cm else "md")
            if status == "yes":
                labels.append((ls, le))
            elif maybe is not None:
                maybe.append((ls, le, key, status if status in ("cm", "md") else None))

    snapshot = current()
    for m in REF_LINK_RE.finditer(snapshot):
        kind = "reflink"
        if not m.group(3).strip(LABEL_SPACE):
            # Collapsed reference "[label][]": the text is the label.
            found.append((m.start(), kind, m.group(0)))
            unhide.extend((k, snapshot[k]) for k in range(m.start(), m.end()) if snapshot[k] in "*_~")
            _mask(chars, m.start(), m.end())
            continue
        found.append((m.start(), kind, (m.group(1) or "") + "[" + m.group(3) + "]"))
        # The reference label is protected. When it does not resolve, the
        # brackets are text and its emphasis markers pair with others; when
        # it may resolve, it is also a possible boundary.
        status = resolve(m.group(3), _label_ok(m.group(3)))
        if status != "yes":
            unhide.extend((k, snapshot[k]) for k in range(m.end(2), m.end()) if snapshot[k] in "*_~")
            if status != "no" and maybe is not None:
                maybe.append((m.start(3), m.end(3), normalize_label(m.group(3)),
                              status if status in ("cm", "md") else None))
        _mask(chars, m.start(), m.start(2))
        _mask(chars, m.end(2), m.end())

    for m in FOOTNOTE_REF_RE.finditer(current()):
        found.append((m.start(), "footnote", m.group(0)))
        _mask(chars, m.start(), m.end())

    snapshot = current()
    html_spans = list(_iter_html(snapshot, loose=True))
    for m in SHORTCUT_REF_RE.finditer(snapshot):
        # (Brackets of an inline link right after it, masked above, are a
        # label after it, which makes it no shortcut reference: marked when
        # its own label may be defined in a renderer that reads those
        # brackets as a label: cmark-gfm only without brackets inside,
        # markdown-it also with nested ones.)
        label_after = False
        if m.end() < len(text) and text[m.end()] == "[" and snapshot[m.end()] != "[":
            status = resolve(text[m.start() + (2 if m.group(0).startswith("!") else 1):m.end() - 1])
            close = _ref_label_close(text, m.end())
            # (markdown-it finds the end of that link's text, so it reads
            # those brackets as a label whatever they hold.)
            label_after = (status in ("yes", "maybe", "cm") and close is not None
                           and (close == m.end() + 1 or _label_ok(text[m.end() + 1:close]))) or (
                status in ("yes", "maybe", "md"))
        found.append((m.start(), "reflink", m.group(0) + ("[" if label_after else "")))
        if (m.group(0).startswith("!") and snapshot.startswith("(", m.end())
                and not any(a <= m.start() < b for a, b in html_spans)):
            # "![label](" that starts no inline image: cmark-gfm falls back
            # to a reference image, markdown-it to a "!" and a reference
            # link. The unit is kept byte for byte.
            found.append((0, "frozen", text))
        # The bracketed text is protected as a whole, as it may be a link
        # label; its emphasis markers still pair with those around it when
        # it is not a link.
        unhide.extend((k, snapshot[k]) for k in range(m.start(), m.end()) if snapshot[k] in "*_~")
        _mask(chars, m.start(), m.end())

    snapshot = current()
    for start, end in _iter_html(snapshot, loose=True):
        found.append((start, "tag", _normalize_tag(snapshot[start:end])))
        _mask(chars, start, end)

    for m in ENTITY_RE.finditer(current()):
        found.append((m.start(), "entity", m.group(0)))
        _mask(chars, m.start(), m.end())

    for m in URL_RE.finditer(current()):
        url = _strip_url(m.group(0))
        found.append((m.start(), "url", url))
        if url_marks is not None:
            url_marks.extend((k, chars[k]) for k in range(m.start(), m.start() + len(url))
                             if chars[k] in "*_~")
        _mask(chars, m.start(), m.start() + len(url))

    # Hide underscore emphasis delimiters from the identifier patterns so
    # "_some text_" stays prose, then restore them for the emphasis count.
    # Dunder names such as "__init__" stay identifiers.
    hidden = []
    for m in UNDERSCORE_EMPHASIS_RE.finditer(current()):
        delim = m.group(1)
        if delim == "__" and re.fullmatch(r"__\w+__", m.group(0), re.A):
            # The name stays one identifier, but its underscores still pair
            # as strong emphasis (cmark-gfm renders "__init__" bold).
            unhide.extend((k, "_") for k in (m.start(), m.start() + 1, m.end() - 2, m.end() - 1))
            continue
        width = len(delim)
        for k in list(range(m.start(), m.start() + width)) + list(range(m.end() - width, m.end())):
            hidden.append((k, chars[k]))
            chars[k] = "\x01"

    # After the emphasis underscores are hidden, so they stay delimiters.
    for m in LONG_RUN_RE.finditer(current()):
        value = m.group(0).rstrip(".:,;")
        found.append((m.start(), "word", value))
        unhide.extend((k, chars[k]) for k in range(m.start(), m.start() + len(value)) if chars[k] in "_~")
        _mask(chars, m.start(), m.start() + len(value))

    for m in WORD_TOKEN_RE.finditer(current()):
        kind = m.lastgroup
        value = m.group(0)
        if kind == "path" and value.lower() in PROSE_SLASH_PAIRS:
            continue
        if kind in ("digit", "dotted", "path", "scope"):
            value = value.rstrip(".:,;")
        if kind == "dotted" and value.lower() in PROSE_ABBREVIATIONS:
            continue
        if kind == "qty":
            value = re.sub(r"\s+", "", value)
            found.append((m.start(), "word", value))
            _mask(chars, m.start(), m.end())
            continue
        if not value:
            continue
        found.append((m.start(), "word", value))
        unhide.extend((k, chars[k]) for k in range(m.start(), m.start() + len(value)) if chars[k] in "_~")
        _mask(chars, m.start(), m.start() + len(value))

    for k, ch in hidden:
        chars[k] = ch
    for k, ch in unhide:
        chars[k] = ch

    # Link destinations, autolinks and URLs are read again from the original
    # text: code-span, math or escape syntax inside a destination is part of
    # the destination, so masking it above must not leave the rest editable.
    links, unmodeled = _scan_links(text, resolve, text)
    for start, _, _, _, _, target in links:
        found.append((start, "dest", target))
    if unmodeled:
        # A link nested beyond the scanner's limit: the whole unit is frozen.
        found.append((0, "frozen", text))
    for m in AUTOLINK_RE.finditer(text):
        found.append((m.start(), "dest", m.group(0)))
    # HTML tags that fit the strict grammar, read from the original text too,
    # so code or math masking elsewhere in the unit cannot split a tag.
    for start, end in _iter_html(text):
        found.append((start, "rawtag", _normalize_tag(text[start:end])))
    for m in URL_RE.finditer(text):
        found.append((m.start(), "dest", _strip_url(m.group(0))))

    found.sort(key=lambda item: item[0])
    tokens = [(kind, value) for _, kind, value in found]
    masked = "".join(chars)
    if alt_masks is not None and exposable:
        # Every reading, those with TeX math read as text included (the same
        # as the others where the text holds no math), so a reading one text
        # does not reach compares as the reading it has there.
        expanded = _expanded_readings(readings)
        expanded = expanded + [(READ_TEX | r, cs) for r, cs in
                               (_expanded_readings(tex) if tex is not readings else expanded)]
        made = {}
        for reading, constructs in expanded:
            if id(constructs) in made:
                if made[id(constructs)] is not None:
                    alt_masks.append((reading, made[id(constructs)]))
                continue
            made[id(constructs)] = None
            covered = [False] * len(text)
            for _, start, end, _ in constructs:
                covered[start:end] = [True] * (end - start)
            alt = list(masked)
            for start, end in exposable:
                for x in range(start, min(end, len(text))):
                    if text[x] in "*_~" and not covered[x]:
                        alt[x] = text[x]
            alt = "".join(alt)
            if alt != masked:
                made[id(constructs)] = alt
                alt_masks.append((reading, alt))
    return tokens, masked


EMPHASIS_RUN_RE = re.compile(r"\*+|_+|~+")


def _flank_class(ch):
    if ch is None or ch.isspace():
        return "space"
    if unicodedata.category(ch)[0] in "PS":
        return "punct"
    return "other"


def _delimiter_runs(original, masked, gfm=True, text_ends=frozenset()):
    """Emphasis delimiter runs in ``masked`` (so markers inside code, math or
    URLs are text), each with whether it can open or close emphasis by the
    CommonMark flanking rules, read against the characters of ``original``.

    ``gfm`` selects the cmark-gfm reading: ``~`` and ``~~`` are strikethrough
    runs, and tildes are skipped when looking at the characters around a
    star or underscore run. Otherwise it is the markdown-it reading: a run
    of two or more tildes holds one strikethrough delimiter per ``~~`` (an
    odd first tilde is text), and a tilde is punctuation like any other;
    link text is parsed on its own there, so a run that ends where link text
    ends (``text_ends``) has nothing after it."""
    ref = original if len(original) == len(masked) else masked
    runs = []
    for m in EMPHASIS_RUN_RE.finditer(masked):
        ch, size = m.group(0)[0], len(m.group(0))
        start = m.start()
        if ch == "~" and gfm and size > 100:
            # cmark-gfm reads at most 100 tildes at a time, so the last
            # piece of a longer run may be a strikethrough run of its own.
            size = size % 100
            start = m.end() - size
        count = size
        if ch == "~":
            if gfm and not 1 <= size <= 2:
                continue
            if not gfm:
                if size < 2:
                    continue
                count = size // 2
        bi, ai = start - 1, m.end()
        if ch != "~" and gfm:
            # cmark-gfm looks past tildes for the characters around a star
            # or underscore run (the strikethrough characters are skipped).
            while bi >= 0 and ref[bi] == "~":
                bi -= 1
            while ai < len(ref) and ref[ai] == "~":
                ai += 1
        before = _flank_class(ref[bi] if bi >= 0 else None)
        after = _flank_class(ref[ai] if ai < len(ref) and (gfm or ai not in text_ends) else None)
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
        runs.append({"ch": ch, "pos": start, "orig": count, "count": count,
                     "open": can_open, "close": can_close})
    return runs


def _pair_delimiters(stack, spans, literal, gfm=True):
    """Pair the delimiter runs in ``stack`` (in text order) with the CommonMark
    "process emphasis" rules, including the rule of three. Adds (start, end,
    kind) to ``spans`` and counts the delimiters that stay literal in
    ``literal``.

    In the cmark-gfm reading (``gfm``) a tilde run finds its opener as an
    emphasis run does, but strikes through only when both runs have the same
    length; otherwise both runs and every delimiter between them stay text.
    cmark-gfm also keeps one search floor per character and closer length
    (modulo 3): a closer that finds no opener stops later closers of that
    class from looking further back, which can change the result. In the
    markdown-it reading each ``~~`` pairs with the nearest ``~~`` opener,
    without the rule of three, and the floor also depends on whether the
    closer can open, so it only saves time."""

    def drop(run):
        if run["count"]:
            key = run["ch"] if (run["ch"] != "~" or gfm) else "~~"
            literal[key] = literal.get(key, 0) + run["count"]

    floor = {}
    ci = 0
    while ci < len(stack):
        closer = stack[ci]
        if not closer["close"]:
            ci += 1
            continue
        found = None
        if gfm:
            key = (closer["ch"], closer["orig"] % 3)
        else:
            # markdown-it's floor also keys on whether the closer can open,
            # which makes it only a shortcut (the result is the same).
            key = (closer["ch"], closer["open"], closer["orig"] % 3 if closer["ch"] != "~" else 0)
        lowest = floor.get(key, -1)
        for oi in range(ci - 1, -1, -1):
            opener = stack[oi]
            if opener["pos"] < lowest:
                break
            if opener["ch"] != closer["ch"] or not opener["open"]:
                continue
            if closer["ch"] == "~" and not gfm:
                found = oi
                break
            if ((opener["close"] or closer["open"])
                    and (opener["orig"] + closer["orig"]) % 3 == 0
                    and not (opener["orig"] % 3 == 0 and closer["orig"] % 3 == 0)):
                continue
            found = oi
            break
        if found is not None and gfm and closer["ch"] == "~" and stack[found]["orig"] != closer["orig"]:
            for run in stack[found:ci + 1]:
                drop(run)
            del stack[found:ci + 1]
            ci = found
            continue
        if found is None:
            floor[key] = closer["pos"]
            if not closer["open"]:
                drop(closer)
                del stack[ci]
            else:
                ci += 1
            continue
        opener = stack[found]
        if closer["ch"] == "~":
            use, kind = (closer["orig"] if gfm else 1), "del"
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


def emphasis_structure(original, masked, labels=(), gfm=True):
    """The emphasis a prose unit renders, independent of the words inside.

    Delimiter runs are paired with the CommonMark rules. Runs inside a link
    or image label pair only with each other (innermost label first), as a
    label is closed before the text around it. The result is the nesting of
    the spans (em and strong with their delimiter character, and del), with
    siblings in sorted order so emphasis can move with its words, plus the
    delimiters that stay literal. Moving a marker away from its word,
    regrouping markers, or swapping ``*`` and ``_`` changes the result.
    """
    runs = _delimiter_runs(original, masked, gfm, frozenset(end for _, end in labels))
    spans = []
    literal = {}
    # Each run belongs to the smallest label that holds it (labels nest), found
    # in one sweep over the runs and the labels sorted by start; the labels
    # are then paired innermost first.
    bounds = sorted(set(labels), key=lambda lb: (lb[0], -lb[1]))
    groups = {lb: [] for lb in bounds}
    outside = []
    open_labels = []
    li = 0
    for run in runs:
        while li < len(bounds) and bounds[li][0] <= run["pos"]:
            open_labels.append(bounds[li])
            li += 1
        while open_labels and open_labels[-1][1] <= run["pos"]:
            open_labels.pop()
        holder = None
        for lb in reversed(open_labels):
            if lb[0] <= run["pos"] < lb[1]:
                holder = lb
                break
        (groups[holder] if holder is not None else outside).append(run)
    for lb in sorted(bounds, key=lambda lb: lb[1] - lb[0]):
        _pair_delimiters(groups[lb], spans, literal, gfm)
    _pair_delimiters(outside, spans, literal, gfm)

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

    # Describe each span after its children (they come later in the sorted
    # order), without recursion: markdown-it nests one strikethrough per
    # "~~" of a long run. A long description is replaced by its digest, so
    # deep nesting stays linear in size.
    desc = {}
    for idx in range(len(spans) - 1, -1, -1):
        text = spans[idx][2] + "(" + ",".join(sorted(desc.pop(c) for c in children[idx])) + ")"
        if len(text) > 200:
            text = spans[idx][2] + "#" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
        desc[idx] = text
    forest = sorted(desc[c] for c in children[None])
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
    for regex in (INLINE_MATH_RE, AUTOLINK_RE):
        for m in regex.finditer("".join(chars)):
            _blank_out(chars, m.start(), m.end(), "\x02")
    for start, end in list(_iter_html("".join(chars))):
        _blank_out(chars, start, end, "\x02")
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
    if [m[2:] for m in src_maybe] != [m[2:] for m in cand_maybe]:
        raise GuardReject("inline_markup", "%s: bracketed text changed" % where)

    def has_markers(masked, span):
        return bool(re.search(r"[*_~]", masked[span[0]:span[1]]))

    relevant = [k for k in range(len(src_maybe))
                if has_markers(src_masked, src_maybe[k]) or has_markers(cand_masked, cand_maybe[k])]
    # Labels that only one renderer resolves are boundaries in that
    # renderer's reading only; the others may or may not resolve, and every
    # combination of them is checked.
    keys = []
    for k in relevant:
        if src_maybe[k][3] is None and src_maybe[k][2] not in keys:
            keys.append(src_maybe[k][2])
    if len(keys) > AMBIGUOUS_LABEL_LIMIT:
        if src == cand:
            return
        raise GuardReject(
            "inline_markup",
            "%s: emphasis markers inside bracketed texts with more than %d different labels that may "
            "be links" % (where, AMBIGUOUS_LABEL_LIMIT))
    for bits in range(1 << len(keys)):
        on = [key for idx, key in enumerate(keys) if bits >> idx & 1]
        chosen = [k for k in relevant if src_maybe[k][3] is None and src_maybe[k][2] in on]
        # Both readings must stay the same: cmark-gfm and markdown-it differ
        # on tildes, on reference labels, and at the end of link text.
        for gfm in (True, False):
            own = [k for k in relevant if src_maybe[k][3] == ("cm" if gfm else "md")]
            src_bounds = src_labels + [src_maybe[k][:2] for k in chosen + own]
            cand_bounds = cand_labels + [cand_maybe[k][:2] for k in chosen + own]
            if (emphasis_structure(src, src_masked, src_bounds, gfm)
                    != emphasis_structure(cand, cand_masked, cand_bounds, gfm)):
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
    src_marks, cand_marks = [], []
    src_alt, cand_alt = [], []
    src_tokens, src_masked = extract_tokens(src, src_labels, refs, src_maybe, src_marks, src_alt)
    cand_tokens, cand_masked = extract_tokens(cand, cand_labels, refs, cand_maybe, cand_marks, cand_alt)
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
    # Where a reading of the renderers takes emphasis markers that the masks
    # hide (inside TeX math, or a destination and title that are text
    # there), they must pair the same way in it too.
    src_alt, cand_alt = dict(src_alt), dict(cand_alt)
    checked = set()
    for reading in sorted(set(src_alt) | set(cand_alt)):
        pair = (src_alt.get(reading, src_masked), cand_alt.get(reading, cand_masked))
        if pair in checked:
            continue
        checked.add(pair)
        _check_emphasis(src, pair[0], src_labels, src_maybe,
                        cand, pair[1], cand_labels, cand_maybe, where)
    # A backtick string outside code (one no other string of its length
    # closes) is markup too: adding or removing one can pair others
    # differently, and markdown-it, after an unclosed "[", reads every code
    # span of that length before an unmatched string as text.
    stray = re.findall(r"`+", src_masked)
    if stray != re.findall(r"`+", cand_masked):
        raise GuardReject("inline_markup", "%s: backtick strings outside code changed" % where)
    # (markdown-it's scan for the end of link text from an unclosed "[" can
    # leave its backtick state behind when it passes a backtick string
    # nothing closes, and later code spans of that length then render as
    # text: where the text holds such a string, the brackets outside code
    # are markup too.)
    if stray and re.findall(r"[][]", src_masked) != re.findall(r"[][]", cand_masked):
        raise GuardReject("inline_markup", "%s: brackets next to code changed" % where)
    if src_marks or cand_marks:
        # Markers inside bare URLs: checked again as markers, the way the
        # renderers without autolinks read them.
        def with_marks(masked, marks):
            chars = list(masked)
            for k, ch in marks:
                chars[k] = ch
            return "".join(chars)
        _check_emphasis(src, with_marks(src_masked, src_marks), src_labels, src_maybe,
                        cand, with_marks(cand_masked, cand_marks), cand_labels, cand_maybe, where)
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
    r"^(?P<indent>[ \t]*)(?P<marker>[-+*]|[0-9]{1,9}[.)])(?:[ \t]+|$)"
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
# The label (at most 1000 UTF-8 bytes, see ``_label_ok``) is not only spaces,
# tabs and line ends; other whitespace counts as text in cmark-gfm.
_REFDEF_HEAD_RE = re.compile(
    r"[ ]{0,3}\[(?![ \t\n\r]*\])((?:\\[\s\S]|[^\[\]\\])+)\]:[ \t]*\n?[ \t]*")
_POINTY_DEST_RE = re.compile(r"<(?:\\.|[^<>\n\\])*>")
# A title: a backslash escapes the next character, and one more backslash
# may come right before the closing delimiter (a backslash, as in
# cmark-gfm). Each form matches one way only, so a title that never closes
# fails in linear time.
_TITLE = (r"(?:\"(?:\\[\s\S]|[^\"\\])*\\?\"|'(?:\\[\s\S]|[^'\\])*\\?'"
          r"|\((?:\\[\s\S]|[^()\\])*\\?\))")
# A title that starts and ends on one line.
_LINE_TITLE_RE = re.compile(_TITLE.replace(r"\s\S", r"^\n").replace(r"[^\"\\]", r"[^\"\\\n]")
                            .replace(r"[^'\\]", r"[^'\\\n]").replace(r"[^()\\]", r"[^()\\\n]"))
_ASCII_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_ASCII_SPACE = frozenset(" \t\n\x0b\x0c\r")


LABEL_SPACE = " \t\n\r"


def _label_ok(label):
    """Whether cmark-gfm takes ``label`` (between the brackets) as a link
    label: at most 1000 bytes of UTF-8, not only spaces, tabs and line
    ends (a vertical tab, form feed or no-break space is text)."""
    return bool(label.strip(LABEL_SPACE)) and len(label.encode("utf-8", "surrogatepass")) <= 1000


def _scan_destination(text, pos, balanced=False):
    """End of the link destination that starts at ``pos``, or None, as
    cmark-gfm scans one: inside angle brackets, or a bare run that ends at
    ASCII whitespace or at a closing parenthesis with none open. A backslash
    escapes ASCII punctuation; at most 32 parentheses may be open, and
    parentheses still open where the run ends are allowed (``balanced``
    rejects them, as markdown-it does)."""
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
    if balanced and depth:
        return None
    return i if i > pos else None


_MDIT_BAD_PROTO_RE = re.compile(r"(?:vbscript|javascript|file|data):")
_MDIT_GOOD_DATA_RE = re.compile(r"data:image/(?:gif|png|jpeg|webp);")
_MDIT_UNESCAPE_RE = re.compile(r"\\([!-/:-@\[-`{-~])|&([A-Za-z#][A-Za-z0-9]{1,31});")
_MDIT_NUMERIC_RE = re.compile(r"#(?:[xX]([0-9a-fA-F]{1,8})|([0-9]{1,8}))")


def _mdit_unescape(text):
    """``text`` with backslash escapes and character references decoded as
    markdown-it decodes a link destination before it validates it."""
    def decode(m):
        if m.group(1):
            return m.group(1)
        name = m.group(2)
        num = _MDIT_NUMERIC_RE.fullmatch(name)
        if num:
            code = int(num.group(1), 16) if num.group(1) else int(num.group(2))
            bad = (0xD800 <= code <= 0xDFFF or 0xFDD0 <= code <= 0xFDEF
                   or (code & 0xFFFF) in (0xFFFE, 0xFFFF) or code <= 0x08 or code == 0x0B
                   or 0x0E <= code <= 0x1F or 0x7F <= code <= 0x9F or code > 0x10FFFF)
            return m.group(0) if bad else chr(code)
        return html.entities.html5.get(name + ";", m.group(0))
    return _MDIT_UNESCAPE_RE.sub(decode, text)


def _mdit_scan_destination(text, pos, n):
    """End of the link destination that starts at ``pos`` as markdown-it
    scans one (reading ``text[:n]``), or None: inside angle brackets, or a
    bare run that ends at a space or control character, or at a closing
    parenthesis with none open, and closes every parenthesis it opens. A
    backslash escapes any next character but a space; before a line end it
    ends the destination with that line (markdown-it has not read the next
    line yet), and nothing more of the definition follows."""
    k = pos
    if k < n and text[k] == "<":
        k += 1
        while k < n:
            ch = text[k]
            if ch in "\n<" or (ch == "\\" and text[k + 1:k + 2] == "\n"):
                return None
            if ch == ">":
                return k + 1
            k += 2 if ch == "\\" and k + 1 < n else 1
        return None
    depth = 0
    while k < n:
        ch = text[k]
        if ch == " " or ch < " " or ch == "\x7f":
            break
        if ch == "\\" and k + 1 < n:
            if text[k + 1] == " ":
                break
            if text[k + 1] == "\n":
                return k + 2 if not depth else None
            k += 2
            continue
        if ch == "(":
            depth += 1
            if depth > 32:
                return None
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
        k += 1
    return k if k > pos and not depth else None


def _mdit_definition_end(text, pos, limit=None):
    """End of the definition whose destination starts at ``pos`` (after the
    line it ends on), as markdown-it reads it, or None when it does not
    (reading ``text[:limit]``): a destination (see _mdit_scan_destination)
    that, once escapes and character references are decoded, is not a
    "javascript:", "vbscript:", "file:" or "data:" link (images in data
    links excepted), then a title that ends at its closing quote (a
    backslash right before it escapes it) with only spaces after it on its
    line (else, unless the title is empty, the definition ends after the
    destination); without a title, only spaces may follow the destination
    on its line."""
    n = len(text) if limit is None else limit
    end = _mdit_scan_destination(text, pos, n)
    if end is None:
        return None
    dest = text[pos:end]
    if dest.startswith("<") and dest.endswith(">"):
        dest = dest[1:-1]
    dest = _mdit_unescape(dest).strip().lower()
    if _MDIT_BAD_PROTO_RE.match(dest) and not _MDIT_GOOD_DATA_RE.match(dest):
        return None
    if text[end - 1] == "\n":
        return end

    def line_end(k):
        nl = text.find("\n", k, n)
        return n if nl < 0 else nl + 1

    j = end
    while j < n and text[j] in " \t":
        j += 1
    if j < n and text[j] == "\n":
        j += 1
        while j < n and text[j] in " \t":
            j += 1
    if j > end and j < n and text[j] in "\"'(":
        close = ")" if text[j] == "(" else text[j]
        k = j + 1
        while k < n and text[k] != close:
            if text[k] == "\\" and k + 1 < n:
                k += 2
                continue
            if close == ")" and text[k] == "(":
                k = n
                break
            k += 1
        if k < n and not text[k + 1:line_end(k + 1)].strip(" \t\n"):
            return line_end(k + 1)
        if k < n and k == j + 1:
            # An empty title with more text after it: markdown-it does not
            # go back to the destination.
            return None
    if not text[end:line_end(end)].strip(" \t\n"):
        return line_end(end)
    return None


_MDIT_LIST_START_RE = re.compile(r"(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)")
_MDIT_UNDERLINE_RE = re.compile(r"(?:=+|-+)[ \t]*$")
_MDIT_BREAK_RE = re.compile(r"(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")


def _mdit_columns(line, base):
    """Indentation of a paragraph line relative to its container (``base``
    columns), as markdown-it measures it after a definition; a lazy line
    that does not reach the container counts from the line start."""
    ind = _indent_of(line)
    return ind - base if ind >= base else ind


def _mdit_interrupts(line, level):
    """Whether ``line`` ends a paragraph that markdown-it has open at quote
    depth ``level`` (else it continues it lazily): a quote marker that opens
    a quote, or (indented less than four columns) a heading, a fence, a
    thematic break, a list item with text that is a bullet or numbered 1,
    or an HTML block that may interrupt a paragraph; on a line with fewer
    quote markers, any list marker (markdown-it ends the quote there)."""
    depth, body = _quote_depth(line)
    if depth > level:
        return True
    expanded = _expand_indent(body)
    rest = expanded.lstrip(" ")
    if len(expanded) - len(rest) >= 4 or not rest:
        return False
    if depth < level and re.match(r"(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)", rest):
        return True
    return bool(ATX_RE.match(rest) or FENCE_RE.match(rest) or HR_RE.match(rest)
                or re.match(r"(?:[-+*]|1[.)])[ \t]+\S", rest)
                or _is_html_start(rest, interrupt=True))


def _mdit_opens_paragraph(text):
    """Whether the block markdown-it starts with ``text`` (measured from
    its container's content column) is, or ends in, a paragraph that a lazy
    line may continue: quote and list markers at its start open containers
    whose first block counts; a blank line, an empty list item, indented
    code, a heading, a thematic break, a fence, an HTML block or a
    definition is none."""
    for _ in range(32):
        rest = _expand_indent(text)
        ind = _indent_of(rest)
        if not rest.strip() or ind >= 4:
            return False
        rest = rest[ind:]
        if rest.startswith(">"):
            text = rest[2:] if rest[1:2] == " " else rest[1:]
            continue
        if ATX_RE.match(rest) or HR_RE.match(rest) or FENCE_RE.match(rest) or _is_html_start(rest):
            return False
        if rest.startswith("["):
            # (A definition, as markdown-it reads it on that line.)
            return _mdit_reading([rest], 0)[-1][0] == "paragraph"
        mark = re.match(r"(?:[-+*]|[0-9]{1,9}[.)])(?=[ \t]|$)", rest)
        if mark:
            inner = rest[mark.end():]
            if not inner.strip() or _indent_of(inner) > 4:
                return False
            text = inner.lstrip(" ")
            continue
        return True
    return False


def _line_shape(text):
    """A coarse kind for the first line of a block (after its containers):
    blank, quote, list item, heading, fence, thematic break, HTML or text."""
    rest = _expand_indent(text).lstrip(" ")
    if not rest:
        return "blank"
    if rest.startswith(">"):
        return "quote"
    if FENCE_RE.match(rest):
        return "fence"
    if HR_RE.match(rest):
        return "break"
    if re.match(r"(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)", rest):
        return "item"
    if ATX_RE.match(rest):
        return "heading"
    if _is_html_start(rest):
        return "html"
    return "text"


def _column_bucket(ind, cols):
    """Where a line indented ``ind`` columns stands against the content
    columns ``cols`` of some containers open there (ascending, the last the
    deepest): how many of them it reaches, and, when it reaches the last,
    whether it is indented four columns past it (other containers may lie
    between the others)."""
    reach = sum(1 for c in cols if c <= ind)
    return reach, (ind - cols[-1] >= 4) if reach == len(cols) else None


def _mdit_lazy_breaks(body):
    """Whether ``body`` (a line past its quote markers, indented less than
    the content column of the list item whose paragraph markdown-it has
    open) ends that paragraph: markdown-it counts the indentation from that
    column, so a heading, fence, thematic break, quote marker or HTML block
    that may interrupt a paragraph does so at any indentation there."""
    rest = _expand_indent(body).lstrip(" ")
    return bool(rest) and bool(ATX_RE.match(rest) or FENCE_RE.match(rest) or HR_RE.match(rest)
                               or rest.startswith(">") or _is_html_start(rest, interrupt=True))


def _mdit_ends_paragraph(line, level, base, marker_indent=None):
    """Whether markdown-it surely ends at ``line`` a paragraph it has open at
    quote depth ``level`` in a container whose content column is ``base``
    (None when that is not known): a line that is blank once its quote
    markers are removed, a line inside the container that starts a block
    there (such as a nested list item or a heading), or a list item outside
    the paragraph's list item (whose marker is indented ``marker_indent``
    columns) less than four columns past that marker, which ends the item
    whatever its number and even when it is empty."""
    depth, body = _quote_depth(line)
    if not body.strip():
        return True
    if base is None or depth != level:
        return False
    body = _expand_indent(_strip_quote(line, level))
    ind = _indent_of(body)
    if ind >= base:
        return _mdit_interrupts(_past_container(body, base), 0)
    return (marker_indent is not None and ind - marker_indent < 4
            and bool(re.match(r"(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)", body[ind:])))


_LOOSE_LABEL_RE = re.compile(r"\[((?:[^\[\]\\]|\\.)*)\]:", re.S)


def _doc_resolver(text):
    """_doc_label_resolver for ``text``, or one that resolves no label where
    no "]:" is in it."""
    return _doc_label_resolver(text) if "]:" in text else (lambda label, cm_valid=True: "no")


def _doc_label_resolver(text):
    """A ``resolve`` for _inline_constructs from the labels anything in
    ``text`` may define (every "[label]:"): "maybe" for those, "no" for
    any other label."""
    found = set()
    # (Also with the quote markers removed: a label may continue on a
    # quoted line.)
    bare = "\n".join(_quote_depth(line)[1] for line in text.split("\n")) if ">" in text else ""
    for source in (text, bare):
        for m in _LOOSE_LABEL_RE.finditer(source):
            found.add(normalize_label(m.group(1)))
            found.add(("md", mdit_label_key(m.group(1))))

    def resolve(label, cm_valid=True):
        return ("maybe" if normalize_label(label) in found or ("md", mdit_label_key(label)) in found
                else "no")
    return resolve


def _spanned_lines(lines, ks, resolve=None):
    """Where the lines ``ks`` (indexes into ``lines``, a paragraph's lines)
    start inside a code span, raw HTML or an inline link's destination and
    title that opened on an earlier line (read as _inline_constructs reads
    them, in every reading): a tuple of (span number, line number inside
    the span), so rewrapping the prose around a span keeps it."""
    if not ks:
        return ()
    text = "\n".join(lines)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    found = []
    # (Every reading, with a choice the text does not meet read as not
    # taken: see _expanded_readings.)
    for reading, constructs in _expanded_readings(_inline_readings(text, resolve)):
        spans = [(s, e) for kind, s, e, _ in constructs if kind in ("code", "html", "linktail")]
        heads = [s for s, _ in spans]
        out = []
        for k in ks:
            at = starts[k]
            x = bisect.bisect_left(heads, at) - 1
            if x >= 0 and spans[x][0] < at < spans[x][1]:
                out.append((x, k - (bisect.bisect_right(starts, spans[x][0]) - 1)))
        if not reading:
            found = main = out
        elif out != main:
            # A text that reads in two ways (see _inline_constructs): the
            # lines inside the spans of each reading.
            found = found + [("reading", reading, tuple(out))]
    return tuple(found)


def _mdit_reading(lines, base, continuing=None, quote_lazy=frozenset(), col_lines=None, depths=None,
                  outer_cols=(), depth_cols=()):
    """How markdown-it reads the lines of one cmark-gfm paragraph (inside a
    container ``base`` columns deep): a list of line ranges (kind, first,
    last, extra), ``last`` excluded, covering the lines in order. Kinds:
    "definition" (extra: the label as markdown-it matches it), "code",
    "break", "item" (an empty list item), "listitem" (a list item with
    text, extra: its marker; the text is prose), "html", "heading" (a
    paragraph that ends at a setext underline, its last line), "paragraph"
    (extra: whether markdown-it reads it outside the paragraph's container)
    and "unknown" (a list item read no further). ``continuing`` is the kind
    of a block markdown-it opened before these lines and continues on them:
    "paragraph", or "html" and "unknown" (which take all of them; the HTML
    block also runs past the paragraph, see parse_blocks). ``quote_lazy``
    holds the indexes of lazy lines outside the paragraph's quotes, and
    ``depths`` the number of quote markers on each line; ``col_lines`` are
    the lines with their quote markers removed and tabs expanded at their
    true columns, for measuring indentation; ``outer_cols`` the content
    columns of the list items open at the paragraph's quote depth, and
    ``depth_cols`` those at each quote depth (from 0).

    markdown-it reads a definition only at the start of a block, and starts
    a new block after each one, so a line that only continues the paragraph
    to cmark-gfm can start indented code, a thematic break, a list item that
    cannot interrupt a paragraph (an empty one, or a number other than 1) or
    an HTML block of the seventh kind there. A list item or a thematic break
    also ends the lines a definition may continue on. A lazy line after a
    definition is read outside the paragraph's quote or list item; a quote
    marker after it opens a new quote (also one that does not reach the
    paragraph's own depth)."""
    n = len(lines)
    if continuing in ("html", "unknown"):
        return [(continuing, 0, n, None)]
    col_lines = lines if col_lines is None else col_lines
    if depths is None:
        depths = [0 if k in quote_lazy else 1 for k in range(n)]
    stripped = [line.lstrip(" \t") for line in lines]
    bodies = [_expand_indent(line).lstrip(" ") for line in lines]
    cols = [_mdit_columns(line, base) for line in col_lines]
    list_lazy = [_indent_of(line) < base for line in col_lines]
    text = "\n".join(stripped)
    starts = [0]
    for line in stripped:
        starts.append(starts[-1] + len(line) + 1)
    # The first line after each line that ends a definition's lines.
    next_end = [n] * (n + 1)
    for k in range(n - 1, -1, -1):
        ends = k > 0 and k not in quote_lazy and cols[k] < 4 and bool(
            _MDIT_LIST_START_RE.match(bodies[k]) or _MDIT_BREAK_RE.match(bodies[k]))
        next_end[k] = k if ends else next_end[k + 1]
    # The first lazy line (of either kind, or outside the paragraph's
    # quotes) from each line on.
    next_lazy = [n] * (n + 1)
    next_qlazy = [n] * (n + 1)
    for k in range(n - 1, -1, -1):
        next_lazy[k] = k if (k in quote_lazy or list_lazy[k]) else next_lazy[k + 1]
        next_qlazy[k] = k if k in quote_lazy else next_qlazy[k + 1]
    # For each depth of a lazy line, the first line from each line on with
    # more quote markers: markdown-it reads a lazy line after a definition
    # outside the quote, at its own depth, and a line with more quote
    # markers than that opens a new quote.
    next_deeper = {}
    for d in {depths[k] for k in quote_lazy}:
        arr = [n] * (n + 1)
        for k in range(n - 1, -1, -1):
            arr[k] = k if depths[k] > d else arr[k + 1]
        next_deeper[d] = arr

    def inside_from(p):
        # The line after ``p`` (a lazy line) where a new quote opens.
        return next_deeper[depths[p]][p + 1]

    # markdown-it ends nested quotes at a lazy line that misses two or more
    # of them and is indented four columns past the quotes it reaches, when
    # the line looks like a block start (a heading, a fence, a thematic
    # break, a list item, or an HTML block that may interrupt a paragraph):
    # it reads that line as indented code outside them. The lines from there
    # on are read no further.
    # markdown-it also continues a quote at a quote marker after any
    # indentation, so a lazy line indented four columns that starts with
    # one may hold quote markers to it (it is text to cmark-gfm).
    cut = n
    for q in range(1, n):
        if depths[q] < depths[0] and _indent_of(col_lines[q]) >= 4:
            b = bodies[q]
            if b.startswith(">") or depths[q] <= depths[0] - 2 and (
                    ATX_RE.match(b) or FENCE_RE.match(b) or _MDIT_BREAK_RE.match(b)
                    or _MDIT_LIST_START_RE.match(b) or _is_html_start(b, interrupt=True)):
                cut = q
                break
    # markdown-it measures a lazy line's indentation from the list item's
    # content column, so a lazy line indented four columns from its start
    # but less than that column, that looks like a block start, ends the
    # paragraph and the list item there (cmark-gfm reads it as text): it is
    # read no further either.
    for q in range(1, cut):
        if q not in quote_lazy and list_lazy[q] and _indent_of(col_lines[q]) >= 4:
            b = bodies[q]
            if (b.startswith(">") or ATX_RE.match(b) or FENCE_RE.match(b) or _MDIT_BREAK_RE.match(b)
                    or _MDIT_LIST_START_RE.match(b) or _is_html_start(b, interrupt=True)):
                cut = q
                break

    def underline(q, where, level):
        # ``where``: "quote" or "list" for a paragraph markdown-it reads
        # outside the paragraph's quote (at depth ``level``) or list item,
        # else None.
        if not _MDIT_UNDERLINE_RE.match(bodies[q]):
            return False
        if where == "quote":
            # (From the content column of the list item open at that depth
            # that markdown-it reads the paragraph in.)
            ind = _indent_of(col_lines[q])
            return depths[q] == level and quote_col <= ind < quote_col + 4
        if where == "list":
            # (From the content column of the list item markdown-it still
            # reads the paragraph in: a line short of it is lazy text.)
            ind = _indent_of(col_lines[q])
            return q not in quote_lazy and own_col <= ind < own_col + 4
        return q not in quote_lazy and not list_lazy[q] and cols[q] < 4

    def plain(q, p):
        # A line that continues the text of the paragraph of the list item
        # at line ``p``: one that does not end it (a list item, a thematic
        # break, a quote marker, a heading, a fence or an HTML block that
        # may interrupt a paragraph) or underline it.
        b = bodies[q]
        return not (depths[q] > depths[p] or item_marker_ends(q) or _MDIT_UNDERLINE_RE.match(b)
                    or _MDIT_BREAK_RE.match(b) or b.startswith(">") or ATX_RE.match(b)
                    or FENCE_RE.match(b) or _is_html_start(b, interrupt=True))

    def item_marker_ends(q):
        # Whether a list marker at line ``q`` ends the paragraph of the list
        # item markdown-it opened (``item``: its marker's indentation and
        # content column): outside that column any marker does (unless it
        # is indented four columns past the item's marker, which is text);
        # inside it only one that may interrupt a paragraph (a bullet or a
        # number 1 with text, less than four columns past the column).
        m = _MDIT_LIST_START_RE.match(bodies[q])
        if not m:
            return False
        if item is None:
            return True
        ind = _indent_of(col_lines[q])
        if ind < item[1]:
            return ind - item[0] < 4
        mark = m.group(0).strip(" \t")
        return (ind - item[1] < 4 and bool(bodies[q][m.end():].strip(" \t"))
                and (mark in "-+*" or int(mark[:-1]) == 1))

    def open_item(p, mark, gap, text):
        # The indentation of a list item's marker and its content column
        # (one column after the marker when the item has no text or more
        # than four spaces after it).
        ind = _indent_of(col_lines[p])
        return (ind, ind + len(mark) + (len(gap) if text and 1 <= len(gap) <= 4 else 1))

    out = []
    p = 0
    # Whether markdown-it has closed the paragraph's list item or quote (it
    # read a block outside them), and whether it opened a list item of its
    # own (whose content an indented line may continue).
    closed = False
    # (The least indentation of a line markdown-it read outside the
    # paragraph's list item: the list items it closed there stay closed,
    # also for a later line indented to them.)
    closed_ind = None
    md_list = False
    # The list item markdown-it opened last and still reads (see open_item).
    item = None
    while p < n:
        if p >= cut:
            out.append(("unknown", p, n, None))
            break
        body = bodies[p]
        outside = p in quote_lazy
        closed = closed or bool(p and (outside or list_lazy[p]))
        if item is not None and (outside or _indent_of(col_lines[p]) < item[1]):
            # (A block that starts short of the item's content column closes
            # it.)
            item = None
        if p and list_lazy[p] and not outside:
            ind_p = _indent_of(col_lines[p])
            closed_ind = ind_p if closed_ind is None else min(closed_ind, ind_p)
        # Indented code or HTML that starts inside the paragraph's
        # containers ends at a lazy line; outside the quote it ends where
        # a quote marker opens a new quote.
        reach = min(inside_from(p) if outside else next_lazy[p + 1], cut)
        if closed and _indent_of(col_lines[p]) >= 4:
            # A line markdown-it reads after it closed the paragraph's list
            # item, indented four columns from its start (or from a quote
            # marker that opens a new quote): indented code, unless an outer
            # list item it is still in takes that indentation.
            out.append(("unknown", p, n, None))
            break
        if p and cols[p] >= 4:
            if md_list:
                out.append(("unknown", p, n, None))
                break
            q = p + 1
            while q < reach and cols[q] >= 4:
                q += 1
            out.append(("code", p, q, None))
            p = q
            continue
        if p and _MDIT_BREAK_RE.match(body):
            out.append(("break", p, p + 1, None))
            p += 1
            continue
        marker = _MDIT_LIST_START_RE.match(body) if p else None
        if marker:
            mark = marker.group(0).rstrip(" \t")
            rest = body[len(mark):]
            # (The indentation of the marker sets the item's content column
            # too: it is structure.)
            at = "%d:" % _indent_of(col_lines[p])
            if not rest.strip(" \t") and (p + 1 == n or cols[p + 1] == 0):
                # An empty item ends at the next line unless that line is
                # indented into it.
                md_list = True
                item = open_item(p, mark, "", False)
                out.append(("item", p, p + 1, None))
                p += 1
                continue
            inner = rest.lstrip(" \t")
            gap = rest[:len(rest) - len(inner)]
            heading = ATX_RE.match(inner) if inner and "\t" not in gap and len(gap) <= 4 else None
            if heading:
                # A heading in the list item: the list and heading markers
                # (with a closing sequence) are structure, its text prose.
                closing = re.search(r"[ \t](#+)[ \t]*$", inner) if heading.group(2) is not None else None
                md_list = True
                item = open_item(p, mark, gap, True)
                out.append(("listitem", p, p + 1, "%s%s%s%s|%s" % (at, mark, gap, heading.group(1),
                                                                 closing.group(1) if closing else "")))
                p += 1
                continue
            if (inner and "\t" not in gap and len(gap) <= 4
                    and not inner.startswith((">", "<", "["))
                    and not (_MDIT_LIST_START_RE.match(inner) or ATX_RE.match(inner)
                             or FENCE_RE.match(inner) or _MDIT_BREAK_RE.match(inner))):
                # A list item whose text starts a paragraph (one to four
                # spaces after the marker; more start indented code): its
                # paragraph continues over the plain lines after it
                # (prose); a further marker starts the next item.
                item = open_item(p, mark, gap, True)
                q = p + 1
                while q < cut and plain(q, p):
                    q += 1
                md_list = True
                # (The marker with the spaces after it: they set the item's
                # content column.)
                out.append(("listitem", p, q, at + mark + gap))
                if q < cut and _MDIT_UNDERLINE_RE.match(bodies[q]):
                    # It may underline the item's text.
                    out.append(("unknown", q, n, None))
                    break
                p = q
                continue
            out.append(("unknown", p, n, None))
            break
        if p and _is_html_start(body) and not _is_html_start(body, interrupt=True):
            # Outside the quote it runs to the next blank line; after
            # markdown-it closed the paragraph's list item, over the lines
            # that missed the item too.
            q = cut if outside else (min(next_qlazy[p + 1], cut) if closed else reach)
            out.append(("html", p, q, None))
            p = q
            continue
        t = min(next_end[p + 1], inside_from(p) if outside else n, cut)
        limit = starts[t] - 1
        head = None if continuing and not p else _REFDEF_HEAD_RE.match(text, starts[p], limit)
        key = mdit_label_key(head.group(1)) if head else ""
        end = _mdit_definition_end(text, head.end(), limit) if key else None
        if end is None:
            # A paragraph, up to the first setext underline in its own
            # container (then a heading, and new blocks after it). Outside
            # the quote it also ends where a quote marker opens a new quote.
            q = p + 1
            stop = min(inside_from(p) if outside else n, cut)
            where = "quote" if outside else ("list" if closed else None)
            p_ind = _indent_of(col_lines[p]) if closed_ind is None else min(_indent_of(col_lines[p]), closed_ind)
            own_col = max((c for c in outer_cols if c <= p_ind), default=0)
            quote_col = (max((c for c in depth_cols[depths[p]] if c <= _indent_of(col_lines[p])), default=0)
                         if outside and depths[p] < len(depth_cols) else 0)
            # (Inside a list item markdown-it opened, a list marker short of
            # the item's content column ends the paragraph, and an underline
            # counts from that column.)
            in_item = item is not None and where is None
            ended = interrupted = False
            while q < stop:
                if in_item and item_marker_ends(q) and _indent_of(col_lines[q]) < item[1]:
                    ended = True
                    break
                if ((_MDIT_UNDERLINE_RE.match(bodies[q]) and q not in quote_lazy
                     and item[1] <= _indent_of(col_lines[q]) < item[1] + 4)
                        if in_item else underline(q, where, depths[p])):
                    break
                if (in_item and q not in quote_lazy and _indent_of(col_lines[q]) >= item[1]
                        and _mdit_interrupts(_expand_indent(col_lines[q])[item[1]:], 0)):
                    # (A line that starts a block inside the item, counted
                    # from its content column, such as a nested list item
                    # that cmark-gfm reads as indented text: the walk reads
                    # no further.)
                    interrupted = True
                    break
                q += 1
            if interrupted:
                out.append(("paragraph", p, q, False))
                out.append(("unknown", q, n, None))
                break
            if ended:
                out.append(("paragraph", p, q, False))
                p = q
                continue
            if q < stop:
                out.append(("heading", p, q + 1, None))
                p = q + 1
                continue
            if where is not None and stop == cut < n:
                # (Where markdown-it reads the paragraph outside the quote or
                # list item, the line the cut found may continue it lazily:
                # the paragraph is read no further either.)
                out.append(("unknown", p, n, None))
                break
            # (Also after an earlier line markdown-it read outside the
            # paragraph's container: it does not reopen that container.)
            out.append(("paragraph", p, stop, bool(p and (outside or list_lazy[p] or closed))))
            if stop == n:
                break
            p = stop
            continue
        last = max(p + 1, min(bisect.bisect_left(starts, end + (end == limit)), t))
        out.append(("definition", p, last, key))
        p = last
    return out


def _cmark_title_end(text, j):
    """End of the link title that starts at ``text[j]`` as cmark-gfm's
    scanner matches it, or None. The scanner takes the longest match: a
    closing delimiter right after a backslash may also be an escaped one
    inside the title, so the title runs to the first closing delimiter
    without a backslash before it (or else the last one with one); an
    opening parenthesis without a backslash before it ends a parenthesized
    title's reach."""
    n = len(text)
    if j >= n or text[j] not in "\"'(":
        return None
    opener = text[j]
    close = ")" if opener == "(" else opener
    last = None
    for k in range(j + 1, n):
        ch = text[k]
        if ch == "\x00" or (opener == "(" and ch == "(" and text[k - 1] != "\\"):
            break
        if ch == close:
            if text[k - 1] != "\\":
                return k + 1
            last = k + 1
    return last


def _match_definition(text, pos=0, kept=None):
    """End of the definition at ``pos`` in ``text`` (after the newline
    that ends it), or None when it is not one, as cmark-gfm reads it: a
    title (see _cmark_title_end) must be followed by only spaces on its
    line, or else the definition ends after the destination, which then
    must end its line. cmark-gfm keeps such a title on the definition all
    the same (its lines are also paragraph text); it is appended to ``kept``
    when given, as its start and end in ``text``."""
    m = _REFDEF_HEAD_RE.match(text, pos)
    if not m or not _label_ok(m.group(1)):
        return None
    end = _scan_destination(text, m.end())
    if end is None:
        return None
    n = len(text)

    def line_end_after_spaces(k):
        while k < n and text[k] in " \t":
            k += 1
        if k == n:
            return n
        return k + 1 if text[k] == "\n" else None

    k = end
    while k < n and text[k] in " \t":
        k += 1
    if k < n and text[k] == "\n":
        k += 1
        while k < n and text[k] in " \t":
            k += 1
    title_end = _cmark_title_end(text, k) if k > end else None
    if title_end is not None:
        after = line_end_after_spaces(title_end)
        if after is not None:
            return after
    after = line_end_after_spaces(end)
    if after is not None and title_end is not None and kept is not None:
        kept.append((k, title_end))
    return after


# The label of a definition, which may continue over lines.
REFDEF_LABEL_RE = re.compile(r"[ ]{0,3}\[((?:\\[\s\S]|[^\[\]\\])+)\]:")
# A line in a protected region or footnote that may be a definition: the
# label after any quote or list markers.
LOOSE_REFDEF_RE = re.compile(
    r"^(?:[ \t>]|(?:[-+*]|[0-9]{1,9}[.)])(?=[ \t]))*\[(?!\^)((?:\\[\s\S]|[^\[\]\\])+)\]:", re.M)


def _loose_labels(text, first_only=False):
    """The labels of the definition-like lines in ``text`` (see
    LOOSE_REFDEF_RE; with ``first_only``, only one at its start), each also
    without the quote markers and indentation at the start of its
    continuation lines (a label that continues on a line inside a quote)."""
    found = []
    for m in ([LOOSE_REFDEF_RE.match(text)] if first_only else LOOSE_REFDEF_RE.finditer(text)):
        if m:
            found.append(m.group(1))
            bare = re.sub(r"\n[ \t>]*", "\n", m.group(1))
            if bare != m.group(1):
                found.append(bare)
    return found


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
# cannot interrupt a paragraph. A tag whose quoted attribute value is still
# open at the line end is not complete: both renderers read a paragraph
# with raw inline HTML there.
HTML_LINE_TAG_RE = re.compile(
    r"^[ ]{0,3}(?:" + HTML_OPEN_TAG + "|" + HTML_CLOSE_TAG + r")[ \t]*$")


class Block(object):
    __slots__ = ("kind", "attrs", "raw", "units", "line", "ref", "md_label", "md_units")

    def __init__(self, kind, attrs, raw, units, line, ref=None):
        self.kind = kind
        self.attrs = attrs
        self.raw = raw
        self.units = units
        self.line = line
        # For a reference definition: (normalized label, whether the parser
        # read the whole definition, the label as markdown-it matches it or
        # "" when markdown-it does not take the definition); for a footnote
        # definition: how its content ends. Not part of the comparison.
        self.ref = ref
        # For a paragraph that starts with a definition only markdown-it
        # takes: its label as markdown-it matches it. Not compared.
        self.md_label = None
        # The text of a paragraph markdown-it reads past the end of this one
        # (over the blocks cmark-gfm starts after it), compared as prose.
        self.md_units = None

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


def _md_blank(line):
    """Whether ``line`` is blank to the renderers: only spaces and tabs (a
    carriage return before the line feed ends the line). Python's
    ``str.strip`` also removes no-break spaces, form feeds and the like,
    which are text to them."""
    if line.endswith("\r"):
        line = line[:-1]
    return not line.strip(" \t")


def _odd_blank(line):
    """Whether the guard's block reading, which takes any whitespace as
    blank or as indentation, may part from the renderers' on ``line``: past
    its quote markers, list markers and indentation, its text starts or
    ends with whitespace other than spaces and tabs (a no-break space, a
    form feed, an ideographic space), which is text to the renderers, or
    it holds a carriage return that is not followed by a line feed (a line
    ending to the renderers)."""
    if line.endswith("\r"):
        line = line[:-1]
    if "\r" in line:
        return True
    rest = re.sub(r"^(?:[ \t>]|(?:[-+*]|[0-9]{1,9}[.)])(?=[ \t]|$))*", "", line).rstrip(" \t")
    return bool(rest) and (rest[0].isspace() or rest[-1].isspace())


def _fence_opener(text):
    """The fence ``text`` opens (character and length), or None: a backtick
    fence's info string holds no backtick."""
    m = FENCE_RE.match(text)
    if m and (m.group(2)[0] == "~" or "`" not in m.group(3)):
        return m.group(2)[0], len(m.group(2))
    return None


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
MAYBE_REFDEF_LINE_RE = re.compile(r"^[ \t>]*(?:(?:[-+*]|[0-9]{1,9}[.)])[ \t]+)*\[(?!\^)")


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
    if not _label_ok(m.group(1)):
        return True
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
    if after == rest or after[0] not in "\"'(":
        return True
    # A title that closes on the line must end it (a title that continues
    # on the next line is read with the whole paragraph).
    title = _LINE_TITLE_RE.match(after)
    return bool(title) and bool(after[title.end():].strip(" \t"))


def _read_definitions(content, parsed_only=False, lazy=None):
    """Read the reference definitions at the start of a paragraph whose
    lines are ``content`` (leading whitespace is ignored), as CommonMark
    does when the paragraph closes. Return a list of (first, end, label,
    parsed) entries in line indices, the index of the first line after
    them, and the titles cmark-gfm keeps from the lines after a definition
    that it reads as text (by the definition's first line). A line that starts like a definition this parser cannot read is
    kept with the lines up to the next one that starts a definition, as an
    unparsed definition, unless it can only be text (``_not_a_definition``),
    where reading stops. With ``parsed_only``, reading stops there instead
    (cmark-gfm checks a setext underline against the definitions it can
    read; a line it cannot read as one is paragraph text). ``lazy`` maps
    the index of a lazy line whose leading whitespace cmark-gfm keeps to
    "text" (no definition starts there: reading stops) or "maybe" (an open
    list item may take the whitespace: the definition only possibly
    counts)."""
    lazy = lazy or {}
    parts = [line.lstrip(" \t") for line in content]
    out = []
    k = 0
    # After a definition this parser cannot read, cmark-gfm may have
    # stopped reading definitions: the ones after it only possibly count.
    unsure = False
    kept = {}
    joined = "\n".join(parts)
    starts = [0]
    for part in parts:
        starts.append(starts[-1] + len(part) + 1)
    while k < len(parts):
        if FOOTNOTE_DEF_RE.match(parts[k]) or not REFDEF_START_RE.match(parts[k]):
            break
        how = lazy.get(k)
        if how == "text":
            break
        kept_title = []
        dm = _match_definition(joined, starts[k], kept_title)
        if kept_title:
            a, b = kept_title[0]
            # The title, with the leading whitespace cmark-gfm keeps on the
            # lazy lines it continues on.
            la = bisect.bisect_right(starts, a) - 1
            lb = bisect.bisect_right(starts, b - 1) - 1
            kept[k] = joined[a:b] + "".join("\x00" + content[x][:len(content[x]) - len(parts[x])]
                                            for x in range(la + 1, lb + 1) if x in lazy)
        lm = REFDEF_LABEL_RE.match(joined, starts[k])
        label = lm.group(1) if lm else None
        if dm is not None:
            end = bisect.bisect_right(starts, dm - 1)
            out.append((k, end, label, not unsure and not how))
            unsure = unsure or bool(how)
            k = end
            continue
        if parsed_only or not REFDEF_RE.match(parts[k]) or _not_a_definition(parts[k]):
            break
        end = k + 1
        while (end < len(parts) and not REFDEF_RE.match(parts[end])
               and not FOOTNOTE_DEF_RE.match(parts[end])):
            end += 1
        out.append((k, end, label, False))
        unsure = True
        k = end
    return out, k, kept


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


def parse_blocks(text, spec_blank_items=False, inner=False, _budget=None, _md_lines=None, _resolve=None):
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
    # polish:on marker is cut in both copies; ``src_lines`` keeps every line
    # as written.
    orig_lines = text.split("\n")
    src_lines = list(orig_lines)
    raw_spans = None
    lines = [_expand_structure(line) for line in orig_lines]
    n = len(lines)
    # (Which reference labels the document may define, for the span records
    # and for markdown-it's emphasis: a nested parse takes the document's.)
    span_resolve = _resolve or _doc_resolver(text)
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
        inner_blocks = parse_blocks("\n".join(content), spec_blank_items, inner=True, _budget=budget,
                                    _resolve=span_resolve)
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
        has_html = any(next(_iter_html(_strip_quote(lines[r], quote), loose=True), None) for r in rows)
        # markdown-it has no tables: it reads the rows as paragraph text,
        # with the paragraph right before them and the lines after them
        # that do not end its paragraph (lazy lines after a quoted table, a
        # list item numbered other than 1, another table). A row where a code span, raw
        # HTML, a link, math or emphasis it reads there crosses a cell or a
        # row (or follows a cell that leaves a "[" open) is kept byte for
        # byte, and where that reaches the paragraph before the table or
        # the lazy lines after it, the lines from there are kept too (see
        # md_list_freeze).
        raw_rows = set()
        sep_raw = False
        before = []
        if blocks and blocks[-1].kind == "paragraph" and \
                blocks[-1].line + blocks[-1].raw.count("\n") == i:
            before = [_strip_quote(lines[x], quote) for x in range(blocks[-1].line - 1, i)]
        lazy = []
        if not inner and j < n and lines[j].strip() and not _mdit_interrupts(lines[j], quote):
            x = j
            while x < n and lines[x].strip() and not _mdit_interrupts(lines[x], quote):
                text = _strip_quote(lines[x], _quote_depth(lines[x])[0])
                if depth > 0 and _indent_of(text) < base and LIST_MARKER_START_RE.match(text):
                    # (A list item of the table's list, or of one around
                    # it, ends the item's paragraph to markdown-it.)
                    break
                lazy.append(text)
                x += 1
        row_texts = [_strip_quote(lines[i], quote), _strip_quote(lines[i + 1], quote)] + \
            [_strip_quote(lines[r], quote) for r in rows[1:]]
        touched = _md_table_crosses(before, row_texts, lazy, span_resolve)
        if touched:
            b = len(before)
            if min(touched) < b and not inner:
                md_list_freeze.append(blocks[-1].line - 1)
            if max(touched) >= b + len(row_texts) and not inner:
                md_list_freeze.append(j)
            raw_rows = {rows[0]} if b in touched else set()
            raw_rows.update(rows[t] for t in range(1, len(rows)) if b + 1 + t in touched)
            sep_raw = b + 1 in touched
        for idx, r in enumerate(rows):
            row_body = _strip_quote(lines[r], quote)
            cells = _split_cells(row_body)
            if has_html or r in raw_rows:
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
                # (A delimiter row inside a code span markdown-it reads
                # there is kept as written.)
                blocks.append(Block("table_sep", attrs(), sep if sep_raw else sep_norm, [], i + 2))
        return j

    # Paragraph lines that head a table and are read with the paragraph's
    # containers, by line index: (quote, depth, base, ancestry, mark), where
    # mark is "lazy", "indented" or "".
    table_headers = {}
    # The line at which a paragraph markdown-it opened on a setext
    # underline continues (see below), or -1.
    md_open = -1
    # The content column of the list item markdown-it reads the paragraph
    # it continues there in (None when not known): it measures the lines'
    # indentation from it, not from the item cmark-gfm opens.
    md_open_base = None
    # (line, quote depth, content column, end marker) where an HTML block
    # markdown-it opened inside a paragraph continues past it, up to a blank
    # line or the end of the paragraph's containers (both 0 when markdown-it
    # had closed them: up to a blank line, or to the end marker of raw HTML
    # of types 1 to 5).
    md_raw_from = []
    # (line, end) where markdown-it's reading of a paragraph stops being
    # known before its end: a block it reads there may run on past it.
    md_unknown_from = []
    md_item_open = []
    # The first line of each list markdown-it opens in a paragraph cmark-gfm
    # reads (a list item numbered other than 1 right after a definition):
    # kept byte for byte from there (see below).
    md_list_freeze = []
    # (Display math the renderers read on into: see the math blocks.)
    math_skip = -1
    math_chain = None
    # (line, quote depth) where a paragraph markdown-it keeps open continues
    # lazily past the end of cmark-gfm's paragraph.
    md_lazy_from = []
    # Where markdown-it's indented code reaches the end of cmark-gfm's
    # paragraph: the line after it, its quote depth and the column the code
    # is measured from.
    md_code_tail = []
    # (first line, line) of a paragraph cmark-gfm ends at a line that
    # markdown-it reads as a lazy continuation of it.
    md_lazy_run = []
    # (Lines of a paragraph cmark-gfm reads that markdown-it reads as
    # another kind, see ``over`` below.)
    over_line = [False] * n
    # (Lines markdown-it reads in the paragraph of a footnote definition
    # that cmark-gfm has ended, see the footnote definitions below.)
    fn_line = [False] * n
    # (The first line of a paragraph markdown-it reads right before a range
    # it may read in any way, by the lazy run of that range: the paragraph
    # may continue into the range, so the two are also compared as one
    # unit.)
    md_unit_pre = {}

    def add_run(entry):
        # A lazy run, with the content columns of the list items cmark-gfm
        # has open at its quote depth there (see md_lazy_run below).
        level = entry[2]
        md_lazy_run.append(entry + (tuple(c for _, c in level_stacks[level]) if level < len(level_stacks) else (),))
    # Where markdown-it reads lines of a paragraph outside the paragraph's
    # containers: the first line and the shape of its reading.
    md_shapes = []
    # (line, quote depth, content column) of the outermost container that
    # markdown-it may have closed in a paragraph before the line (it read a
    # line of the paragraph outside it): a list item at that quote depth, or
    # the quote itself (column 0). markdown-it reads the rest of cmark-gfm's
    # container outside it too.
    md_closed_from = []

    def item_marker(level, col):
        # The indentation of the marker of the open list item at quote
        # depth ``level`` whose content column is ``col``, or None.
        stack = level_stacks[level] if level < len(level_stacks) else []
        return next((ind for ind, c in reversed(stack) if c == col), None)

    def md_item_continues(j, md_level):
        """Whether markdown-it's paragraph at quote depth ``md_level``
        continues over line ``j``, where cmark-gfm opens a list item that
        cannot interrupt a paragraph (a number other than 1, or an empty
        one) at the same depth (a list item with fewer or more quote markers
        ends markdown-it's quote and opens there too). The lines cmark-gfm
        then reads inside that item are markdown-it's top-level lines."""
        jq = _quote_depth(lines[j])[0]
        jbody = _strip_quote(lines[j], jq).lstrip(" ")
        jm = re.match(r"([0-9]{1,9})[.)](?=[ \t]|$)|[-+*](?=[ \t]*$)", jbody)
        if not (jm and jq == md_level and (not jm.group(1) or int(jm.group(1)) != 1
                                           or not jbody[jm.end():].strip())):
            return False
        jrest = jbody[jm.end():]
        jgap = len(jrest) - len(jrest.lstrip(" "))
        jcol = (_indent_of(_strip_quote(lines[j], jq)) + jm.end()
                + (jgap if 1 <= jgap <= 4 and jrest.strip() else 1))
        md_closed_from.append((j + 1, jq, jcol))
        return True

    while i < n:
        if math_chain is not None and i > math_chain[0]:
            # (The line after a chain of math blocks was read as another
            # block: the renderers read it on in the chain's paragraph.)
            md_list_freeze.append(math_chain[0])
            math_chain = None
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
            # A raw block (a fence, an HTML block, indented code, a
            # definition) that starts inside the region, or on the marker's
            # line with text before the marker, and still runs at the
            # polish:on marker for the renderers, to whom the markers are
            # plain HTML comments, takes the marker as its own text: the
            # region is kept to that block's end, read by this parser with
            # the markers renamed to ordinary comments of the same length.
            if raw_spans is None:
                # (The raw block covering each line, as (first, last).)
                raw_spans = [None] * n
                for b in parse_blocks(re.sub(r"(<!--\s*polish):(o(?:n|ff)\s*-->)", r"\1-\2", text),
                                      spec_blank_items, inner, _resolve=span_resolve):
                    if b.kind in RAW_KINDS:
                        span = (b.line - 1, min(n - 1, b.line - 1 + b.raw.count("\n")))
                        for x in range(span[0], span[1] + 1):
                            raw_spans[x] = span
            lead = re.sub(r"^(?:[ \t]*(?:>|(?:[-+*]|[0-9]{1,9}[.)])(?=[ \t]|$)))*[ \t]*", "",
                          lines[j][:on.start()])
            cover = raw_spans[j]
            e = cover[1] if cover is not None and i < cover[0] and (cover[0] < j or lead) else None
            if e is not None:
                blocks.append(Block("protected", attrs(base=base), "\n".join(src_lines[i:e + 1]), [],
                                    start_line))
                i = e + 1
                continue
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
                if quote and _leaves_list_item(qcols_of(k, quote), quote, level_stacks):
                    # A quote marker that leaves a list item closes it.
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
            if not inner and end + 1 < n and i > math_skip:
                # The renderers read math as Markdown: a fence or an HTML
                # block that starts in it may run on past its last line,
                # and its last line is text of a paragraph that a line
                # right after it continues, where a code span, raw HTML,
                # emphasis or a link text may run on and a setext
                # underline makes a heading, so that the lines after it may
                # be code. The lines from there are kept byte for byte (see
                # md_list_freeze). Math blocks right after each other are
                # one paragraph to the renderers, read once; one inside a
                # block that runs on is part of that block.
                texts = [_past_container(_strip_quote(lines[x], quote), base) for x in range(i, end + 1)]
                runs_on = False
                x = i + 1
                while x <= end and not runs_on:
                    rel = texts[x - i]
                    fence = _is_fence_open(rel) if _indent_of(rel) < 4 else None
                    if fence:
                        last, _ = fence_end(x + 1, quote, depth, base, fence)
                    elif _indent_of(rel) < 4 and _is_html_start(rel, interrupt=bool(texts[x - i - 1].strip())):
                        last = html_end(x, quote, depth, base, rel)
                    else:
                        x += 1
                        continue
                    runs_on = last > end
                    x = last + 1
                chain = math_chain if math_chain is not None and math_chain[0] == i else None
                math_chain = None
                if runs_on:
                    md_list_freeze.append(chain[1] if chain else i)
                    math_skip = x - 1
                else:
                    if chain:
                        chain[2].extend(texts)
                        texts = chain[2]
                    nxt = lines[end + 1]
                    nrel = _past_container(_strip_quote(nxt, quote), base)
                    continues = bool(nrel.strip(" \t")) and not _mdit_interrupts(nxt, quote)
                    if (continues and nrel.lstrip().startswith("$$") and _indent_of(nrel) < 4
                            and _quote_depth(nxt)[0] == quote and in_container(end + 1, quote, depth, base)):
                        # (The next line starts a math block the guard reads
                        # next; should it read that line otherwise, the
                        # lines from there are kept, see the main loop.)
                        math_chain = (end + 1, chain[1] if chain else i, texts)
                    elif continues:
                        tail = texts
                        for x in range(len(texts) - 1, -1, -1):
                            if not texts[x].strip(" \t"):
                                tail = texts[x + 1:]
                                break
                        para = []
                        for x in range(end + 1, n):
                            text = _strip_quote(lines[x], _quote_depth(lines[x])[0])
                            if not text.strip(" \t") or (x > end + 1 and _mdit_interrupts(lines[x], quote)):
                                break
                            para.append(text)
                        body = "\n".join(tail)
                        after = "\n".join(para)
                        if (SETEXT_LIKE_RE.match(nrel) or _md_open_bracket(body, span_resolve)
                                or _md_runs_on(body, after, span_resolve)
                                or _md_emphasis_runs_on(body, after, span_resolve)):
                            md_list_freeze.append(end + 1)
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
            if any(ancestry):
                # Inside a list item, the whitespace of the blank lines after
                # the definition decides in cmark-gfm whether the list is
                # loose (the definition's end state is not modeled): those
                # lines are kept as written when a line follows them.
                k = end + 1
                while k < n and not _strip_quote(lines[k], quote).strip():
                    k += 1
                if end + 1 < k < n:
                    blocks[-1].attrs["after_sep"] = tuple(lines[end + 1:k])
            if (not inner and len(blocks) > 1 and blocks[-2].kind == "paragraph"
                    and blocks[-2].line + blocks[-2].raw.count("\n") == i
                    and not _md_starts_anew(lines, i, blocks[-2])):
                # (The definition ends cmark-gfm's paragraph right before
                # it, which markdown-it continues into the definition: where
                # a code span, raw HTML, emphasis or a link text opened in
                # that paragraph runs on into it, the lines from the
                # paragraph on are kept byte for byte.)
                prev = [_strip_quote(lines[x], _quote_depth(lines[x])[0]) for x in range(blocks[-2].line - 1, i)]
                after = []
                for x in range(i, n):
                    text = _strip_quote(lines[x], _quote_depth(lines[x])[0])
                    if not text.strip(" \t") or (x > i and _mdit_interrupts(lines[x], quote)):
                        break
                    after.append(text)
                prev_text, after_text = "\n".join(prev), "\n".join(after)
                if (_md_open_bracket(prev_text, span_resolve) or _md_runs_on(prev_text, after_text, span_resolve)
                        or _md_emphasis_runs_on(prev_text, after_text, span_resolve)):
                    md_list_freeze.append(blocks[-2].line - 1)
            # markdown-it has no footnotes: it reads the definition as a
            # paragraph (or a reference definition) and its lazy and
            # indented lines as paragraph text. A line right after it that
            # cmark-gfm starts a block other than a paragraph on but that
            # does not interrupt a paragraph for markdown-it (raw HTML of
            # start condition 7, a list item numbered other than 1 or an
            # empty one, indented code past a container it leaves) may
            # continue that paragraph, and a fence or an HTML
            # block that ends it there runs on past cmark-gfm's block (a
            # paragraph cmark-gfm starts there reads as markdown-it's
            # paragraph does from there on): the lines from there are
            # kept byte for byte (see md_list_freeze). No paragraph is open
            # there for markdown-it after a blank line inside the definition
            # (it reads the indented lines after it as code), nor when the
            # definition starts after a blank line and markdown-it reads it
            # as a reference definition and then code. A definition right
            # after it is read the same way where it ends.
            if not inner and end + 1 < n:
                nxt = lines[end + 1]
                nbody = _strip_quote(nxt, _quote_depth(nxt)[0])
                own = [_strip_quote(lines[x], min(quote, _quote_depth(lines[x])[0])) for x in range(i, end + 1)]
                after_def = _past_container(nbody, base)
                if (nbody.strip() and not FOOTNOTE_DEF_RE.match(nbody.lstrip(" \t"))
                        and all(text.strip(" \t") for text in own)
                        and not _mdit_interrupts(nxt, quote)):
                    md_open_end = True
                    anew = _md_starts_anew(lines, i, blocks[-2] if len(blocks) > 1 else None)
                    if anew:
                        reading = _mdit_reading([_past_container(text, base) for text in own], 0)
                        md_open_end = not (reading and reading[-1][0] in ("definition", "code")
                                           and reading[-1][2] == len(own))
                    # (A paragraph cmark-gfm starts there continues markdown-
                    # it's: a code span, raw HTML, emphasis or a link text
                    # left open in the definition may run on into it, and a
                    # setext underline there ends markdown-it's paragraph as
                    # a heading, so that the lines after it may be its code.)
                    body = "\n".join([cbody[fm.end():]] + own[1:])
                    para = []
                    for k in range(end + 1, n):
                        text = _strip_quote(lines[k], _quote_depth(lines[k])[0])
                        if not text.strip(" \t") or (k > end + 1 and _mdit_interrupts(lines[k], quote)):
                            break
                        para.append(text)
                    if md_open_end and (_starts_block(after_def, False) or _indent_of(after_def) >= 4
                                        or SETEXT_LIKE_RE.match(after_def)
                                        or any(ch in "*_~" for ch in body) or _md_open_bracket(body, span_resolve)
                                        or _md_runs_on(body, "\n".join(para), span_resolve)):
                        md_list_freeze.append(end + 1)
                    elif md_open_end and not anew:
                        # (A paragraph cmark-gfm starts there continues the
                        # paragraph markdown-it reads from before the
                        # definition, whose code spans may pair over the
                        # lines before: those lines are read otherwise by
                        # markdown-it, see _mask_code. Where markdown-it's
                        # paragraph starts with the definition and nothing
                        # in it runs on, it reads them as cmark-gfm does.)
                        k = end + 1
                        while k < n and _strip_quote(lines[k], _quote_depth(lines[k])[0]).strip(" \t") and (
                                k == end + 1 or not _mdit_interrupts(lines[k], quote)):
                            fn_line[k] = True
                            k += 1
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
        # Lazy lines with fewer quote markers than the paragraph, by index
        # in ``content`` (markdown-it never reads one as an underline).
        quote_lazy = set()
        # The lines with quote markers removed and tabs expanded at their
        # true columns (for markdown-it's indentation).
        col_lines = [content[0]]
        # The number of quote markers on each line.
        depths = [quote]
        # Lazy lines whose leading whitespace cmark-gfm keeps (see
        # _read_definitions), by index in ``content``.
        cm_lazy = {}
        resolved = None
        j = i + 1
        setext_level = 0

        def add_line(j, nq):
            # A line of the paragraph with ``nq`` quote markers. cmark-gfm
            # adds a lazy line (one that does not reach all of the
            # paragraph's containers) with the whitespace after the
            # containers it does reach: "text" when no open list item
            # can take that whitespace, "maybe" when one may.
            col = _strip_quote(lines[j], nq)
            if col[:1] == " ":
                if nq < quote:
                    cm_lazy[len(content)] = ("maybe" if nq < len(level_stacks) and level_stacks[nq]
                                             else "text")
                elif depth and _indent_of(col) < base:
                    # It keeps the whitespace past the outer list items its
                    # indentation reaches (none when it reaches one's
                    # content column exactly).
                    if "\t" in col[:len(col) - len(col.lstrip(" \t"))]:
                        cm_lazy[len(content)] = "maybe" if depth > 1 else "text"
                    elif _indent_of(past_matched(col, nq)):
                        cm_lazy[len(content)] = "text"
            if nq < quote:
                quote_lazy.add(len(content))
            depths.append(nq)
            col_lines.append(col)
            content.append(orig_lines[j][_loose_quote_end(orig_lines[j], nq):])

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
        table_nq = quote
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
                early = _read_definitions(content, parsed_only=True, lazy=cm_lazy)
                if early[1] < len(content):
                    setext_level = 1 if sm.group(1)[0] == "=" else 2
                    j += 1
                    break
                if resolved is None:
                    # cmark-gfm reads the definitions at the first underline
                    # with the lines so far (a title cannot reach past it);
                    # nothing but definitions there, the underline is text,
                    # and the lines from it on start with no definition.
                    resolved = early
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
                add_line(j, nq)
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
                table_nq = nq
                break
            # The original bytes after the line's quote markers, also when a
            # marker was moved for parsing: a tab inside a code span or math
            # that spans lines is compared as written.
            add_line(j, nq)
            if sep_after(j):
                tables_off = True
            j += 1
        defs, rest, kept_titles = resolved or _read_definitions(content, parsed_only=bool(setext_level),
                                                                lazy=cm_lazy)
        # cmark-gfm does not read definitions in the lines above a table's
        # header row (they render as text), while markdown-it does: such a
        # definition only possibly defines its label, and is marked, so a
        # blank line added or removed before the header changes structure.
        above_table = j in table_headers
        # markdown-it reads definitions by its own rules, each at the start
        # of a block (see _mdit_reading). It takes a definition cmark-gfm
        # reads when one of its own starts on the same line, and possibly
        # takes one inside a list item it did not read further.
        # Whether markdown-it continues a paragraph of its own on these lines.
        md_cont = i == md_open
        walk_base = md_open_base if md_cont and md_open_base is not None and md_open_base < base else base
        md_read = _mdit_reading(content, walk_base, "paragraph" if md_cont else None, quote_lazy,
                                col_lines, depths,
                                tuple(c for _, c in level_stacks[quote]) if quote < len(level_stacks) else (),
                                tuple(tuple(c for _, c in stack) for stack in level_stacks))
        md_defs = {r[1]: r[3] for r in md_read if r[0] == "definition"}
        if md_read and md_read[-1][0] == "code" and md_read[-1][2] == len(content) and j < n:
            md_code_tail.append((j, quote, walk_base))
        # A list item markdown-it opens in these lines and still reads at
        # their end: its content column decides whether it takes the lines
        # after cmark-gfm's paragraph (see md_item_open below).
        md_item_col = md_item_mark = md_item_line = None
        for x, r in enumerate(md_read):
            # (Also an empty list item right after a definition, where the
            # walk reads no further: markdown-it starts a block there.)
            if r[0] in ("listitem", "item") or (
                    r[0] == "unknown" and x and md_read[x - 1][2] == r[1]
                    and (md_read[x - 1][0] == "definition" or (
                        # (In a list item markdown-it opened, one beside it or
                        # outside it, whatever ends the item there: the walk
                        # of that item reads one nested in it.)
                        md_item_col is not None
                        and _indent_of(_expand_indent(col_lines[r[1]])) < md_item_col))
                    and _MDIT_LIST_START_RE.match(_expand_indent(col_lines[r[1]]).lstrip(" "))):
                md_item_line = i + r[1]
                body = _expand_indent(col_lines[r[1]])
                ind = len(body) - len(body.lstrip(" "))
                body = body[ind:]
                mark = _MDIT_LIST_START_RE.match(body)
                mark = mark.group(0).rstrip(" \t") if mark else ""
                inner = body[len(mark):].lstrip(" \t")
                gap = len(body) - len(mark) - len(inner)
                md_item_col = ind + len(mark) + (gap if inner and 1 <= gap <= 4 else 1)
                md_item_mark = ind
            elif md_item_col is not None and r[1] and _indent_of(col_lines[r[1]]) < md_item_col:
                md_item_col = None
        md_list_at = next((r[1] for r in md_read if r[0] in ("listitem", "item") or (
            r[0] == "unknown" and _MDIT_LIST_START_RE.match(_expand_indent(col_lines[r[1]]).lstrip(" ")))), None)
        if md_list_at is not None:
            md_list_freeze.append(i + md_list_at)
        elif above_table and content:
            # The header row of a table cmark-gfm reads below these lines is
            # where markdown-it may start a block of its own (after a
            # definition): the row and the lines after it are kept the same
            # way, or only the lines after it when markdown-it reads the row
            # as paragraph text inside the paragraph's containers (prose to
            # both; the delimiter and body rows are text of that paragraph,
            # which a later underline can make a heading).
            trial = _mdit_reading(
                content + [orig_lines[j][_loose_quote_end(orig_lines[j], table_nq):]], walk_base,
                "paragraph" if md_cont else None, quote_lazy | ({len(content)} if table_nq < quote else set()),
                col_lines + [_strip_quote(lines[j], table_nq)], depths + [table_nq],
                tuple(c for _, c in level_stacks[quote]) if quote < len(level_stacks) else (),
                tuple(tuple(c for _, c in stack) for stack in level_stacks))
            row = next((r for r in trial if r[1] <= len(content) < r[2]), None)
            if row is None or row[0] != "paragraph" or row[3]:
                # (From where that reading starts: a definition whose title
                # runs onto the row starts above it.)
                md_list_freeze.append(i + min(row[1], len(content)) if row is not None else j)
            elif row[1] == len(content) and j + 1 < n:
                md_list_freeze.append(j + 1)
        if md_item_col is not None and j < n:
            # (With the content column of the list item around it, which
            # markdown-it reads the lines after it in.)
            md_item_open.append((i, j, quote, md_item_col, md_item_mark, max(
                (c for _, c in (level_stacks[quote] if quote < len(level_stacks) else ())
                 if c <= md_item_mark), default=0), md_item_line))
        md_unknown = next((r[1] for r in md_read if r[0] == "unknown"), None)
        if md_unknown is not None and md_unknown in quote_lazy and j < n:
            # (After markdown-it ended nested quotes there; a list item it
            # closed is the rest of that container, below.)
            md_unknown_from.append((i + md_unknown, j))
        elif md_unknown is not None and j < n and lines[j].strip() and not _mdit_interrupts(lines[j], quote):
            # (What markdown-it reads there, such as a paragraph, may run on
            # over the lines after cmark-gfm's paragraph: they are compared
            # with it as one prose unit, its own lines kept byte for byte.)
            # (Inside the list item markdown-it still reads there: the
            # deepest of cmark-gfm's at that quote depth whose content column
            # the range's first line reaches.)
            add_run((i + md_unknown, j, quote, False, False, max(
                (c for _, c in (level_stacks[quote] if quote < len(level_stacks) else ())
                 if c <= _indent_of(_expand_indent(col_lines[md_unknown]))), default=0), None))
            pre = next((r[1] for r in md_read if r[0] == "paragraph" and r[2] == md_unknown), None)
            if pre is not None:
                md_unit_pre[(i + md_unknown, j)] = i + pre
        cm_firsts = {first for first, _last, _label, _parsed in defs}
        # Labels only markdown-it defines (or may define) in these lines.
        md_only = [r[3] for r in md_read if r[0] == "definition" and r[1] not in cm_firsts]
        for kind, first, last, *_rest in md_read:
            if kind == "unknown":
                md_only += [mdit_label_key(label) for label in _loose_labels("\n".join(content[first:last]))]
        # cmark-gfm drops a paragraph of only definitions in a list item
        # when a blank line closes it, before it decides whether the list is
        # loose; closed otherwise, the paragraph still counts there.
        defs_end = (("blank" if j < n and not _strip_quote(lines[j], quote).strip() else "other")
                    if defs and rest == len(content) and depth > 0 else None)
        for first, last, label, parsed in defs:
            maybe = md_unknown is not None and first >= md_unknown
            md_key = md_defs.get(first, mdit_label_key(label) if maybe else "")
            ref = ((normalize_label(label), parsed and not above_table, md_key, not maybe)
                   if label is not None else None)
            marks = {"above_table": True} if above_table else {}
            if defs_end is not None:
                marks["closed_by"] = defs_end
            if first in kept_titles:
                # A title cmark-gfm keeps from the paragraph text after it.
                marks["kept_title"] = hashlib.sha256(
                    kept_titles[first].encode("utf-8", "surrogatepass")).hexdigest()[:32]
            blocks.append(Block("refdef", attrs(**marks), "\n".join(lines[i + first:i + last]), [],
                                i + first + 1, ref))
        if defs and md_only:
            blocks[-1].md_label = tuple(md_only)
        closers = [r[1] for r in md_read
                   if r[1] and (r[1] in quote_lazy or (depth and _indent_of(col_lines[r[1]]) < base))]
        closer_set = set(closers)
        if closers:
            # (markdown-it reads lines of the paragraph outside its quote or
            # list item after a definition: kept byte for byte from there,
            # as a list it opens is.)
            md_list_freeze.append(i + min(closers))
        if closers:
            # Which blocks markdown-it starts in these lines, which of them
            # it reads outside the paragraph's quote or list item, and where
            # it closes them: whether a line after a definition reaches the
            # list item's content column, or keeps its quote markers, decides
            # where markdown-it reads the rest, although cmark-gfm continues
            # the paragraph either way. (Without line offsets, so rewording
            # and rewrapping inside a block keep it.)
            def closes(k):
                # The quote depth markdown-it reads line k at and the content
                # column of the outermost list item there it does not reach.
                nq = depths[k]
                stack = level_stacks[nq] if nq < len(level_stacks) else []
                ind = _indent_of(col_lines[k])
                return (nq, next((col for _, col in stack if col > ind), None))
            # Each paragraph markdown-it reads in these lines is a prose
            # unit of its own, so inline markup that spans where markdown-it
            # splits cmark-gfm's paragraph is compared as markdown-it groups
            # it.
            # (And the quote depth of the next line, where a quote marker,
            # even alone, opens a quote of markdown-it's own, or whether it
            # is a setext underline, which may end markdown-it's paragraph as
            # a heading; 0 for a blank line, the end or another line.)
            after = (_quote_depth(lines[j])[0] if j < n and lines[j].strip() else 0) or (
                "underline" if j < n and _MDIT_UNDERLINE_RE.match(lines[j].lstrip(" ")) and _indent_of(lines[j]) < 4
                else 0)
            md_shapes.append((i, tuple((r[0], r[3] is True if r[0] == "paragraph" else None,
                                        closes(r[1]) if r[1] in closer_set else None)
                                       for r in md_read) + (after,),
                              ["\n".join(content[x].lstrip(" \t") if x == r[1] else content[x]
                                         for x in range(r[1], r[2]))
                               for r in md_read if r[0] == "paragraph"]))
        if md_read[-1][0] == "html" and md_read[-1][2] == len(content):
            if closers:
                # markdown-it opened it after it closed the paragraph's
                # containers: it runs to a blank line whatever the lines'
                # containers (raw HTML of types 1 to 5 to its end marker).
                hfirst = md_read[-1][1]
                until = _html_end_marker(_expand_indent(content[hfirst]).lstrip(" "))
                if until is not None and until.search("\n".join(content[hfirst:])[1:]):
                    until = None
                # (In the quotes its line opens or keeps: a line with fewer
                # quote markers ends it.)
                md_raw_from.append((j, depths[hfirst], 0, until))
            else:
                md_raw_from.append((j, quote, base, None))
        if closers and j < n:
            # markdown-it read a line of the paragraph outside some of its
            # containers and closed them: the rest of the outermost one it
            # may have closed is read differently (see md_closed_from).
            # (A quote it closed and reopens reads the same, unless it held
            # a list item.)
            k0 = min(closers, key=lambda k: depths[k])
            nq0 = depths[k0]
            stack = level_stacks[nq0] if nq0 < len(level_stacks) else []
            inner = [lv for lv in range(nq0 + 1, min(quote + 1, len(level_stacks))) if level_stacks[lv]]
            if stack and (nq0 < quote or depth) and _indent_of(col_lines[k0]) < stack[-1][1]:
                # (The outermost list item whose content column that line
                # does not reach: markdown-it keeps the ones it reaches.)
                k0_indent = _indent_of(col_lines[k0])
                md_closed_from.append((j, nq0, next(col for _, col in stack if col > k0_indent)))
            elif inner:
                md_closed_from.append((j, inner[0], level_stacks[inner[0]][0][1]))
        last_read = md_read[-1]
        md_level = _quote_depth(lines[i + last_read[1]])[0] if last_read[1] in quote_lazy else quote
        own = None
        if last_read[0] == "paragraph" and (last_read[3] is True or (md_cont and last_read[1] == 0)):
            if md_cont and last_read[1] == 0:
                own = md_open_base
            else:
                # (The list item markdown-it still reads that paragraph in:
                # the deepest one open at its quote depth that the lines it
                # read outside the paragraph's item reach.)
                reached = [_indent_of(col_lines[k]) for k in closers
                           if k <= last_read[1] and depths[k] == md_level]
                own = (max((c for _, c in level_stacks[md_level] if c <= min(reached)), default=0)
                       if reached and md_level < len(level_stacks) else None)
        # (A list item outside the list item markdown-it reads the paragraph
        # in ends it there.)
        own_ends = (j < n and own is not None and own > 0
                    and _mdit_ends_paragraph(lines[j], md_level, own, item_marker(md_level, own)))
        # (The paragraph, or list item only markdown-it opens, that a unit
        # of the lazy run below covers.)
        run_tail = None
        if (last_read[0] in ("paragraph", "unknown", "listitem") and last_read[2] == len(content)
                and not setext_level and j < n):
            # cmark-gfm ended the paragraph at a line that markdown-it
            # reads as a lazy continuation of it (an HTML line or an empty
            # list item outside the paragraph's containers): definitions up
            # to a blank line or a line that interrupts the paragraph only
            # possibly count for markdown-it. (Also the paragraph of a list
            # item only markdown-it opens there.)
            lazy_level = md_level
            if lines[j].strip() and not _mdit_interrupts(lines[j], lazy_level):
                md_lazy_from.append((j, lazy_level))
                if last_read[0] in ("paragraph", "listitem"):
                    run_tail = last_read[1]
                    add_run((i + last_read[1], j, lazy_level,
                                        own_ends or _mdit_ends_paragraph(
                                            lines[j], lazy_level,
                                            # (A paragraph markdown-it reads
                                            # outside its item is measured
                                            # from its own column.)
                                            own if last_read[3] is True
                                            else base if lazy_level == quote and last_read[0] == "paragraph"
                                            else None,
                                            None if last_read[3] is True else item_marker(quote, base)),
                                        last_read[0] == "listitem",
                                        # (Read from the column of the list
                                        # item markdown-it reads it in, and
                                        # ended as its first line is.)
                                        (md_item_col or 0) if last_read[0] == "listitem"
                                        else (own or 0) if last_read[3] is True
                                        else base if lazy_level == quote else 0,
                                        (md_item_col, md_item_mark) if last_read[0] == "listitem"
                                        else (own if last_read[3] is True
                                              else base if lazy_level == quote and last_read[0] == "paragraph"
                                              else None,
                                              None if last_read[3] is True else item_marker(quote, base))))
        if (last_read[0] == "paragraph" and (last_read[3] or (md_cont and last_read[1] == 0))
                and last_read[2] == len(content)
                and not setext_level and j < n and not own_ends):
            # markdown-it reads that paragraph outside the list item or quote
            # it started in; a following list item that cannot interrupt a
            # paragraph (a number other than 1, or an empty one) and no quote
            # marker that reopens a quote continue it.
            if md_item_continues(j, md_level):
                md_open_base = own
                md_open = j
                add_run((i + last_read[1], j, md_level, False, False, own or 0,
                                    (own, item_marker(md_level, own)) if own else None))
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
            # An underline right below definitions is text to cmark-gfm, but
            # markdown-it reads "---" there as a thematic break (and, below a
            # definition it does not take, either underline as a heading), so
            # the underline is part of the structure.
            under = (re.match(r"[ ]{0,3}(=+|-+)[ \t]*$", _past_container(content[rest], base))
                     if defs else None)
            marks = {}
            if under:
                # "=" is text or an h1 underline; "-" is an empty list item,
                # "--" text, and "---" or longer a thematic break (each also
                # an h2 underline below a definition markdown-it does not take).
                run = under.group(1)
                marks["after_definition"] = "=" if run[0] == "=" else "-" * min(len(run), 3)
            # Lines that markdown-it reads as anything but a paragraph (a
            # definition, such as one whose label cmark-gfm does not take
            # because it is over 1000 bytes; indented code; a thematic break;
            # a list item that cannot interrupt a paragraph; an HTML block)
            # are not prose to it: they are kept byte for byte, in order (a
            # paragraph markdown-it reads after them is prose). The underline
            # right below the definitions is compared through after_definition.
            over = []
            md_items = any(r[0] in ("listitem", "item") for r in md_read)
            for r in md_read:
                if md_items and r[2] > rest and r[0] in ("paragraph", "heading"):
                    # (Where markdown-it opened list items of its own, the
                    # indentation of a paragraph's first line decides
                    # whether it reads that paragraph inside one.)
                    over.append(("indent", r[1], r[1], "%d" % _indent_of(col_lines[r[1]])))
                if r[2] <= rest or r[0] == "paragraph":
                    continue
                if r[0] == "heading":
                    # Its text is prose to both; its underline is not.
                    if r[2] - 1 >= rest and not (under and r[2] - 1 == rest):
                        over.append(("underline", r[2] - 1, r[2]))
                    continue
                if r[0] == "listitem":
                    # Its marker is structure; its text is prose.
                    over.append(("listitem", r[1], r[1], r[3]))
                elif not (under and r[1] == rest and r[0] in ("break", "item")):
                    over.append(r)
            kept_lines = list(content)
            for r in over:
                for x in range(max(r[1], rest), r[2]):
                    over_line[i + x] = True
            # (Measured past the quote markers of markdown-it's paragraph,
            # as written: a quote marker after the indentation is text.)
            md_depth = (_quote_depth(lines[i + md_read[-1][1]])[0] if md_read[-1][1] in quote_lazy
                        else quote)
            # (From the column markdown-it reads that paragraph at, when
            # known: a line short of it is lazy text too. Also for a
            # paragraph markdown-it continues from before these lines.)
            und_ind = _indent_of(_strip_quote(orig_lines[j - 1], md_depth))
            lazy_underline = bool(setext_level and md_read[-1][0] == "paragraph"
                                  and (md_read[-1][3] or (md_cont and md_read[-1][1] == 0))
                                  and (und_ind >= 4 + (own or 0) or (own is not None and und_ind < own)))
            if setext_level and (md_read[-1][0] != "paragraph" or md_read[-1][1] in quote_lazy
                                 or lazy_underline):
                # cmark-gfm's underline is not one to markdown-it, which has
                # no paragraph open there, or has one open outside the
                # paragraph's quote (the underline's quote marker opens a
                # new quote) or outside its list item with the underline
                # indented four columns from the line start (lazy text to
                # it): it reads the line anew, and a paragraph it
                # starts there ("=" or "--") continues into the lines after
                # the heading unless one of them ends it. After a list item
                # markdown-it did not read further, or one with text (whose
                # paragraph the underline may continue, and any list item
                # ends), the definitions in those lines only possibly count.
                uline = _past_container(_strip_quote(lines[j - 1], quote), base)
                # (With its indentation: it sets which list item markdown-it
                # reads the line in.)
                over.append(("underline", len(content), len(content) + 1))
                kept_lines.append(uline)
                uline = uline.lstrip(" ")
                if j < n and lines[j].strip():
                    # (A heading in a list item markdown-it opens takes no
                    # underline either: the underline starts a paragraph.)
                    heading_item = md_read[-1][0] == "listitem" and "|" in md_read[-1][3]
                    if md_read[-1][0] == "unknown" or (md_read[-1][0] == "listitem" and not heading_item):
                        md_lazy_from.append((j, quote))
                    elif ((heading_item
                           or md_read[-1][0] in ("paragraph", "heading", "code", "break", "item", "definition"))
                          and not _mdit_interrupts(lines[j], quote)
                          and (lazy_underline
                               or not (_MDIT_BREAK_RE.match(uline) or re.match(r"-[ \t]*$", uline)))):
                        # (It also continues lazily over blocks of other
                        # kinds, such as indented code, and over a list item
                        # that cannot interrupt it, which cmark-gfm opens.)
                        md_open = j
                        md_open_base = None
                        md_lazy_from.append((j, quote))
                        md_item_continues(j, md_depth)
                        add_run((i + (len(content) if heading_item else md_read[-1][1]), j, md_depth,
                                            _mdit_ends_paragraph(lines[j], md_depth,
                                                                 base if md_depth == quote else None,
                                                                 None if md_read[-1][3] is True
                                                                 else item_marker(quote, base)),
                                            False, (md_item_col or 0) if heading_item
                                            else base if md_depth == quote else 0,
                                            (md_item_col, md_item_mark) if heading_item
                                            else (base if md_depth == quote else None,
                                                  None if md_read[-1][3] is True
                                                  else item_marker(quote, base))))
            if over:
                # (A range markdown-it may read in any way keeps the number
                # of quote markers on each line too.)
                kept = "\x00".join(r[0] + "\x00" + (r[3] if r[0] in ("listitem", "indent")
                                                      else "\n".join("%d\x01%s" % (depths[x], kept_lines[x])
                                                                      for x in range(max(r[1], rest), r[2]))
                                                      if r[0] == "unknown"
                                                      else "\n".join(kept_lines[max(r[1], rest):r[2]]))
                                   for r in over)
                digest = hashlib.sha256(kept.encode("utf-8", "surrogatepass")).hexdigest()[:32]
                kind = ("markdown_it_definition" if any(r[0] == "definition" for r in over)
                        else "markdown_it_block")
                marks[kind] = digest
            md_label = None
            if not defs:
                md_label = tuple(md_only) or None
            # cmark-gfm keeps the whitespace at the start of a lazy line
            # (inside a code span or raw HTML, such as an attribute value)
            # and removes it from a line that reaches the paragraph's
            # containers: which lines that may start inside such a span keep
            # it is structure.
            lazy_ws = _spanned_lines(content[rest:], [k - rest for k in sorted(cm_lazy) if k > rest],
                                     span_resolve)
            if lazy_ws:
                marks["lazy_ws"] = lazy_ws
            if base and len(content) - rest > 1:
                # In a list item, how much indentation the renderers remove
                # from the paragraph's later lines depends on the item's
                # content column: where a code span, raw HTML or a link title
                # spans lines, that column is structure too.
                joined = "\n".join(content[rest:])
                if any("\n" in joined[s:e] for _, constructs in _inline_readings(joined, span_resolve)
                       for kind, s, e, _ in constructs if kind in ("code", "html", "linktail")):
                    marks["span_base"] = base
            if setext_level:
                blocks.append(Block("heading", attrs(level=setext_level, **marks),
                                    "\n".join(lines[i + rest:j]), units, i + rest + 1))
            else:
                blocks.append(Block("paragraph", attrs(**marks), "\n".join(lines[i + rest:j]), units,
                                    i + rest + 1))
            # The label markdown-it defines there, for reference_labels.
            blocks[-1].md_label = md_label
            # The text of each list item markdown-it opens in these lines
            # (a paragraph, or a heading's text), and each paragraph or
            # heading it reads there, is a prose unit of its own: its inline
            # markup, code and HTML are compared as markdown-it groups them,
            # not only across cmark-gfm's paragraph. (Not the last one when
            # the lazy run below holds its paragraph; paragraphs the reading
            # shape holds already; not one that is cmark-gfm's unit too.)
            item_units = []
            for r in md_read:
                if r[1] < rest or (r[1] == run_tail and not md_lazy_run[-1][3]):
                    continue
                if r[0] == "listitem":
                    head = content[r[1]].lstrip(" \t")
                    mark = _MDIT_LIST_START_RE.match(head)
                    head = head[mark.end():].lstrip(" \t") if mark else head
                    if "|" in r[3]:
                        heading = ATX_RE.match(head)
                        head = (heading.group(2) or "") if heading else head
                    item_units.append("\n".join([head] + content[r[1] + 1:r[2]]))
                elif (r[0] in ("paragraph", "heading") and not closers
                      and not (r[1] == rest and r[2] == len(content))):
                    last = r[2] - (r[0] == "heading")
                    item_units.append("\n".join([content[r[1]].lstrip(" \t")] + content[r[1] + 1:last]))
            if item_units:
                blocks[-1].md_units = (blocks[-1].md_units or []) + item_units
        i = j

    # Raw blocks are compared byte for byte against the original lines; a
    # line cut after a polish:on marker keeps its cut text.
    for block in blocks:
        if block.kind in RAW_LINE_KINDS:
            first = block.line - 1
            last = first + block.raw.count("\n")
            block.raw = "\n".join(orig_lines[first:last + 1])
    # The blocks markdown-it reads as part of an HTML block that it opened
    # inside a paragraph before them are kept byte for byte, and their
    # definitions only possibly count.
    # (The parse blanks list markers in ``lines``; these read the lines as
    # written.)
    # markdown-it continues a quote at a quote marker after any indentation,
    # where cmark-gfm starts indented code after a quoted block that is not
    # a paragraph: the code's definition-like lines possibly define their
    # labels, and a paragraph markdown-it may have open there continues
    # lazily after the code.
    # (After a quoted HTML block, markdown-it continues that block over the
    # code and up to a blank line, and after a quoted fence that cmark-gfm
    # ended with the quote, that fence: those lines are kept byte for byte.)
    md_html_run = []
    md_quote_raw = []
    prev_block = None
    for block in blocks:
        if block.kind in RAW_LINE_KINDS and block.kind != "indented_code":
            # The same for a line a block compared raw absorbed (a quoted
            # footnote definition's lazy line, for one): a quote marker with
            # four or more columns before it may continue markdown-it's quote
            # there. The line before it need not be quoted (a lazy line may
            # continue the quote), and where the parse read the marker as
            # one inside a list item, markdown-it may still read another
            # quote in deeper containers. So any such line counts. A quoted
            # footnote definition that absorbs a nonblank line with fewer
            # quote markers counts too: markdown-it may have ended the quote
            # there (reading the first line as a reference definition) and
            # read the rest as a paragraph outside it. Either way the block
            # and the lines after it up to the next blank line are kept byte
            # for byte.
            first = block.line - 1
            after = min(first + block.raw.count("\n") + 1, n)
            quote = block.attrs.get("quote", 0) if block.kind == "footnote_def" else 0
            if (any(_indented_quote_marker(orig_lines[k]) for k in range(first, after))
                    or (quote and any(not _md_blank(orig_lines[k]) and _quote_depth(orig_lines[k])[0] < quote
                                      for k in range(first + 1, after)))):
                md_quote_raw.append((first, after))
        if block.kind == "indented_code":
            first = block.line - 1
            after = first + block.raw.count("\n") + 1
            # Code whose lines start with a quote marker, right after a quoted
            # line (also one behind list markers): markdown-it continues the
            # quote there, and what it reads after the marker (a fence, an
            # HTML block, a list item holding either, a paragraph that runs
            # on lazily over lines without a marker, ...) is not modeled.
            # The lines from the code up to the next blank line (spaces and
            # tabs only) are kept byte for byte; see md_quote_raw below.
            if first and _quoted_line(orig_lines[first - 1]) and any(
                    _indented_quote_marker(line) for line in orig_lines[first:after]):
                md_quote_raw.append((first, after))
            if (first and orig_lines[first - 1].strip() and _quote_depth(orig_lines[first - 1])[0]
                    and orig_lines[first].lstrip(" \t").startswith(">")):
                # (So a blank line that ends that quote for markdown-it, and
                # makes the lines code there too, changes the structure.)
                block.attrs["md_quoted"] = True
                labels = tuple(mdit_label_key(label) for label in _loose_labels(block.raw))
                if labels:
                    block.md_label = tuple(block.md_label or ()) + labels
                after = first + block.raw.count("\n") + 1
                if after < n and orig_lines[after].strip():
                    md_lazy_from.append((after, _quote_depth(orig_lines[first - 1])[0]))
                if prev_block is not None and prev_block.line + prev_block.raw.count("\n") == first:
                    if prev_block.kind == "html":
                        md_html_run.append((first, after, None, 0))
                    elif prev_block.kind == "fence" and not prev_block.attrs.get("fence_closed", True):
                        pq = prev_block.attrs.get("quote", 0)
                        fm = FENCE_RE.match(_strip_quote(prev_block.raw.split("\n")[0], pq).lstrip(" "))
                        if fm:
                            md_html_run.append((first, after, (fm.group(2)[0], len(fm.group(2))), pq))
        if block.kind not in ("quote", "list_item"):
            prev_block = block
    written = [_expand_structure(line) for line in orig_lines]

    def relocated(k, below=None):
        # Line ``k`` as written, with the quote markers the parse moved (four
        # or more columns into the line but within the open list items at
        # their level) moved the same way, so its quote depth is the one the
        # parse read. With ``below``, only the markers of the quotes below
        # that depth are moved: the text after them keeps its columns.
        line = written[k]
        for d in sorted(marker_quote_col.get(k, ())):
            if below is not None and d >= below:
                continue
            body = _strip_quote(line, d)
            line = ((_quote_prefix(line, d) + " ") if d else "") + " " * min(_indent_of(body), 3) + body.lstrip(" ")
        return line

    view = [relocated(k) if k in marker_quote_col else written[k] for k in range(n)]
    # markdown-it ends raw HTML (start conditions 1 to 5) in a list item at
    # a blank line that does not reach the item's content column. It reads
    # the lines after that one as blocks of other kinds (their definitions
    # possibly count, and one may run on past cmark-gfm's HTML block), and a
    # paragraph it reads there continues lazily after cmark-gfm's block.
    md_run_from = []
    for block in blocks:
        hbase = block.attrs.get("base", 0) if block.kind == "html" else 0
        if not hbase:
            continue
        hq = block.attrs.get("quote", 0)
        first = block.line - 1
        last = min(n, first + block.raw.count("\n") + 1)
        # (The parse's own first line, where a list marker before the block
        # is blank, or the line as written with moved quote markers.)
        if (_html_end_marker(_strip_quote(block.raw.split("\n")[0], hq).lstrip(" ")) is None
                and _html_end_marker(_strip_quote(view[first], hq).lstrip(" ")) is None):
            continue
        for x in range(first + 1, last):
            hx = _strip_quote(view[x], hq)
            if not hx.strip() and _indent_of(hx) < hbase:
                labels = tuple(mdit_label_key(label) for label in _loose_labels("\n".join(view[x + 1:last])))
                if labels:
                    block.md_label = tuple(block.md_label or ()) + labels
                md_run_from.append((x + 1, last))
                if last < n and orig_lines[last].strip():
                    md_lazy_from.append((last, hq))
                break
    raw_line = [False] * n
    # Lines kept byte for byte by the block that holds them, also inside
    # another block or between blocks (see md_item_lines and the exit walk).
    md_kept = [None] * n
    if md_quote_raw:
        # Each such code block is kept with the lines after it up to the next
        # blank line, quoted or not: a missing quote marker does not end
        # markdown-it's quote while its paragraph runs on lazily. (One pass:
        # the next blank line is looked up, and overlapping runs are marked
        # once.)
        next_blank = [n] * (n + 1)
        for k in range(n - 1, -1, -1):
            next_blank[k] = k if _md_blank(orig_lines[k]) else next_blank[k + 1]
        marked = 0
        for start, after in md_quote_raw:
            end = next_blank[after]
            for x in range(max(start, marked), end):
                md_kept[x] = 0
            marked = max(marked, end)
    # The lines a freeze of a container markdown-it closed already kept (a
    # later one stops there; it runs on over HTML blocks frozen above).
    closed_line = [False] * n
    # (markdown-it's indented code at the end of cmark-gfm's paragraph runs
    # on over blank lines to a further indented line: those blank lines are
    # its content.)
    for z0, q, b in md_code_tail:
        z = z0
        while z < n and _quote_depth(view[z])[0] >= q and not _strip_quote(view[z], q).strip():
            z += 1
        if z0 < z < n and _quote_depth(view[z])[0] >= q and _indent_of(
                _expand_indent(_strip_quote(view[z], q))) >= b + 4:
            for x in range(z0, z):
                md_kept[x] = q
    lazy_line = [False] * n
    for start, level in md_lazy_from:
        end = start
        while end < n and not lazy_line[end] and written[end].strip() and (
                end == start or not _mdit_interrupts(written[end], level)):
            lazy_line[end] = True
            end += 1
    # The quote depth and content column of each list item cmark-gfm opens,
    # by its first line.
    items_at = {}
    for block in blocks:
        if block.kind == "list_item":
            q = block.attrs.get("quote", 0)
            body = _strip_quote(view[block.line - 1], q)
            im = re.match(r"( *)([-+*]|[0-9]{1,9}[.)])( *)", body)
            if im:
                gap = len(im.group(3))
                items_at[block.line - 1] = (q, len(im.group(1)) + len(im.group(2))
                                            + (gap if 1 <= gap <= 4 and body[im.end():].strip() else 1))
    # The first block other than a quote or list item on each line.
    block_at = {}
    for block in blocks:
        if block.kind not in ("quote", "list_item"):
            block_at.setdefault(block.line - 1, block)
    # Which lines after such a paragraph reach the content column of the
    # list item markdown-it still reads there (or are blank), up to the
    # first that does not (it closes the item), as runs: structure of the
    # block on the paragraph's first line, so a line indented into or out of
    # that item is a structure change.
    # The line where markdown-it closes each such item, its quote depth and
    # the content column of the list item around it. The lines from
    # ``start`` that a fence or an HTML block markdown-it reads in the item
    # holds are kept byte for byte.
    md_item_exits = []
    # (The first line of each block cmark-gfm reads, for where an item ends
    # relative to them.)
    block_starts = sorted(block.line - 1 for block in blocks)
    for x, (at, start, level, col, mark_ind, outer, item_line) in enumerate(md_item_open):
        stop = md_item_open[x + 1][1] if x + 1 < len(md_item_open) else n
        runs = []
        # One flag for each block markdown-it starts there (not for the
        # lines that continue a paragraph, lazily or not, so rewrapping
        # prose keeps them): "in" inside the item, "underline" for a setext
        # underline, "blank" for blank lines, and "out" where the item ends.
        # The item is read from its first line (inside cmark-gfm's
        # paragraph), so a paragraph, fence or HTML block open there carries
        # over; only the lines from ``start`` are recorded, and the lines a
        # fence or HTML block holds there are kept byte for byte.
        para = quoted = False
        fence = None
        # (An open HTML block: the end marker of its kind, or "blank" for
        # one that a blank line ends.)
        html = None
        # (A fence or HTML block open inside the item's quote, as above, and
        # the lines of a paragraph that starts like a definition, read with
        # the markdown-it walk while they last.)
        qblock = None
        plines = None
        # (The quote depth ``plines`` started at: a deeper quote marker opens
        # a quote of its own there.)
        pdepth = 0

        def blocks_before(k, first=item_line):
            # How many of cmark-gfm's blocks start between the item's first
            # line and line ``k`` (a line that ends the item in one version
            # and continues its paragraph in the other moves this).
            return bisect.bisect_left(block_starts, k) - bisect.bisect_left(block_starts, first)

        def exit_sig(k, level=level, outer=outer):
            # Where the item ends: the kind of that line, its quote depth,
            # whether it reaches the list item around the item (or is
            # indented code there), and where it is among cmark-gfm's
            # blocks.
            depth = _quote_depth(view[k])[0]
            body = _expand_indent(_strip_quote(view[k], min(level, depth)))
            shape = _line_shape(body)
            return "out:%d:%s:%s:%d" % (depth, shape, "-" if shape == "blank" else
                                        "%s,%s" % _column_bucket(_indent_of(body), (0, outer)),
                                        blocks_before(k))

        def open_block(t):
            # The state markdown-it is in after a block starts with ``t``:
            # whether a paragraph is open, the quoted fence or HTML block
            # open, and the paragraph's lines if it may be a definition.
            rest = _expand_indent(t)
            ind = _indent_of(rest)
            if not rest.strip() or ind >= 4:
                return False, None, None
            rest = rest[ind:]
            fm = FENCE_RE.match(rest)
            if fm and not (fm.group(2)[0] == "`" and "`" in fm.group(3)):
                return False, ("fence", fm.group(2)[0], len(fm.group(2)), qdepth), None
            if _is_html_start(rest):
                marker = _html_end_marker(rest)
                if marker is None:
                    return False, ("html", None, qdepth), None
                return False, (None if marker.search(rest[1:]) else ("html", marker, qdepth)), None
            if rest.startswith("["):
                lines_now = [rest]
                return _mdit_reading(lines_now, 0)[-1][0] == "paragraph", None, lines_now
            return _mdit_opens_paragraph(t), None, None

        def taken(k, level=level, stop=stop):
            # Whether the reading of a quoted paragraph that starts like a
            # definition takes line ``k``, which has no quote markers there,
            # as part of a block that starts earlier (a title, which may run
            # on over the lines after it): markdown-it then reads it in the
            # quote, and anew outside the quote otherwise. (Read with the
            # lines markdown-it's quote takes after it: lazy lines and lines
            # of the same quote, up to a blank line or a block start.)
            trial = list(plines)
            for x in range(k, min(stop, k + 65 - len(plines)) + 1):
                if x == k + 1:
                    # (After a complete definition, only a title may follow
                    # it: a line that starts none starts a block of its own.)
                    short = _mdit_reading(trial, 0)
                    if (len(short) > 1 and short[-1][1] == len(plines) and short[-2][0] == "definition"
                            and short[-2][2] == len(plines) and trial[-1][:1] not in ('"', "'", "(")):
                        return False
                if x == k + 65 - len(plines) or x == stop:
                    # (Lines past what the walk reads: unknown, unless it
                    # ends there.)
                    if x < stop:
                        return None
                    break
                t = relocated(x, level) if x in marker_quote_col else written[x]
                rest = _expand_indent(_strip_quote(t, min(level, _quote_depth(t)[0])))
                if not rest.strip():
                    break
                rest = rest[col:] if _indent_of(rest) >= col else rest
                st = rest.lstrip(" ")
                if _indent_of(rest) < 4 and st.startswith(">"):
                    qt = re.sub(r"^(?:[ ]{0,3}>[ ]?)+", "", st)
                    if st[:len(st) - len(qt)].count(">") > pdepth or not qt.strip():
                        break
                    st = qt.lstrip(" ")
                if x > k and _mdit_interrupts(st, 0):
                    break
                trial.append(st)
            here = len(plines)
            return any(r[1] < here < r[2] for r in _mdit_reading(trial, 0))

        def go_on(t, lazy=False):
            # Whether a paragraph is still open after ``t`` continues it (a
            # lazy line is never its setext underline).
            if plines is not None and len(plines) < 64:
                plines.append(t.lstrip(" "))
                last = _mdit_reading(plines, 0)[-1]
                return last[0] == "paragraph" and last[2] == len(plines)
            return lazy or not (_indent_of(t) < 4 and _MDIT_UNDERLINE_RE.match(t.lstrip(" ")))

        def next_item(k, body):
            # The marker indentation and content column of the list item
            # markdown-it opens at line ``k`` (a list marker short of the
            # item's column, inside the list item around it), or None.
            ind = _indent_of(body)
            if not outer <= ind < outer + 4:
                return None
            mark = _MDIT_LIST_START_RE.match(body[ind:])
            if not mark:
                return None
            mark = mark.group(0).rstrip(" \t")
            rest = body[ind + len(mark):]
            text_after = rest.lstrip(" \t")
            gap = len(rest) - len(text_after)
            return ind, ind + len(mark) + (gap if text_after and 1 <= gap <= 4 else 1)

        k = item_line
        unread = False
        while k < stop:
            record = k >= start
            if plines is not None and len(plines) >= 64 and not unread:
                # (A paragraph whose label is closed and not followed by a
                # colon, or holds a bracket, starts no definition whatever
                # follows: it stays a paragraph, which the lines after it
                # continue. A label that is still open may close later.)
                joined = "\n".join(plines)
                edge = re.search(r"(?<!\\)(?:\\\\)*[][]", joined[1:])
                if edge is not None and (joined[1 + edge.end() - 1] == "[" or not joined.startswith(":", 1 + edge.end())):
                    plines = None
            if plines is not None and (len(plines) >= 64 or unread):
                # (A paragraph that starts like a definition and runs past
                # what the markdown-it walk reads: the lines after it, up to
                # a blank line, are kept byte for byte, wherever markdown-it
                # reads them.)
                if record:
                    runs.append("long")
                while k < stop and _strip_quote(view[k], min(level, _quote_depth(view[k])[0])).strip():
                    if k >= start:
                        md_kept[k] = level
                    k += 1
                para = quoted = unread = False
                qblock = plines = None
                continue
            # (Read with the markers of the item's quotes where the parse
            # moved them into list items, and the rest at its columns.)
            text = relocated(k, level) if k in marker_quote_col else written[k]
            if level and _quote_depth(view[k])[0] < level:
                # (Fewer quote markers end the quote, and the item with it,
                # unless the line continues a paragraph lazily. Read with
                # the quote markers the parse moved into list items.)
                if (para and fence is None and html is None and _quote_depth(view[k])[1].strip()
                        and not _mdit_interrupts(view[k], level)
                        # (Any list marker, whatever its number and also an
                        # empty item, ends a quote there in markdown-it.)
                        and not re.match(r"[ ]{0,3}(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)",
                                         _expand_indent(_quote_depth(view[k])[1]))):
                    para = go_on(_quote_depth(view[k])[1], lazy=True)
                    k += 1
                    continue
                if record:
                    if not _quote_depth(view[k])[1].strip() and (not runs or runs[-1] != "blank"):
                        # (A blank line there ends the quote: recorded as
                        # a blank line where the item ends, as a blank line
                        # that keeps the markers followed by one that does
                        # not is.)
                        runs.append("blank")
                    runs.append(exit_sig(k) if runs[-1:] != ["blank"]
                                else "out:%d:blank:-:%d" % (_quote_depth(view[k])[0], blocks_before(k)))
                md_item_exits.append((k, level, outer))
                break
            body = _expand_indent(_strip_quote(text, min(level, _quote_depth(text)[0])))
            if k == item_line:
                # (The text after the marker starts the item's first block.)
                body = " " * col + body[col:] if len(body) > col else ""
                if not body.strip():
                    k += 1
                    continue
            ind = _indent_of(body)
            if not body.strip():
                if fence is not None or (html is not None and html != "blank"):
                    # (Inside a fence, or raw HTML that runs to its end
                    # marker.)
                    if record:
                        md_kept[k] = level
                else:
                    if record and (not runs or runs[-1] != "blank"):
                        runs.append("blank")
                    para = quoted = False
                    html = qblock = plines = None
                k += 1
                continue
            if fence is not None or html is not None:
                # (A fence or HTML block in the item ends with it: its lines
                # are never lazy.)
                if ind < col:
                    if record:
                        runs.append(exit_sig(k))
                    nxt = next_item(k, body) if _quote_depth(text)[0] <= level else None
                    if nxt is not None:
                        # (A list marker there starts the next item, which
                        # the walk reads on.)
                        mark_ind, col = nxt
                        item_line = k
                        para = quoted = unread = False
                        fence = html = qblock = plines = None
                        continue
                    md_item_exits.append((k, level, outer))
                    break
                if record:
                    md_kept[k] = level
                inner = body[col:]
                if html is not None:
                    if html != "blank" and html.search(inner):
                        html = None
                elif _indent_of(inner) < 4 and re.match(
                        re.escape(fence[0]) + "{%d,}[ \t]*$" % fence[1], inner.lstrip(" ")):
                    fence = None
                k += 1
                continue
            if (ind < col and plines is not None and quoted and not para and len(plines) < 64
                    and taken(k) is None):
                # (A line short of the item's column the walk cannot read:
                # kept byte for byte from here, as above.)
                unread = True
                continue
            if ind >= col:
                inner = body[col:]
                rind = _indent_of(inner)
                stripped = inner.lstrip(" ")
                quote_line = rind < 4 and stripped.startswith(">")
                if (plines is not None and quoted and not para and not quote_line and len(plines) < 64
                        and not _mdit_interrupts(inner, 1)):
                    took = taken(k)
                    if took is None:
                        # (The walk cannot read that far: kept byte for byte
                        # from here, as above.)
                        unread = True
                        continue
                    if took:
                        # (A line without quote markers that the reading of
                        # the quote's paragraph takes, such as a definition's
                        # title, is read in the quote.)
                        para = go_on(inner, lazy=True)
                        k += 1
                        continue
                    # (One it does not take ends the quote: markdown-it reads
                    # it anew in the item.)
                    quoted = para = False
                    plines = None
                # (What a quote line holds: only a paragraph in it continues
                # lazily.)
                qtext = re.sub(r"^(?:[ ]{0,3}>[ ]?)+", "", stripped) if quote_line else ""
                qdepth = stripped[:len(stripped) - len(qtext)].count(">") if quote_line else 0
                if quote_line and quoted and qblock is not None and qdepth < qblock[-1]:
                    # (A line with fewer quote markers ends the quote the
                    # fence or HTML block is in, and the block with it.)
                    qblock = None
                    para, qblock, plines = open_block(qtext)
                    pdepth = qdepth
                    if record and qblock is not None:
                        md_kept[k] = level
                elif quote_line and quoted:
                    if qblock is not None:
                        # (A line of a fence or HTML block in the quote: kept
                        # byte for byte.)
                        if record:
                            md_kept[k] = level
                        if not qtext.strip():
                            if qblock[0] == "html" and qblock[1] is None:
                                qblock = None
                        elif qblock[0] == "fence":
                            if _indent_of(_expand_indent(qtext)) < 4 and re.match(
                                    re.escape(qblock[1]) + "{%d,}[ \t]*$" % qblock[2], qtext.lstrip(" ")):
                                qblock = None
                        elif qblock[1] is not None and qblock[1].search(qtext):
                            qblock = None
                        para = False
                    elif ((para or plines is not None) and qtext.strip() and not _mdit_interrupts(qtext, 0)
                          and not (plines is not None and qdepth > pdepth)):
                        # (Also after a definition, whose title may follow,
                        # but not in a deeper quote, which opens there.)
                        para = go_on(qtext)
                    else:
                        para, qblock, plines = open_block(qtext)
                        pdepth = qdepth
                        if record and qblock is not None:
                            md_kept[k] = level
                elif para and not quoted and rind < 4 and _MDIT_UNDERLINE_RE.match(stripped) and plines is None:
                    if record:
                        runs.append("underline")
                    para = False
                elif ((para or (plines is not None and not quoted)) and not quote_line
                      and not _mdit_interrupts(inner, 1 if quoted else 0)):
                    para = go_on(inner, lazy=quoted)
                else:
                    if record:
                        runs.append("in")
                    fm = FENCE_RE.match(stripped)
                    quoted = quote_line
                    qblock = plines = None
                    if rind < 4 and fm and not (fm.group(2)[0] == "`" and "`" in fm.group(3)):
                        fence = (fm.group(2)[0], len(fm.group(2)))
                        para = False
                        if record:
                            md_kept[k] = level
                    elif rind < 4 and _is_html_start(stripped, interrupt=para):
                        # (An HTML block runs to its end marker, or to a
                        # blank line, or to the item's end.)
                        marker = _html_end_marker(stripped)
                        html = "blank" if marker is None else (None if marker.search(stripped[1:]) else marker)
                        para = False
                        if record:
                            md_kept[k] = level
                    else:
                        para, qblock, plines = open_block(qtext if quote_line else inner)
                        pdepth = qdepth
                        if record and qblock is not None:
                            md_kept[k] = level
            elif not ((para or (plines is not None and quoted and len(plines) < 64 and taken(k)))
                      and fence is None and html is None and _quote_depth(text)[0] <= level
                      and not _mdit_lazy_breaks(body)
                      and not _mdit_ends_paragraph(text, level, col, mark_ind)):
                # (A lazy line short of the item's column: a block start at
                # any indentation ends the paragraph there.)
                if record:
                    runs.append(exit_sig(k))
                nxt = next_item(k, body) if _quote_depth(text)[0] <= level else None
                if nxt is not None:
                    # (A list marker there starts the next item, which the
                    # walk reads on.)
                    mark_ind, col = nxt
                    item_line = k
                    para = quoted = unread = False
                    fence = html = qblock = plines = None
                    continue
                md_item_exits.append((k, level, outer))
                break
            else:
                para = go_on(body, lazy=True)
            k += 1
        if at in block_at:
            block_at[at].attrs["md_item_lines"] = tuple(runs)
    for at, shape, texts in md_shapes:
        if at in block_at:
            block_at[at].attrs["md_shape"] = shape
            block_at[at].md_units = (block_at[at].md_units or []) + texts
    # Containers markdown-it reads outside cmark-gfm's (see below), in the
    # order they are found.
    closed_queue = list(md_closed_from)

    def swallowed(first, last, at):
        # A list item cmark-gfm opens in lines ``first`` to ``last`` that
        # markdown-it reads inside an HTML block stays open after the block,
        # where markdown-it reads the block's container: the rest of that
        # item (from line ``at``) is read outside it.
        cols = [items_at[k] for k in range(first, last) if k in items_at]
        if cols:
            closed_queue.append((at,) + min(cols))

    # The lines an HTML block markdown-it opened inside a paragraph runs over.
    html_line = [False] * n
    for start, quote, base, until in md_raw_from:
        end = start
        while end < n and not raw_line[end]:
            text = view[end]
            if until is not None:
                raw_line[end] = html_line[end] = True
                end += 1
                if until.search(text):
                    break
                continue
            if not any(_strip_quote(line, quote).strip() and _quote_depth(line)[0] >= quote
                       and _indent_of(_strip_quote(line, quote)) >= base for line in (text, written[end])):
                break
            raw_line[end] = html_line[end] = True
            end += 1
        swallowed(start, end, end)

    def freeze_run(k, end, html=False, fence=None, open_depth=0):
        # Keep the lines from ``k`` byte for byte: up to ``end``, and past it
        # while a block markdown-it may read there runs on (a paragraph or an
        # HTML block to a blank line or, for a paragraph, a line that
        # interrupts it; a fence or a raw HTML element to its end). Text that
        # may belong to an HTML block (one that starts there, or a line an
        # HTML block frozen above holds) runs to a blank line, also when a
        # fence or raw HTML element in it closed; a fence that opened in such
        # text and is still open after that blank line may instead open at
        # its closing line. ``fence`` (with the quote depth of its opening
        # line) is a fence markdown-it has open at ``k``; quote markers are
        # then counted as markdown-it does, after any indentation.
        mdq = fence is not None
        prev_blank = False
        # Whether a block markdown-it reads in the frozen lines may run on
        # (anything but a fence or raw HTML that just closed).
        run_on = True
        html_end = None
        maybe_html = html
        # Whether the open fence or raw HTML opened in text that may belong
        # to an HTML block, and whether that block has ended since.
        in_html = flip = False
        html_from = k if html else None
        while k < n and not closed_line[k]:
            text = view[k]
            depth_k = _quote_depth(text)[0]
            if mdq:
                depth_k = re.match(r"(?:[ \t]*>)*", text).group(0).count(">")
            plain_text = _strip_quote(text, depth_k) if not mdq else re.sub(r"^(?:[ \t]*>)*[ \t]?", "", text)
            if k >= end and fence is None and html_end is None and (
                    prev_blank or not run_on or (not maybe_html and _mdit_interrupts(text, depth_k))):
                break
            run_on = True
            if not plain_text.strip():
                if maybe_html:
                    swallowed(html_from, k, k)
                    maybe_html = False
                    flip = in_html
            elif html_line[k] and not maybe_html and fence is None and html_end is None:
                maybe_html = True
                html_from = k
            if (fence is not None or html_end is not None) and depth_k < open_depth:
                fence = html_end = None
            if fence is not None:
                inner_text = plain_text if mdq else _strip_quote(text, open_depth)
                if (depth_k == open_depth and _indent_of(inner_text) < 4
                        and re.match(re.escape(fence[0]) + "{%d,}[ \t]*$" % fence[1], inner_text.lstrip(" "))):
                    if flip:
                        # (Read as an opening fence instead.)
                        fence = (fence[0], len(inner_text.strip()))
                        in_html = flip = False
                    else:
                        fence = None
                        run_on = maybe_html or in_html
            elif html_end is not None:
                if html_end.search(plain_text if mdq else _strip_quote(text, open_depth)):
                    html_end = None
                    run_on = maybe_html or in_html
            else:
                stripped = plain_text.lstrip(" ")
                fm = FENCE_RE.match(stripped)
                if fm and _indent_of(plain_text) < 4 and not (fm.group(2)[0] == "`" and "`" in fm.group(3)):
                    fence = (fm.group(2)[0], len(fm.group(2)))
                    open_depth = depth_k
                    in_html, flip = maybe_html, False
                elif _indent_of(plain_text) < 4:
                    marker = _html_end_marker(stripped)
                    if marker is not None and not marker.search(stripped[1:]):
                        html_end = marker
                        open_depth = depth_k
                        in_html, flip = maybe_html, False
                    elif _is_html_start(stripped) and not maybe_html:
                        maybe_html = True
                        html_from = k
            raw_line[k] = closed_line[k] = True
            # (A blank line inside a fence or raw HTML, where its whitespace
            # is content, is kept also without a block of its own.)
            if not text.strip() and (fence is not None or html_end is not None):
                md_kept[k] = open_depth
            prev_blank = not text.strip()
            k += 1
        if maybe_html:
            swallowed(html_from, k, k)

    # The lines that continue a paragraph cmark-gfm has open (the
    # definitions at its start are blocks of their own; a list item or a
    # quote that opens on a line starts a new paragraph there).
    cont_line = [False] * n
    opens = {block.line - 1 for block in blocks if block.kind in ("list_item", "quote")}
    in_def = [False] * (n + 1)
    for block in blocks:
        if block.kind in ("paragraph", "heading", "refdef"):
            first = block.line - 1
            last = min(n, first + block.raw.count("\n") + 1)
            cont_line[first] = bool(first and in_def[first - 1] and first not in opens)
            for k in range(first + 1, last):
                cont_line[k] = True
            if block.kind == "refdef":
                for k in range(first, last):
                    in_def[k] = True

    # The last region read for each (quote depth, content column): a start
    # inside it ends at the same line and was frozen with it.
    regions = {}

    def close_region(start, quote, base):
        seen = regions.get((quote, base))
        if seen is not None and seen[0] <= start < seen[1]:
            return
        # The rest of cmark-gfm's container (blank lines included, and the
        # lazy lines that continue a paragraph in it), which markdown-it
        # reads outside it: its definitions only possibly count. From the
        # first line markdown-it may read as a block of another kind there
        # (indented four columns past its quote markers, a fence or an HTML
        # block), the blocks are kept byte for byte (see freeze_run).
        # (A line is read both as written and with the quote markers the
        # parse moved: it is inside when either reading puts it there, and
        # risky when either reading is.)
        end = start
        while end < n:
            if not any(_strip_quote(line, quote).strip() == "" or (
                    _quote_depth(line)[0] >= quote and _indent_of(_strip_quote(line, quote)) >= base)
                       for line in (view[end], written[end])):
                if not cont_line[end]:
                    break
            end += 1
        regions[(quote, base)] = (start, end)
        # Whether a blank line follows the region (markdown-it may continue a
        # block it reads there, such as a quote, on the next line).
        owner = next((block_at[k] for k in range(start, end) if k in block_at), None)
        if owner is not None:
            owner.attrs["md_region_next"] = ("blank" if end >= n or not written[end].strip()
                                             else _quote_depth(written[end])[0])
        risky = None
        for k in range(start, end):
            lazy_line[k] = True
            if risky is None:
                for line in (view[k], written[k]):
                    text = _strip_quote(line, _quote_depth(line)[0])
                    st = text.lstrip(" ")
                    if st and (_indent_of(text) >= 4 or FENCE_RE.match(st) or _is_html_start(st)):
                        risky = k
        if risky is None:
            # A paragraph markdown-it reads in the last of those lines may
            # continue lazily past the container.
            k = end
            while end > start and k < n and written[k].strip() and written[end - 1].strip():
                lazy_line[k] = True
                k += 1
            return
        freeze_run(risky, end)

    done = set()
    queued = [0]

    def drain():
        # (In the order found, so a region read once covers the later starts
        # inside it.)
        while queued[0] < len(closed_queue):
            item = closed_queue[queued[0]]
            queued[0] += 1
            if item not in done:
                done.add(item)
                close_region(*item)

    drain()
    # Where markdown-it closes a list item only it opens (see
    # md_item_lines above), it reads the line anew outside the item, where
    # cmark-gfm may still be inside a fence (that started in the item's
    # lines): from a line markdown-it reads as an opening fence that
    # cmark-gfm does not open there (or as indented code, four columns past
    # the content column of the list item around it), what markdown-it
    # reads as code is kept byte for byte, until both are outside fences
    # and raw blocks again.
    def md_block_end(m, level, col, para, inner_quote=0):
        # The end of the fence, HTML block or indented code markdown-it
        # starts at line ``m`` in a container at quote depth ``level`` whose
        # content column is ``col`` (with a paragraph open there when
        # ``para``); a line that leaves the container ends it too. ``m``
        # when it starts none there.
        def inner(x):
            if _quote_depth(written[x])[0] < level:
                return None
            body = _expand_indent(_strip_quote(written[x], level))
            if not body.strip():
                return ""
            if _indent_of(body) < col:
                return None
            if not inner_quote:
                return body[col:]
            # (Inside a quote that opens at the container's column.)
            rel = body[col:]
            if _indent_of(rel) >= 4 or _quote_depth(rel)[0] < inner_quote:
                return None
            return _expand_indent(_strip_quote(rel, inner_quote))
        first = inner(m)
        if not first:
            return m
        stripped = first.lstrip(" ")
        if _indent_of(first) >= 4:
            if para:
                return m
            # (Blank lines after the last indented line are not part of the
            # code.)
            x = last = m + 1
            while x < n and inner(x) is not None and (not inner(x) or _indent_of(inner(x)) >= 4):
                x += 1
                if inner(x - 1):
                    last = x
            return last
        fm = FENCE_RE.match(stripped)
        if fm and not (fm.group(2)[0] == "`" and "`" in fm.group(3)):
            close = re.compile(re.escape(fm.group(2)[0]) + "{%d,}[ \t]*$" % len(fm.group(2)))
            x = m + 1
            while x < n and inner(x) is not None:
                if _indent_of(inner(x)) < 4 and close.match(inner(x).lstrip(" ")):
                    return x + 1
                x += 1
            return x
        if _is_html_start(stripped, interrupt=para):
            marker = _html_end_marker(stripped)
            if marker is not None and marker.search(stripped[1:]):
                return m + 1
            x = m + 1
            while x < n and inner(x) is not None:
                if marker is None and not inner(x):
                    break
                if marker is not None and marker.search(inner(x)):
                    return x + 1
                x += 1
            return x
        return m

    # Where markdown-it closes a list item only it opens (see
    # md_item_lines above), it reads the lines from there anew in the list
    # item around it, where cmark-gfm may still be inside a fence that
    # started in the item's lines: what markdown-it reads there as a fence,
    # an HTML block or indented code (measured from that item's content
    # column, and ending where the line leaves it) is kept byte for byte,
    # until both read a line as other than such a block.
    if md_item_exits:
        cm_raw = [False] * n
        for block in blocks:
            if block.kind in RAW_KINDS:
                first = block.line - 1
                for k in range(first, min(n, first + block.raw.count("\n") + 1)):
                    cm_raw[k] = True
        # (A walk that reaches a line in the state an earlier walk had there
        # reads the rest as that one did, so it stops: repeated exits are
        # read once.)
        walked = set()
        for out, level, outer in md_item_exits:
            m = out
            mpara = False
            while m < n and _quote_depth(written[m])[0] >= level:
                if (m, mpara, level, outer) in walked:
                    break
                walked.add((m, mpara, level, outer))
                body = _expand_indent(_strip_quote(written[m], level))
                if body.strip() and _indent_of(body) < outer:
                    break
                end = md_block_end(m, level, outer, mpara)
                if end > m:
                    for x in range(m, end):
                        md_kept[x] = level
                    mpara = False
                    m = end
                    continue
                rel = body[outer:]
                if not mpara and _indent_of(rel) < 4 and rel.lstrip(" ").startswith(">"):
                    # (A quote markdown-it opens there, at the column of the
                    # list item around the item: what it reads in that quote
                    # as a fence, an HTML block or indented code is kept
                    # byte for byte too.)
                    end = md_block_end(m, level, outer, False, inner_quote=_quote_depth(rel)[0])
                    if end > m:
                        for x in range(m, end):
                            md_kept[x] = level
                        m = end
                        continue
                if not cm_raw[m]:
                    break
                stripped = body[outer:].lstrip(" ")
                mpara = bool(stripped) and not (ATX_RE.match(stripped) or HR_RE.match(stripped))
                m += 1

    # Where markdown-it continues a paragraph lazily over the block cmark-gfm
    # starts after it (an HTML block, for example), what it reads in that
    # block (a fence or raw HTML that interrupts its paragraph) may run on
    # past it, and an inline element may span from the paragraph into it:
    # the block's lines and what runs on are kept byte for byte, and so is
    # the paragraph when it holds the start of an HTML tag, a code span or
    # a link.
    def setext_at(k, level, col=0):
        # Whether line ``k`` may underline a paragraph markdown-it has open
        # at quote depth ``level`` in a list item whose content column is
        # ``col`` (indented less than four columns past it).
        body = _strip_quote(written[k], level)
        if col:
            body = _expand_indent(body)
            if _indent_of(body) < col:
                return False
            body = body[col:]
        return (_quote_depth(written[k])[0] == level and _indent_of(body) < 4
                and bool(_MDIT_UNDERLINE_RE.match(body.lstrip(" "))))

    def md_breaks(text, level, col=0):
        # Whether ``text`` interrupts a paragraph markdown-it has open at
        # quote depth ``level`` in a list item whose content column is
        # ``col`` (a line that reaches the column is read from it).
        if col:
            body = _expand_indent(_strip_quote(text, level))
            if _quote_depth(text)[0] <= level and _indent_of(body) >= col:
                return _mdit_interrupts(body[col:], 0)
            if _quote_depth(text)[0] == level and body.strip():
                # (A lazy line short of the column: markdown-it counts its
                # indentation from the column, so a block start interrupts
                # the paragraph at any indentation there.)
                return _mdit_interrupts(body.lstrip(" "), 0)
        return _mdit_interrupts(text, level)

    # (The lines of each such run that markdown-it reads as paragraph text.)
    run_line = [False] * n
    if md_lazy_run:
        starts = sorted(block_at)
        # (The lines an earlier unit already covers: a further list item
        # markdown-it continues the same paragraph over adds no unit.)
        covered = 0
        for first, at, level, ends, marker_first, col, para_end, open_cols in md_lazy_run:
            # (The columns a line after the paragraph may reach: those of
            # the list items around the one markdown-it reads it in.)
            reach_cols = tuple(sorted({0, col} | {c for c in open_cols if c < col}))
            nxt = block_at.get(at)
            # (Read with the quote markers the parse moved: such a marker
            # opens a quote in both renderers, which ends the paragraph.)
            if md_breaks(view[at], level, col):
                continue
            # The paragraph markdown-it reads (from its first line, over the
            # lines it continues it on up to a blank line or a line that
            # interrupts it) is a prose unit of the block where it starts,
            # so its inline markup, code, HTML and links are compared as
            # markdown-it groups them.
            # (The block that holds its first line, which may start
            # earlier, such as a paragraph whose first lines markdown-it
            # reads as a heading; the unit is compared whatever its kind.)
            pos = bisect.bisect_right(starts, first) - 1
            owner = block_at[starts[pos]] if pos >= 0 else (block_at[starts[0]] if starts else None)
            # (Not where the line ends the paragraph for markdown-it too: a
            # blank line once its quote markers are removed, a block start
            # inside the paragraph's container, or a list item outside it.
            # Trailing whitespace stays: it may be inside a code span.)
            if owner is not None and not ends and at >= covered:
                k = at
                while (k < n and _quote_depth(view[k])[1].strip()
                       and (k == at or not (md_breaks(view[k], level, col) or (
                           para_end is not None and _mdit_ends_paragraph(view[k], level, *para_end))))
                       and not (k > first and setext_at(k, level, col))):
                    k += 1
                covered = k
                for x in range(at, k):
                    run_line[x] = True
                if k < n and k > first and setext_at(k, level, col):
                    # A setext underline ends markdown-it's paragraph as a
                    # heading, and markdown-it reads the lines after it anew,
                    # as blocks of their own, where cmark-gfm may continue a
                    # paragraph. The underline is kept byte for byte by the
                    # block that holds it, and so is what markdown-it reads
                    # there before a paragraph starts (read from the list
                    # item's content column, or past the quote markers):
                    # indented code, definitions (whose labels may then be
                    # defined), an HTML block (to a blank line) or any other
                    # block (to the end of the lines cmark-gfm may continue
                    # its paragraph on).
                    hold = bisect.bisect_right(starts, k) - 1
                    holder = block_at[starts[hold]] if hold >= 0 else None
                    kept = [written[k]]
                    x = y = k + 1
                    while (y < n and _quote_depth(written[y])[1].strip()
                           and not md_breaks(written[y], level, col)):
                        y += 1
                    after = []
                    for z in range(x, y):
                        body = _expand_indent(_strip_quote(written[z], level))
                        after.append(body[col:] if col and _indent_of(body) >= col else body)
                    if x < y:
                        # (Whether the line after the underline keeps the
                        # quote markers and reaches the column of the
                        # container markdown-it reads it in: it starts a
                        # block there, which no lazy line may continue.)
                        body = _expand_indent(_strip_quote(written[x], level))
                        kept.append("\x01%d:%s" % (_quote_depth(written[x])[0],
                                                    "%s,%s" % _column_bucket(_indent_of(body), reach_cols)
                                                    if body.strip() else "blank"))
                    z = x
                    while z < y:
                        body = after[z - x]
                        stripped = body.lstrip(" ")
                        if _indent_of(body) >= 4:
                            kept.append(written[z])
                            z += 1
                            continue
                        if _is_html_start(stripped):
                            # (To a line that is blank at the run's quote
                            # depth: a line of only quote markers deeper
                            # than that is text of the block.)
                            while (z < n and _quote_depth(written[z])[0] >= level
                                   and _strip_quote(written[z], level).strip()):
                                kept.append(written[z])
                                z += 1
                            break
                        defs_end = z
                        if stripped.startswith("["):
                            # (The definitions markdown-it reads from there.)
                            for r in _mdit_reading(after[z - x:], 0):
                                if r[0] != "definition":
                                    break
                                kept.extend(written[z + r[1]:z + r[2]])
                                defs_end = z + r[2]
                                if holder is not None:
                                    holder.md_label = tuple(holder.md_label or ()) + (r[3],)
                        if defs_end == z:
                            break
                        z = defs_end
                    # (How that stretch ends: at a paragraph markdown-it
                    # starts, a blank line, or a line that interrupts the run,
                    # with its quote depth.)
                    kept.append("\x02" + ("p" if z < y else "b" if z >= n or not _quote_depth(written[z])[1].strip()
                                           else "%d" % _quote_depth(written[z])[0]))
                    if holder is not None:
                        holder.attrs["md_underline"] = holder.attrs.get("md_underline", ()) + (
                            hashlib.sha256("\n".join(kept).encode("utf-8", "surrogatepass")).hexdigest()[:32],)
                elif col and k < n:
                    # markdown-it reads the lines after that paragraph from
                    # the content column of the list item it is still in,
                    # where cmark-gfm may be in a deeper one: indented code
                    # (four columns past that column, with no paragraph
                    # open) is kept byte for byte, and so is a fence or an
                    # HTML block from where it starts, up to the line that
                    # leaves that item.
                    m = k
                    mpara = False
                    while m < n and _quote_depth(written[m])[0] == level:
                        body = _expand_indent(_strip_quote(written[m], level))
                        if not body.strip():
                            mpara = False
                            m += 1
                            continue
                        if _indent_of(body) < col:
                            break
                        end = md_block_end(m, level, col, mpara)
                        if end > m:
                            for x in range(m, end):
                                md_kept[x] = level
                            mpara = False
                            m = end
                            continue
                        inner = body[col:]
                        stripped = inner.lstrip(" ")
                        if not (mpara and not _mdit_interrupts(inner, 0)):
                            mpara = not (ATX_RE.match(stripped) or HR_RE.match(stripped))
                        m += 1
                # (The whitespace at the start of each line after the first
                # stays as written: markdown-it keeps what lies past the
                # paragraph's column inside a code span or raw HTML.)
                heads = [_strip_quote(lines[x], _quote_depth(lines[x])[0]) for x in range(first, at)]
                if heads:
                    heads[0] = heads[0].lstrip(" \t")
                if marker_first and heads:
                    # (The text of a list item only markdown-it opens.)
                    mark = _MDIT_LIST_START_RE.match(heads[0])
                    heads[0] = heads[0][mark.end():].lstrip(" \t") if mark else heads[0]
                text = "\n".join(heads + [_strip_quote(written[x], level) for x in range(at, k)])
                owner.md_units = (owner.md_units or []) + [text]
                if (first, at) in md_unit_pre:
                    # (With the paragraph before the range, which markdown-it
                    # may continue into it.)
                    pre = [_strip_quote(lines[x], _quote_depth(lines[x])[0])
                           for x in range(md_unit_pre[(first, at)], first)]
                    pre[0] = pre[0].lstrip(" \t")
                    owner.md_units = owner.md_units + ["\n".join(pre + [text])]
                # (How many of cmark-gfm's blocks it spans: a blank line that
                # ends it earlier moves the rest out of markdown-it's
                # paragraph.)
                owner.attrs["md_runs"] = owner.attrs.get("md_runs", ()) + (
                    bisect.bisect_left(starts, k) - bisect.bisect_left(starts, first),)
                if col and k < n:
                    # (Where the line that ends it, or the first line after
                    # the blank lines that end it, stands against the
                    # content column of the list item markdown-it reads it
                    # in: inside that item or not, and whether it is
                    # indented code there, where cmark-gfm may have closed
                    # the item earlier.)
                    z = k
                    while z < n and not _quote_depth(written[z])[1].strip():
                        z += 1
                    if z < n:
                        # (markdown-it continues a quote at a quote marker
                        # after any indentation.)
                        depth = re.match(r"(?:[ \t]*>)*", view[z]).group(0).count(">")
                        body = _expand_indent(view[z][_loose_quote_end(view[z], min(depth, level)):])
                        # (A line with fewer quote markers is outside the
                        # quote that holds the list item.)
                        owner.attrs["md_item_after"] = owner.attrs.get("md_item_after", ()) + (
                            (depth,) + (_column_bucket(_indent_of(body), (0, col)) if depth >= level else ()),)
            if nxt is None or nxt.kind != "html":
                continue
            last = min(n, at + nxt.raw.count("\n") + 1)
            for k in range(at + 1, last):
                # From the first line that interrupts markdown-it's
                # paragraph there (a fence or raw HTML that may run on).
                st = _strip_quote(view[k], _quote_depth(view[k])[0]).lstrip(" ")
                if st and _indent_of(_strip_quote(view[k], _quote_depth(view[k])[0])) < 4 and (
                        FENCE_RE.match(st) or _is_html_start(st, interrupt=True)):
                    freeze_run(k, last)
                    drain()
                    break
    for start, end in md_run_from + md_unknown_from:
        freeze_run(start, end)
        drain()
    for start, end, fence, depth in md_html_run:
        freeze_run(start, end, html=fence is None, fence=fence, open_depth=depth)
        drain()
    if any(lazy_line):
        for block in blocks:
            if lazy_line[block.line - 1] and block.kind in ("refdef", "paragraph", "heading", "html"):
                if block.kind == "refdef" and block.ref and block.ref[2]:
                    block.ref = block.ref[:3] + (False,)
                labels = [mdit_label_key(label) for label in _loose_labels(block.raw)]
                if labels:
                    block.md_label = tuple(block.md_label or ()) + tuple(labels)
    if math_chain is not None:
        md_list_freeze.append(math_chain[0])
    # A list markdown-it opens where cmark-gfm reads a paragraph is kept byte
    # for byte, quote markers and indentation included, from its first line
    # to the first line after a blank line (spaces and tabs only) that
    # starts at the left margin with no quote or list marker: both renderers
    # have closed every container there. When those lines hold a fence or an
    # HTML block that may run on over blank lines, to the end of the
    # document. A line the guard's reading takes as blank and the renderers
    # do not (see _odd_blank) is kept the same way with the lines around it,
    # from the first line after the blank line before it.
    # (Each line is read once: a start inside a region kept already ends
    # where that region ends.)
    after_blank = 0
    for k in range(n):
        if _md_blank(src_lines[k]):
            after_blank = k + 1
        elif _odd_blank(src_lines[k]):
            md_list_freeze.append(after_blank)
    covered = 0
    for first in sorted(md_list_freeze):
        if first < covered:
            continue
        end = n
        runs_on = False
        x = first
        while x < n:
            line = src_lines[x]
            if (x > first and _md_blank(src_lines[x - 1]) and not _md_blank(line) and line[0] not in " \t>"
                    and not re.match(r"(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)", line)):
                end = x
                break
            # (The text past any quote and list markers.)
            text = re.sub(r"^(?:[ \t]*(?:>|(?:[-+*]|[0-9]{1,9}[.)])(?=[ \t]|$)))*[ \t]*", "", line)
            if _fence_opener(text) or (_is_html_start(text) and _html_end_marker(text) is not None):
                runs_on = True
            x += 1
        covered = n if runs_on else end
        for x in range(first, covered):
            md_kept[x] = 0
    if any(depth is not None for depth in md_kept):
        # (Each kept line is recorded in the block that starts last at or
        # before it, as its bytes past the quote markers of the container
        # markdown-it reads it in, and how many of those it has: a further
        # marker is text of the block there.)
        heads = sorted(block_at)
        kept_by = {}
        for k in range(n):
            if md_kept[k] is not None and heads:
                hold = block_at[heads[max(0, bisect.bisect_right(heads, k) - 1)]]
                depth = min(md_kept[k], _quote_depth(view[k])[0])
                # (Whether it follows the previous kept line directly: a
                # run of kept lines may move with the prose before it.)
                kept_by.setdefault(id(hold), [hold, []])[1].append(
                    "%s%d:%s" % ("+" if k and md_kept[k - 1] is not None else "|", depth,
                                 src_lines[k][_loose_quote_end(src_lines[k], depth):]))
        for hold, kept in kept_by.values():
            hold.attrs["md_kept"] = hashlib.sha256(
                "\n".join(kept).encode("utf-8", "surrogatepass")).hexdigest()[:32]
        for block in blocks:
            if md_kept[block.line - 1] is not None:
                # (A block markdown-it reads as code or HTML from its first
                # line defines nothing there.)
                if block.kind == "refdef" and block.ref and block.ref[2]:
                    block.ref = block.ref[:3] + (False,)
                labels = [mdit_label_key(label) for label in _loose_labels(block.raw)]
                if labels:
                    block.md_label = tuple(block.md_label or ()) + tuple(labels)
    if any(raw_line):
        for block in blocks:
            if raw_line[block.line - 1]:
                block.attrs["markdown_it_raw"] = hashlib.sha256(
                    block.raw.encode("utf-8", "surrogatepass")).hexdigest()[:32]
                if block.kind == "refdef" and block.ref and block.ref[2]:
                    block.ref = block.ref[:3] + (False,)
                labels = [mdit_label_key(label) for label in _loose_labels(block.raw)]
                if labels:
                    block.md_label = tuple(block.md_label or ()) + tuple(labels)
    if _md_lines is not None:
        # (For _mask_code: the lines markdown-it may read otherwise, kept
        # byte for byte, read as another kind inside cmark-gfm's paragraph,
        # read as raw HTML or code, or continuing a paragraph over blocks
        # cmark-gfm reads there: see md_lazy_run.)
        _md_lines[:] = [md_kept[k] is not None or raw_line[k] or run_line[k] or over_line[k] or fn_line[k]
                        for k in range(n)]
    return blocks


def normalize_label(label):
    """A link label as cmark-gfm matches it: case-folded, with runs of
    spaces, tabs and line ends collapsed and the ends trimmed (other
    whitespace is text)."""
    return " ".join(re.split(r"[ \t\n\r]+", label.strip(LABEL_SPACE))).casefold()


def mdit_label_key(label):
    """A link label as markdown-it matches it: every kind of whitespace
    trimmed and collapsed, then lowered and uppercased. Empty when
    markdown-it takes it as no label."""
    return re.sub(r"\s+", " ", label.strip()).lower().upper()


def reference_labels(blocks):
    """The link reference labels a document defines, as (definite, possible)
    for cmark-gfm followed by (definite, possible) for markdown-it: labels
    of definitions the parser read, and labels that may be defined (in a
    polish:off region, front matter, a footnote, a definition the parser could not read
    in full, or a definition-like line at the start of a paragraph that
    markdown-it may read as a definition, such as one with a label over
    1000 bytes)."""
    definite, possible = set(), set()
    md_definite, md_possible = set(), set()
    for block in blocks:
        _add_block_labels(block, definite, possible, md_definite, md_possible)
    md_possible.discard("")
    return definite, possible - definite, md_definite, md_possible - md_definite


def reference_label_sequence(blocks):
    """The labels each block may define, in document order: which of two
    definitions of one label comes first decides the link target, so this
    order is compared as well as the label sets."""
    out = []
    for block in blocks:
        sets = (set(), set(), set(), set())
        _add_block_labels(block, *sets)
        sets[3].discard("")
        if any(sets):
            out.append((block.kind,) + tuple(tuple(sorted(s)) for s in sets))
    return out


def _add_block_labels(block, definite, possible, md_definite, md_possible):
    """Add the labels ``block`` defines or may define (see reference_labels)."""
    if block.kind == "refdef" and block.ref:
        (definite if block.ref[1] else possible).add(block.ref[0])
        if block.ref[2]:
            (md_definite if block.ref[1] and block.ref[3] else md_possible).add(block.ref[2])
    elif block.kind in ("protected", "footnote_def", "frontmatter"):
        # (Front matter is Markdown to the renderers that do not read
        # it as metadata.)
        for label in _loose_labels(block.raw):
            possible.add(normalize_label(label))
            md_possible.add(mdit_label_key(label))
    elif block.kind == "html":
        # Raw text to cmark-gfm, but markdown-it may read some of its
        # lines as Markdown (it starts fewer HTML blocks).
        for label in _loose_labels(block.raw):
            md_possible.add(mdit_label_key(label))
    elif block.kind == "paragraph":
        # Definitions are read only from the start of a paragraph.
        for label in _loose_labels(block.raw, first_only=True):
            md_possible.add(mdit_label_key(label))
        for line in block.raw.split("\n"):
            m = LOOSE_REFDEF_RE.match(line)
            if not m:
                break
            md_possible.add(mdit_label_key(m.group(1)))
    # A paragraph or heading that starts with definitions only markdown-it
    # takes (kept byte for byte) defines their labels there.
    if block.md_label:
        md_possible.update(block.md_label)


def prose_block_count(text):
    return len([b for b in parse_blocks(text)
                if b.kind not in RAW_KINDS and any(u.strip() for u in b.units)])


def _md_runs_on(body, after, resolve=None):
    """Whether a code span, raw HTML, an autolink, math or a link tail that
    opens in ``body`` runs on into ``after`` when markdown-it reads them as
    one paragraph (in any reading, see _all_readings; also where the
    readings are unknown)."""
    cut = len(body)
    readings = _all_readings(body + "\n" + after, resolve)
    if readings is None:
        return True
    for _, constructs in readings:
        if any(start < cut < end for _, start, end, _ in constructs):
            return True
    return False


def _renderer_readings(text, resolve=None, readings=None):
    """(reading, constructs) for every reading of ``text`` (see
    _inline_readings, whose result ``readings`` may already hold) as the
    renderers read it: TeX math is text to both, so "\\(" and "\\[" are
    escapes and the code spans, raw HTML, links and escapes inside it count.
    ``readings`` itself where the text holds no math."""
    if readings is None:
        readings = _inline_readings(text, resolve)
    if not any(c[0] == "math" for _, constructs in readings for c in constructs):
        return readings
    return _inline_readings(text, resolve, True)


def _all_readings(text, resolve=None):
    """The readings of ``text`` with TeX math read as math and those with it
    read as text, as the renderers do, for every combination of the labels
    that may or may not resolve (see _ref_readings): where a construct runs
    or hides a marker, any may be the one that counts. None when they are
    unknown."""
    readings = _ref_readings(text, resolve)
    if readings is None or not any(c[0] == "math" for _, constructs in readings for c in constructs):
        return readings
    tex = _ref_readings(text, resolve, True)
    return None if tex is None else readings + tex


def _renderer_masks(text, resolve=None):
    """(masks, unknown): (masked, link tail starts) for every renderer
    reading of ``text`` (TeX math read as text, every combination of the
    labels that may or may not resolve, see _ref_readings): ``masked`` is
    ``text`` with backslash escapes, code spans, raw HTML, autolinks and
    link tails blanked out (same length), for _delimiter_runs and bracket
    scans: delimiters and brackets there do not count. Where the
    combinations are too many, ``unknown`` is True and all or none of the
    labels resolve."""
    readings = _ref_readings(text, resolve, True)
    unknown = readings is None
    if unknown:
        readings = _inline_readings(text, resolve, True)
    out = []
    for _, constructs in readings:
        chars = list(text)
        tails = set()
        for kind, start, end, _ in constructs:
            if kind == "linktail":
                tails.add(start)
            for x in range(start, end):
                if chars[x] != "\n":
                    chars[x] = " "
        out.append(("".join(chars), tails))
    return out, unknown


def _paired_spans(text, masked, labels, gfm):
    """Emphasis spans (start, end) of ``text`` with delimiter runs found in
    ``masked``; runs inside a link or image text (``labels``, (start, end)
    of the text between the brackets) pair only with each other, innermost
    first, as in emphasis_structure."""
    runs = _delimiter_runs(text, masked, gfm, frozenset(end for _, end in labels))
    bounds = sorted(set(labels), key=lambda lb: (lb[0], -lb[1]))
    groups = {lb: [] for lb in bounds}
    outside = []
    open_labels = []
    li = 0
    for run in runs:
        while li < len(bounds) and bounds[li][0] <= run["pos"]:
            open_labels.append(bounds[li])
            li += 1
        while open_labels and open_labels[-1][1] <= run["pos"]:
            open_labels.pop()
        holder = None
        for lb in reversed(open_labels):
            if lb[0] <= run["pos"] < lb[1]:
                holder = lb
                break
        (groups[holder] if holder is not None else outside).append(run)
    spans = []
    for lb in sorted(bounds, key=lambda lb: lb[1] - lb[0]):
        _pair_delimiters(groups[lb], spans, {}, gfm)
    _pair_delimiters(outside, spans, {}, gfm)
    return [(a, b) for a, b, _ in spans]


def _emphasis_spans(text, resolve=None):
    """The emphasis and strikethrough spans (start, end) of ``text`` read as
    one paragraph, in every renderer reading (see _renderer_masks), with the
    text of an inline link or image read on its own (link text that holds a
    link, also inside an image, is no link), and that of a bracket pair
    that may be a reference both ways: the pairs that may resolve together
    (the same labels) are read each way in every combination, up to
    MAYBE_LABEL_GROUPS such groups; past that, a span also runs from the
    first delimiter to the last, as it does where the readings are unknown
    (see _renderer_masks). A bracket pair none of whose labels ``resolve``
    (see _doc_label_resolver; None: any may resolve) may resolve is no
    reference."""
    out = []
    masks, unknown = _renderer_masks(text, resolve)
    if unknown:
        marks = [x for x, ch in enumerate(text) if ch in "*_~"]
        if marks:
            out.append((marks[0], marks[-1] + 1))
    for masked, tails in masks:
        closes = {}
        stack = []
        for x, ch in enumerate(masked):
            if ch == "[":
                stack.append(x)
            elif ch == "]" and stack:
                closes[stack.pop()] = x
        groups = {}
        for o, x in closes.items():
            if x + 1 in tails:
                continue
            names = [text[o + 1:x]]
            if x + 1 in closes:
                # ("[text][label]": the label decides, or the text where it
                # is empty; the text is looked up too.)
                names.insert(0, text[x + 2:closes[x + 1]])
            names = [name for name in names if name.strip()]
            if not re.search(r"[*_~]", masked[o + 1:x]) or (
                    resolve is not None and all(resolve(name) == "no" for name in names)):
                # (A pair with no delimiter inside pairs nothing either way.)
                continue
            # (Grouped by the label that decides, so that the text and the
            # label of one reference resolve together.)
            groups.setdefault(normalize_label(names[0]) if names else "", set()).add(o)
        found = list(groups.values())
        if len(found) <= MAYBE_LABEL_GROUPS:
            choices = [set().union(*(g for b, g in enumerate(found) if pick >> b & 1))
                       for pick in range(1 << len(found))]
        else:
            choices = [set(), set().union(*found)]
            marks = [x for x, ch in enumerate(masked) if ch in "*_~"]
            if marks:
                out.append((marks[0], marks[-1] + 1))
        for chosen in choices:
            labels = []
            open_at = []
            inner = {}
            for x, ch in enumerate(masked):
                if ch == "[":
                    open_at.append(x)
                    inner[x] = False
                elif ch == "]" and open_at:
                    o = open_at.pop()
                    image = o > 0 and masked[o - 1] == "!"
                    holds = inner.pop(o)
                    link = (x + 1 in tails or o in chosen) and (image or not holds)
                    if link:
                        labels.append((o + 1, x))
                    if open_at:
                        # (A link deactivates the brackets open around it.)
                        inner[open_at[-1]] = inner[open_at[-1]] or holds or (link and not image)
            for gfm in (True, False):
                out.extend(_paired_spans(text, masked, labels, gfm))
    return out


def _md_emphasis_runs_on(body, after, resolve=None):
    """Whether emphasis or strikethrough pairs a delimiter in ``body`` with
    one in ``after`` when they are read as one paragraph (any reading; see
    _emphasis_spans for ``resolve``)."""
    cut = len(body)
    return any(a < cut < b for a, b in _emphasis_spans(body + "\n" + after, resolve))


def _md_table_crosses(before, rows, after, resolve=None):
    """The indices of the lines (``before`` + ``rows`` + ``after``, which
    markdown-it reads as one paragraph) where markdown-it's reading crosses
    what cmark-gfm reads apart in a table's ``rows``: a code span, raw
    HTML, an autolink, math, a link tail or emphasis that spans a row end
    or an unescaped pipe of a row covers the lines from its start to its
    end; a cell that leaves a "[" open, its row and every line after it
    (see _emphasis_spans for ``resolve``)."""
    lines = before + rows + after
    text = "\n".join(lines)
    cuts = []
    starts = []
    touched = set()
    open_from = None
    pos = 0
    for k, line in enumerate(lines):
        starts.append(pos)
        if pos:
            cuts.append(pos - 1)
        if len(before) <= k < len(before) + len(rows):
            for x, ch in enumerate(line):
                if ch == "|" and (x == 0 or line[x - 1] != "\\"):
                    cuts.append(pos + x)
            if open_from is None and any(_md_open_bracket(cell, resolve) for cell in _split_cells(line)):
                open_from = k
        pos += len(line) + 1
    if open_from is not None:
        touched.update(range(open_from, len(lines)))
    cuts.sort()

    def mark(a, b):
        c = bisect.bisect_right(cuts, a)
        if c < len(cuts) and cuts[c] < b:
            touched.update(range(bisect.bisect_right(starts, a) - 1, bisect.bisect_right(starts, b - 1)))

    readings = _all_readings(text, resolve)
    if readings is None:
        # (Unknown readings: every line may be crossed.)
        return set(range(len(lines)))
    for _, constructs in readings:
        for kind, start, end, _ in constructs:
            if kind != "escape":
                mark(start, end)
    for a, b in _emphasis_spans(text, resolve):
        mark(a, b)
    return touched


def _md_open_bracket(text, resolve=None):
    """Whether ``text`` leaves a "[" open as the renderers read it (in any
    reading, see _renderer_masks; also where they are unknown): brackets in
    code spans, raw HTML, autolinks, link tails and escapes do not count."""
    masks, unknown = _renderer_masks(text, resolve)
    return unknown or any(_open_bracket(masked) for masked, _ in masks)


def _open_bracket(text):
    """Whether ``text`` leaves a "[" open (not closed by a later "]";
    backslash escapes skipped)."""
    depth = 0
    x = 0
    while x < len(text):
        if text[x] == "\\":
            x += 1
        elif text[x] == "[":
            depth += 1
        elif text[x] == "]" and depth:
            depth -= 1
        x += 1
    return depth > 0


def _md_starts_anew(lines, k, prev_block):
    """Whether markdown-it reads line ``k`` with no paragraph open, as far as
    the lines before it tell: it is the first line, the line before it is
    blank, raw HTML of types 1 to 5 (such as a marker) ends on that line in
    the block before it (``prev_block``), or line ``k`` opens a quote or a
    list item that ends a paragraph markdown-it may have open there (one at
    the deepest quote depth of the lines since the last blank line)."""
    if k == 0:
        return True
    prev = _strip_quote(lines[k - 1], _quote_depth(lines[k - 1])[0])
    if not prev.strip(" \t"):
        return True
    if prev_block is not None and prev_block.kind == "html" and prev_block.line + prev_block.raw.count("\n") == k:
        head = prev_block.raw.split("\n")[0]
        head = _strip_quote(head, _quote_depth(head)[0]).lstrip(" ")
        marker = _html_end_marker(head)
        if marker is not None and marker.search(prev):
            return True
    own, own_body = _quote_depth(lines[k])
    if _mdit_interrupts(lines[k], own):
        # (It ends a paragraph at its own depth, so at any depth.)
        return True
    marked = bool(re.match(r"[ \t]*(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)", own_body))
    level = 0
    for x in range(k - 1, max(-1, k - 1 - MD_ANEW_LOOKBACK), -1):
        depth, body = _quote_depth(lines[x])
        if not body.strip(" \t"):
            break
        level = max(level, depth)
        if level > own or (level == own and not marked):
            # (The deeper lines further back no longer change the answer.)
            break
    else:
        if k - 1 - MD_ANEW_LOOKBACK >= 0:
            # (Too far to look back: a paragraph may be open.)
            return False
    return _mdit_interrupts(lines[k], level)


# Container markers at the start of a footnote definition's first line,
# which may be a list item's or a quote's first line.
_FIRST_LINE_MARKERS_RE = re.compile(r"^(?:[ \t]*(?:>|(?:[-+*]|[0-9]{1,9}[.)])(?=[ \t]|$)))*[ \t]*")


def _footnote_label_line(line):
    """The first line of a footnote definition from its label on, past the
    quote and list markers in front of it (None when no label is there)."""
    rest = line[_FIRST_LINE_MARKERS_RE.match(line).end():]
    return rest if FOOTNOTE_DEF_RE.match(rest) else None


def _footnote_content(block_lines, quote, base):
    """The content of a footnote definition as cmark-gfm reads it, by line:
    (column where it starts in the line, content). The first line's content
    follows the label; a line indented four columns past the definition's
    container is content from there; any other line is a lazy line or blank.
    The column is None where the content is not the end of the line as
    written (past an expanded tab), on a lazy line that is not plain text,
    and on a first line without a label after its container markers."""
    out = []
    for k, line in enumerate(block_lines):
        depth = _quote_depth(line)[0]
        body = _strip_quote(line, min(depth, quote))
        if k == 0:
            labelled = _footnote_label_line(line)
            if labelled is None:
                out.append((None, line))
                continue
            text = labelled[FOOTNOTE_DEF_RE.match(labelled).end():].lstrip(" \t")
        elif not body.strip():
            text = ""
        elif depth >= quote and _indent_of(_expand_indent(body)) - base >= 4:
            text = _past_container(body, base + 4)
        else:
            text = body.lstrip(" \t")
            if not _plain_text_line(text):
                # (A lazy line continues the paragraph as text, but read
                # again inside the content it could start a block or end
                # the paragraph, such as an underline: not placed.)
                out.append((None, text))
                continue
        out.append((len(line) - len(text) if line.endswith(text) else None, text))
    return out


# Footnote definitions read inside each other for markers (see _mask_code);
# deeper ones are read conservatively.
FOOTNOTE_MASK_DEPTH = 8


def _hidden_brackets(text, readings):
    """(start, end) of each bracket pair in ``text`` whose text no renderer
    emits as written: an image's text (alt text: cmark-gfm escapes a
    comment there and markdown-it drops it) and the label of an explicit
    reference ("[text][label]"), in any of its ``readings`` (see
    _all_readings). Brackets in code spans, raw HTML, autolinks, link tails
    (destinations and titles) and escapes of that reading do not count; a
    pair that is no image or reference after all is read the conservative
    way."""
    out = set()
    for _, constructs in readings:
        skip = {}
        for kind, start, end, _ in constructs:
            if kind in ("code", "html", "autolink", "linktail", "escape"):
                skip[start] = end
        stack = []
        x = 0
        while x < len(text):
            if x in skip:
                x = skip[x]
                continue
            if text[x] == "[":
                stack.append(x)
            elif text[x] == "]" and stack:
                o = stack.pop()
                if o and (text[o - 1] == "]" or (text[o - 1] == "!" and skip.get(o - 2) != o)):
                    out.add((o, x + 1))
            x += 1
    return sorted(out)


def _marker_masks(text, resolve=None):
    """``text`` (inline content, its lines joined) masked for markers as
    two texts of the same length (see _mask_code). In the first, the one to
    find polish:off markers in, NUL characters cover code spans in every
    reading of the text and a backslash-escaped "<". In the second, the one
    to find polish:on markers in, they cover code spans in any reading, TeX
    math, inline link destinations and titles, raw HTML that holds a marker
    without being one (an attribute value), and an escaped "<": a comment
    in those is no comment to a renderer, or not one to both. The readings
    are those of _all_readings (TeX math read as math and as text, every
    combination of the labels that may or may not resolve; see ``resolve``
    there); where they are unknown, every polish:off marker counts and no
    polish:on marker does."""
    readings = _all_readings(text, resolve)
    if readings is None:
        return text, "".join(ch if ch == "\n" else "\0" for ch in text)
    every = None
    esc = [False] * len(text)
    hidden = [False] * len(text)
    for start, end in _hidden_brackets(text, readings):
        hidden[start:end] = [True] * (end - start)
    for _, constructs in readings:
        code = [False] * len(text)
        for kind, start, end, value in constructs:
            if kind == "code":
                code[start:end] = [True] * (end - start)
            elif kind in ("math", "linktail") or (kind == "html" and not POLISH_MARKER_RE.fullmatch(value)):
                hidden[start:end] = [True] * (end - start)
            elif kind == "escape" and value.endswith("<"):
                esc[end - 1] = True
        every = code if every is None else [a and b for a, b in zip(every, code)]
        hidden = [a or b for a, b in zip(hidden, code)]
    off = "".join("\0" if ch != "\n" and (every[x] or esc[x]) else ch for x, ch in enumerate(text))
    on = "".join("\0" if ch != "\n" and (hidden[x] or esc[x]) else ch for x, ch in enumerate(text))
    return off, on


def _mask_code(text, segments=False, _depth=0, _resolve=None):
    """``text`` read for markers, as two texts of the same length, one to
    find polish:off markers in and one to find polish:on markers in, with
    code blanked out (NUL characters, which no marker contains), so markers
    in code are text.

    Fenced and indented code blocks come from the block parser, so fences
    behind several list markers count too. Code spans are matched only inside
    one block (or one segment line), because a code span cannot cross a block
    boundary; a stray backtick elsewhere cannot hide a real marker. The blocks
    are read as the renderers read them, with the markers as ordinary
    comments (renamed, same length). The content of a footnote definition is
    read the same way, as cmark-gfm reads it. markdown-it has no footnotes:
    it reads that text as a paragraph, a reference definition or indented
    code, so a polish:on marker counts there only on a line it reads as
    paragraph text; a polish:off marker counts where either renderer reads
    it outside code. Lines whose content cannot be placed (past an expanded
    tab, or more than ``FOOTNOTE_MASK_DEPTH`` definitions deep) are read the
    same conservative way: a polish:off marker in them counts and a
    polish:on marker does not, as does one in a definition's label and in a
    reference definition, front matter or math. In a table, code is read
    both ways (cells first, and the rows with the paragraph right before
    them as paragraph text). Inline text is masked by _marker_masks.
    """
    lines = text.split("\n")
    for_off = list(lines)
    for_on = list(lines)
    # (The reference labels the document may define: a definition's
    # content read on its own takes the document's.)
    resolve = _resolve or _doc_resolver(text)
    footnotes = []
    tables = []
    md_lines = []
    if segments:
        chunks = [(k, k) for k in range(len(lines))]
    else:
        chunks = []
        prev_block = None
        for block in parse_blocks(POLISH_MARKER_RE.sub(r"\1-\2", text),
                                  _md_lines=md_lines if not _depth else None, _resolve=resolve):
            before, prev_block = prev_block, block
            if block.kind == "quote":
                continue
            first = block.line - 1
            last = min(first + block.raw.count("\n"), len(lines) - 1)
            if block.kind in ("fence", "indented_code"):
                for k in range(first, last + 1):
                    for_off[k] = for_on[k] = "\0" * len(lines[k])
            elif block.kind == "footnote_def":
                footnotes.append((first, last, block.attrs.get("quote", 0), block.attrs.get("base", 0),
                                  _md_starts_anew(lines, first, before)))
            elif block.kind in ("refdef", "frontmatter", "math"):
                # (A definition's destination or title, front matter and
                # math hold no comment to cmark-gfm, while markdown-it may
                # read them as paragraph text: a polish:off marker counts
                # there and a polish:on marker does not.)
                for k in range(first, last + 1):
                    for_on[k] = "\0" * len(lines[k])
            elif block.kind in ("table_row", "table_raw", "table_sep"):
                # (The rows of one table, with the paragraph right before
                # it, which markdown-it reads as one paragraph.)
                if (tables and tables[-1][2] == first - 1 and before is not None
                        and before.kind in ("table_row", "table_raw", "table_sep")
                        and before.attrs.get("quote") == block.attrs.get("quote")
                        and before.attrs.get("container") == block.attrs.get("container")):
                    tables[-1][2] = last
                else:
                    lead = first
                    if (before is not None and before.kind == "paragraph"
                            and before.attrs.get("quote") == block.attrs.get("quote")
                            and before.attrs.get("container") == block.attrs.get("container")):
                        b_first = before.line - 1
                        if min(b_first + before.raw.count("\n"), len(lines) - 1) == first - 1:
                            lead = b_first
                    tables.append([lead, first, last])
            elif block.kind not in RAW_KINDS and block.kind != "list_item":
                # (A list item's own blocks are read as such.)
                chunks.append((first, last))
    for first, last in chunks:
        cm_off, cm_on = (part.split("\n") for part in _marker_masks("\n".join(for_off[first:last + 1]), resolve))
        for_off[first:last + 1] = cm_off
        for_on[first:last + 1] = cm_on
        if not any(md_lines[first:last + 1]):
            continue
        # markdown-it reads some of these lines as another kind, so the
        # paragraph text between them is a paragraph of its own to it,
        # whose code spans pair on their own: a polish:off marker counts
        # outside code in either reading, a polish:on marker outside code
        # in both.
        k = first
        while k <= last:
            if md_lines[k]:
                k += 1
                continue
            a = k
            while k <= last and not md_lines[k]:
                k += 1
            md_off, md_on = (part.split("\n") for part in _marker_masks("\n".join(lines[a:k]), resolve))
            for y in range(a, k):
                for_off[y] = "".join(c if c != "\0" else m for c, m in zip(cm_off[y - first], md_off[y - a]))
                for_on[y] = "".join(c if m != "\0" else "\0" for c, m in zip(cm_on[y - first], md_on[y - a]))
    for lead, first, last in tables:
        # A table: cmark-gfm splits each row into cells at unescaped pipes
        # before it reads code spans, markdown-it reads the rows as one
        # paragraph with the paragraph right before them. A polish:on
        # marker counts outside code in both readings, a polish:off marker
        # outside code in either.
        md_off, md_on = (part.split("\n") for part in _marker_masks("\n".join(lines[lead:last + 1]), resolve))
        cm_off, cm_on = for_off[lead:first], for_on[lead:first]
        for row in lines[first:last + 1]:
            row_off, row_on = list(row), list(row)
            cell = x = 0
            while x <= len(row):
                if x == len(row) or row[x] == "|":
                    row_off[cell:x], row_on[cell:x] = _marker_masks(row[cell:x], resolve)
                    cell = x + 1
                elif row[x] == "\\":
                    x += 1
                x += 1
            cm_off.append("".join(row_off))
            cm_on.append("".join(row_on))
        for y in range(lead, last + 1):
            for_off[y] = "".join(c if c != "\0" else m for c, m in zip(cm_off[y - lead], md_off[y - lead]))
            for_on[y] = "".join(c if m != "\0" else "\0" for c, m in zip(cm_on[y - lead], md_on[y - lead]))
    for first, last, quote, base, anew in footnotes:
        block_lines = lines[first:last + 1]
        content = _footnote_content(block_lines, quote, base)
        inner_off = inner_on = None
        if _depth < FOOTNOTE_MASK_DEPTH and all(col is not None for col, _ in content):
            inner_off, inner_on = (part.split("\n") for part in
                                   _mask_code("\n".join(t for _, t in content), _depth=_depth + 1,
                                              _resolve=resolve))
        # markdown-it's reading of the same lines up to the first blank
        # line: where it starts anew there, as it reads them (paragraph text
        # with its own code spans, a reference definition, indented code);
        # otherwise they continue the paragraph open before them, where a
        # code span opened earlier may run on (unknown: a polish:off marker
        # counts and a polish:on marker does not). Past that blank line the
        # definition's lines are indented code to it.
        view = [_past_container(_strip_quote(line, min(quote, _quote_depth(line)[0])), base)
                for line in block_lines]
        view[0] = _footnote_label_line(block_lines[0]) or view[0]
        stop = next((k for k, t in enumerate(view) if not t.strip(" \t")), len(view))
        md_off = ["\0" * len(line) for line in block_lines]
        md_on = list(md_off)
        if _depth:
            # (markdown-it reads only the document's own lines: a definition
            # inside another one is read with the lines of the outer one.)
            md_off = md_on = block_lines
        elif not anew:
            md_off[:stop] = block_lines[:stop]
        readings = _mdit_reading(view[:stop], 0) if anew and not _depth else []
        for r in readings:
            if r[0] not in ("paragraph", "heading"):
                continue
            texts = [view[k].lstrip(" \t") for k in range(r[1], r[2])]
            joined = "\n".join(texts)
            if r is readings[-1] and r[0] == "paragraph" and r[2] == len(view):
                # (markdown-it's paragraph goes on past the definition, into
                # a definition right after it and the lines it continues, so
                # a code span, raw HTML or an image text opened in it may run
                # on there: it is read with those lines. Where a setext
                # underline may end it among them, a polish:on marker in it
                # does not count.)
                after = []
                y = last + 1
                while y < len(lines):
                    text_y = _strip_quote(lines[y], _quote_depth(lines[y])[0])
                    if (not text_y.strip(" \t") or _mdit_interrupts(lines[y], quote)
                            or (base and _indent_of(text_y) < base and LIST_MARKER_START_RE.match(text_y))):
                        # (A list item of the definition's list, or of one
                        # around it, ends the paragraph too.)
                        break
                    after.append(text_y.lstrip(" \t"))
                    y += 1
                if after and (_md_open_bracket(joined, resolve) or _md_runs_on(joined, "\n".join(after), resolve)):
                    if any(SETEXT_LIKE_RE.match(text_y) for text_y in after):
                        for k in range(r[1], r[2]):
                            md_off[k] = block_lines[k]
                            md_on[k] = "\0" * len(block_lines[k])
                        continue
                    joined += "\n" + "\n".join(after)
            part_off, part_on = (part.split("\n") for part in _marker_masks(joined, resolve))
            for k, text_k, p_off, p_on in zip(range(r[1], r[2]), texts, part_off, part_on):
                line = block_lines[k]
                if line.endswith(text_k):
                    md_off[k] = line[:len(line) - len(text_k)] + p_off
                    md_on[k] = line[:len(line) - len(text_k)] + p_on
        for k, (col, _) in enumerate(content):
            line = lines[first + k]
            if inner_off is None:
                for_off[first + k] = line
                for_on[first + k] = "\0" * len(line)
                continue
            cm_off = line[:col] + inner_off[k]
            cm_on = ("\0" * col if k == 0 else line[:col]) + inner_on[k]
            for_off[first + k] = "".join(a if a != "\0" else b for a, b in zip(cm_off, md_off[k]))
            for_on[first + k] = "".join(a if b != "\0" else "\0" for a, b in zip(cm_on, md_on[k]))
    for k, flag in enumerate(md_lines[:len(lines)]):
        if flag:
            # (A line markdown-it may read otherwise, as code or raw HTML
            # where cmark-gfm reads prose or the reverse: a polish:off
            # marker counts there and a polish:on marker does not.)
            for_off[k] = lines[k]
            for_on[k] = "\0" * len(lines[k])
    return "\n".join(for_off), "\n".join(for_on)


def protected_slices(text, segments=False):
    """Exact source slices covered by polish:off regions, in order.

    A region runs from a polish:off marker to the next polish:on marker, or to
    the end of the text when it is never closed. Markers inside code are text
    (see _mask_code).
    """
    if not POLISH_OFF_RE.search(text):
        # (Masking only hides markers: no marker, no region.)
        return []
    for_off, for_on = _mask_code(text, segments)
    slices = []
    pos = 0
    while True:
        m = POLISH_OFF_RE.search(for_off, pos)
        if not m:
            break
        e = POLISH_ON_RE.search(for_on, m.end())
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
    if "\r" in source:
        # Line endings that are CRLF throughout read as line feeds; mixed
        # line endings and bare carriage returns, which the renderers also
        # read as line ends, are not supported (the runner does not send
        # such documents either).
        if any(text.count("\r") != text.count("\r\n") or text.count("\n") - text.count("\r\n") > 0
               for text in (source, candidate)):
            raise GuardReject("structure", "mixed line endings or bare carriage returns are not supported")
        source = source.replace("\r\n", "\n")
        candidate = candidate.replace("\r\n", "\n")
    check_regions(source, candidate)
    if POLISH_MARKER_RE.search(source) or POLISH_MARKER_RE.search(candidate):
        # The regions are byte-identical now. To the renderers the markers
        # are plain HTML comments, and a region's boundary cannot change how
        # they read the lines around it (a fence or HTML block running past a
        # polish:on marker, the line a marker starts, a list item opened
        # inside a region), so the rest is compared as they read it, with the
        # markers renamed to ordinary comments of the same length.
        # (With a separator that no comment in either text has there, so the
        # renaming can be undone: a literal "polish-off" comment in code
        # stays different from a renamed marker.)
        both = source + "\n" + candidate
        sep = next((ch for ch in "-_.=+~^" if not re.search(
            r"<!--\s*polish" + re.escape(ch) + r"o(?:n|ff)\s*-->", both)), None)
        if sep is None:
            raise GuardReject("structure", "comments that look like renamed polish markers are not supported")
        source = POLISH_MARKER_RE.sub(lambda m: m.group(1) + sep + m.group(2), source)
        candidate = POLISH_MARKER_RE.sub(lambda m: m.group(1) + sep + m.group(2), candidate)
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
    # the candidate too (a changed definition is rejected below); the labels
    # markdown-it may define elsewhere (in lines it reads differently) must
    # stay the same.
    refs = reference_labels(src_blocks)
    if (reference_labels(cand_blocks) != refs
            or reference_label_sequence(cand_blocks) != reference_label_sequence(src_blocks)):
        raise GuardReject("structure", "the reference labels the renderers may define changed")
    total_src = 0
    total_cand = 0
    for a, b in zip(src_blocks, cand_blocks):
        where = a.describe()
        if a.kind != b.kind:
            raise GuardReject("structure", "%s: candidate has %s" % (where, b.kind))
        if a.attrs != b.attrs:
            raise GuardReject("structure", "%s: attributes changed from %r to %r" % (where, a.attrs, b.attrs))
        # (Also for a raw block, such as a definition, where markdown-it's
        # paragraph starts: the unit runs past its bytes.)
        if len(a.md_units or ()) != len(b.md_units or ()):
            raise GuardReject("structure", "%s: the paragraphs markdown-it reads past it changed" % where)
        for su, cu in zip(a.md_units or (), b.md_units or ()):
            compare_prose(su, cu, where + " (as markdown-it reads it)", block_ratio, refs=refs)
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
