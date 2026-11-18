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
# Inline math: "$x + y$", and digit-leading math without spaces such as "$2x$".
# Digit-leading spans with spaces are left alone so prices like "$5 or $10"
# stay prose (their numbers are still protected as digit tokens).
INLINE_MATH_RE = re.compile(
    r"(?<![\\$\w])\$(?:(?=[^\s$\d])[^$\n]*?(?<=\S)|(?=\d)[^\s$]+)\$(?!\w)")
AUTOLINK_RE = re.compile(
    r"<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*|[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+)>")
LINK_RE = re.compile(
    r"(!?)\[((?:\\.|[^\[\]\\]|\[(?:\\.|[^\[\]\\])*\])*)\]"
    r"\(\s*(<[^<>\n]*>|(?:\\.|[^\s()\\]|\((?:\\.|[^\s()\\])*\))*)"
    r"(\s+(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\((?:\\.|[^()\\])*\)))?\s*\)")
REF_LINK_RE = re.compile(r"(!?)\[((?:\\.|[^\[\]\\])+)\]\[((?:\\.|[^\[\]\\])*)\]")
FOOTNOTE_REF_RE = re.compile(r"\[\^[^\]\s]+\]")
# Any other bracketed text may be a shortcut reference link whose label is
# its text, so it is protected as a whole.
SHORTCUT_REF_RE = re.compile(r"!?\[(?:\\.|[^\[\]\\])+\](?![(\[])")
HTML_TAG_RE = re.compile(
    r"<!--.*?-->|</?[A-Za-z][A-Za-z0-9-]*(?:\s+[^<>]*?)?\s*/?>", re.S)
ENTITY_RE = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]{1,31}|#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6});")
URL_RE = re.compile(r"\b(?:https?|ftp|file)://[^\s<>\"'`]+|\bwww\.[^\s<>\"'`]+")

WORD_TOKEN_RE = re.compile(
    r"""
      (?P<path>(?<![\w./~-])(?:~|\.{1,2})?/?[\w@+.-]+(?:/[\w@+.-]*)+)
    | (?P<call>[A-Za-z_][\w.]*\(\))
    | (?P<scope>[A-Za-z_]\w*(?:::\w+)+)
    | (?P<flag>(?<![\w-])--[A-Za-z0-9][\w-]*)
    | (?P<var>(?<![\w$])\$\{?[A-Za-z_]\w*\}?)
    | (?P<ident>__\w+__|\w+(?:_\w+)+|(?<!\w)_+[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*(?!\w))
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

# Slash pairs that are ordinary prose rather than paths.
PROSE_SLASH_PAIRS = frozenset(["and/or", "either/or", "he/she", "his/her", "him/her", "s/he"])
# Dotted abbreviations made of one-letter segments that are ordinary prose.
PROSE_ABBREVIATIONS = frozenset(["e.g", "i.e", "a.k.a", "n.b", "p.s", "a.m", "p.m", "u.s", "u.k"])
# Emphasis delimited by underscores, such as "_word_" or "__two words__".
UNDERSCORE_EMPHASIS_RE = re.compile(r"(?<![\w\\])(_{1,2})(?=[^\s_])(?:(?!\1).)+?(?<=[^\s_])\1(?!\w)")
MARKUP_TOKEN_KINDS = ("tag", "link", "image", "reflink", "autolink", "footnote")


def _mask(chars, start, end):
    for k in range(start, end):
        if chars[k] != "\n":
            chars[k] = " "


def _normalize_tag(tag):
    """Collapse whitespace in a tag outside quoted attribute values."""
    parts = re.split(r"(\"[^\"]*\"|'[^']*')", tag)
    for k in range(0, len(parts), 2):
        parts[k] = re.sub(r"\s+", " ", parts[k])
    return "".join(parts)


def _strip_url(url):
    url = url.rstrip(".,;:!?'\"")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1].rstrip(".,;:!?'\"")
    return url


def extract_tokens(text):
    """Return (tokens, masked) for a prose fragment.

    ``tokens`` is an ordered list of (kind, value) pairs. ``masked`` is the
    text with every token replaced by spaces, so the remaining characters are
    the editable prose.
    """
    chars = list(text)
    found = []

    def current():
        return "".join(chars)

    for m in CODE_SPAN_RE.finditer(current()):
        found.append((m.start(), "code", m.group(2)))
        _mask(chars, m.start(), m.end())

    for m in INLINE_MATH_RE.finditer(current()):
        found.append((m.start(), "math", m.group(0)))
        _mask(chars, m.start(), m.end())

    for m in AUTOLINK_RE.finditer(current()):
        found.append((m.start(), "autolink", m.group(0)))
        _mask(chars, m.start(), m.end())

    for m in LINK_RE.finditer(current()):
        kind = "image" if m.group(1) else "link"
        target = m.group(3) + (m.group(4) or "")
        found.append((m.start(), kind, target.strip()))
        # Keep the link text editable; mask the syntax and the target.
        text_start = m.start(2)
        text_end = m.end(2)
        _mask(chars, m.start(), text_start)
        _mask(chars, text_end, m.end())

    for m in REF_LINK_RE.finditer(current()):
        kind = "reflink"
        if not m.group(3).strip():
            # Collapsed reference "[label][]": the text is the label.
            found.append((m.start(), kind, m.group(0)))
            _mask(chars, m.start(), m.end())
            continue
        found.append((m.start(), kind, (m.group(1) or "") + "[" + m.group(3) + "]"))
        _mask(chars, m.start(), m.start(2))
        _mask(chars, m.end(2), m.end())

    for m in FOOTNOTE_REF_RE.finditer(current()):
        found.append((m.start(), "footnote", m.group(0)))
        _mask(chars, m.start(), m.end())

    for m in SHORTCUT_REF_RE.finditer(current()):
        found.append((m.start(), "reflink", m.group(0)))
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

    found.sort(key=lambda item: item[0])
    tokens = [(kind, value) for _, kind, value in found]
    return tokens, "".join(chars)


def emphasis_counts(masked):
    strong = len(re.findall(r"\*\*|__", masked))
    rest = re.sub(r"\*\*|__", "  ", masked)
    em_star = rest.count("*")
    em_under = len(re.findall(r"(?<!\w)_|_(?!\w)", rest))
    strike = masked.count("~~")
    return (strong, em_star, em_under, strike)


def hard_break_count(text):
    lines = text.split("\n")
    count = 0
    for line in lines[:-1]:
        if line.endswith("  ") or line.endswith("\\"):
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


def compare_prose(src, cand, where, block_ratio=BLOCK_RATIO_BOUNDS, markup_chars=False):
    """Compare one prose unit (a paragraph, heading, list item, cell or segment)."""
    if markup_chars:
        for ch in "<>":
            if cand.count(ch) > src.count(ch):
                raise GuardReject("markup_in_text", "%s: candidate adds %r" % (where, ch))
    src_tokens, src_masked = extract_tokens(src)
    cand_tokens, cand_masked = extract_tokens(cand)
    if src_tokens != cand_tokens:
        idx, x, y = _first_token_difference(src_tokens, cand_tokens)
        kinds = set()
        if x:
            kinds.add(x[0])
        if y:
            kinds.add(y[0])
        reason = "inline_markup" if kinds & set(MARKUP_TOKEN_KINDS) else "protected_token"
        raise GuardReject(
            reason,
            "%s: protected token %d differs (source %r, candidate %r)" % (where, idx + 1, x, y))
    if emphasis_counts(src_masked) != emphasis_counts(cand_masked):
        raise GuardReject("inline_markup", "%s: emphasis markers changed" % where)
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
             "refdef", "hr", "table_sep", "table_raw", "indented_code", "list_fence")

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
REFDEF_RE = re.compile(r"^[ ]{0,3}\[[^\]^][^\]]*\]:[ \t]*\S")
HTML_BLOCK_TAGS = (
    "address|article|aside|blockquote|body|caption|center|col|colgroup|dd|details|dialog|"
    "dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|"
    "header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|"
    "option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|"
    "ul|pre|script|style|textarea|picture|video|audio|canvas|svg|img|source")
HTML_BLOCK_RE = re.compile(
    r"^[ ]{0,3}(?:<(?:!--|!\[CDATA\[|![A-Za-z]|\?)|</?(?:" + HTML_BLOCK_TAGS + r")(?:\s|/?>|$))",
    re.I)
HTML_TYPE1_RE = re.compile(r"<(?:script|pre|style|textarea)(?:\s|>|$)", re.I)
HTML_TYPE1_END_RE = re.compile(r"</(?:script|pre|style|textarea)\s*>", re.I)
HTML_LINE_TAG_RE = re.compile(r"^[ ]{0,3}</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>[ \t]*$")


class Block(object):
    __slots__ = ("kind", "attrs", "raw", "units", "line")

    def __init__(self, kind, attrs, raw, units, line):
        self.kind = kind
        self.attrs = attrs
        self.raw = raw
        self.units = units
        self.line = line

    def describe(self):
        return "block at line %d (%s)" % (self.line, self.kind)


def _quote_depth(line):
    m = QUOTE_PREFIX_RE.match(line)
    if not m:
        return 0, line
    return m.group(1).count(">"), line[m.end():]


def _strip_quote(line, depth):
    """Remove up to ``depth`` blockquote markers from ``line``."""
    rest = line
    for _ in range(depth):
        m = re.match(r"^[ ]{0,3}>[ ]?", rest)
        if not m:
            break
        rest = rest[m.end():]
    return rest


def _is_html_start(body):
    stripped = body.strip()
    if stripped == POLISH_OFF or stripped == POLISH_ON:
        return False
    return bool(HTML_BLOCK_RE.match(body) or HTML_LINE_TAG_RE.match(body))


def _split_cells(row):
    tokens_masked = list(row)
    for m in CODE_SPAN_RE.finditer(row):
        for k in range(m.start(), m.end()):
            tokens_masked[k] = " "
    masked = "".join(tokens_masked)
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


def _prose_line(text):
    """Strip a prose line but keep trailing hard-break markup."""
    if text.endswith("  ") or text.endswith("\\"):
        return text.lstrip()
    return text.strip()


def _is_table_sep(line):
    return "|" in line and "-" in line and bool(TABLE_SEP_RE.match(line))


def _starts_block(body, in_list):
    """True when ``body`` would start a new block instead of continuing prose."""
    if not body.strip():
        return True
    if body.strip() in (POLISH_OFF, POLISH_ON):
        return True
    if FENCE_RE.match(body) or ATX_RE.match(body) or HR_RE.match(body):
        return True
    if _is_html_start(body):
        return True
    if LIST_ITEM_RE.match(body):
        return True
    if FOOTNOTE_DEF_RE.match(body) or REFDEF_RE.match(body):
        return True
    if body.lstrip().startswith("$$"):
        return True
    return False


def _fence_end(lines, start, quote, fence):
    """Return the index of the line that closes ``fence`` (or the last line)."""
    n = len(lines)
    j = start
    while j < n:
        b = _strip_quote(lines[j], quote)
        cm = re.match(r"^[ \t]*(`{3,}|~{3,})[ \t]*$", b)
        if cm and cm.group(1)[0] == fence[0] and len(cm.group(1)) >= len(fence):
            return j
        j += 1
    return n - 1


def _is_fence_open(text):
    fm = FENCE_RE.match(text)
    if not fm:
        return None
    if fm.group(2)[0] == "`" and "`" in fm.group(3):
        return None
    return fm.group(2)


def _html_block_end(lines, i, body):
    """Return the index of the last line of the HTML block starting at ``i``.

    Follows the CommonMark end conditions: raw-text elements, comments,
    processing instructions, declarations and CDATA end at their closing
    marker even across blank lines; other HTML blocks end at a blank line.
    """
    n = len(lines)
    stripped = body.lstrip(" ")
    end_re = None
    if HTML_TYPE1_RE.match(stripped):
        end_re = HTML_TYPE1_END_RE
    elif stripped.startswith("<!--"):
        end_re = re.compile(re.escape("-->"))
    elif stripped.startswith("<?"):
        end_re = re.compile(re.escape("?>"))
    elif stripped.startswith("<![CDATA["):
        end_re = re.compile(re.escape("]]>"))
    elif re.match(r"<![A-Za-z]", stripped):
        end_re = re.compile(">")
    if end_re is None:
        j = i
        while j + 1 < n and lines[j + 1].strip():
            j += 1
        return j
    j = i
    while j < n and not end_re.search(lines[j]):
        j += 1
    return min(j, n - 1)


def parse_blocks(text):
    """Split Markdown or plain text into an ordered list of blocks."""
    lines = text.split("\n")
    n = len(lines)
    blocks = []
    i = 0

    if n > 1 and lines[0] in ("---", "+++"):
        closer = lines[0]
        for j in range(1, n):
            if lines[j] == closer or (closer == "---" and lines[j] == "..."):
                blocks.append(Block("frontmatter", {}, "\n".join(lines[0:j + 1]), [], 1))
                i = j + 1
                break

    # Open list items as (marker_indent, content_column), tracked within one
    # blockquote depth. A block belongs to every open item whose content
    # column it reaches.
    list_stack = []
    stack_quote = [0]

    def containers(quote, indent):
        if quote != stack_quote[0]:
            del list_stack[:]
            stack_quote[0] = quote
        while list_stack and indent < list_stack[-1][1]:
            list_stack.pop()
        base = list_stack[-1][1] if list_stack else 0
        return len(list_stack), base

    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        start_line = i + 1

        if line.strip() == POLISH_OFF:
            j = i + 1
            while j < n and lines[j].strip() != POLISH_ON:
                j += 1
            end = min(j, n - 1)
            blocks.append(Block("protected", {}, "\n".join(lines[i:end + 1]), [], start_line))
            i = end + 1
            continue

        quote, body = _quote_depth(line)
        ebody = body.expandtabs(4)
        indent = len(ebody) - len(ebody.lstrip(" "))
        depth, base = containers(quote, indent)

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
            blocks.append(Block("indented_code", {"quote": quote, "container": depth},
                                "\n".join(lines[i:j + 1]), [], start_line))
            i = j + 1
            continue

        fence = _is_fence_open(body)
        if fence:
            end = _fence_end(lines, i + 1, quote, fence)
            blocks.append(Block("fence", {"quote": quote, "container": depth},
                                "\n".join(lines[i:end + 1]), [], start_line))
            i = end + 1
            continue

        if body.lstrip().startswith("$$"):
            j = i
            opener = body.strip()
            if not (len(opener) > 2 and opener.endswith("$$")):
                j = i + 1
                while j < n and "$$" not in lines[j]:
                    j += 1
            end = min(j, n - 1)
            blocks.append(Block("math", {"quote": quote, "container": depth},
                                "\n".join(lines[i:end + 1]), [], start_line))
            i = end + 1
            continue

        if _is_html_start(body):
            end = _html_block_end(lines, i, body)
            blocks.append(Block("html", {"quote": quote, "container": depth},
                                "\n".join(lines[i:end + 1]), [], start_line))
            i = end + 1
            continue

        if FOOTNOTE_DEF_RE.match(body):
            # Continuation: indented lines right after the definition, and
            # lines indented four columns after blank lines.
            j = i
            k = i + 1
            while k < n:
                kq, _ = _quote_depth(lines[k])
                if kq != quote:
                    break
                kb = _strip_quote(lines[k], quote)
                if not kb.strip():
                    k += 1
                    continue
                if k == j + 1 and kb[:1] in (" ", "\t"):
                    j = k
                    k += 1
                    continue
                if kb.expandtabs(4).startswith("    "):
                    j = k
                    k += 1
                    continue
                break
            blocks.append(Block("footnote_def", {"quote": quote, "container": depth},
                                "\n".join(lines[i:j + 1]), [], start_line))
            i = j + 1
            continue

        if REFDEF_RE.match(body):
            # A title may continue on the following lines.
            j = i
            while j + 1 < n:
                nq, _ = _quote_depth(lines[j + 1])
                nb = _strip_quote(lines[j + 1], quote)
                if nq != quote or not nb.strip():
                    break
                if REFDEF_RE.match(nb) or FOOTNOTE_DEF_RE.match(nb):
                    break
                if nb[:1] in (" ", "\t") or nb.lstrip()[:1] in ("\"", "'", "("):
                    j += 1
                    continue
                break
            blocks.append(Block("refdef", {"quote": quote, "container": depth},
                                "\n".join(lines[i:j + 1]), [], start_line))
            i = j + 1
            continue

        hm = ATX_RE.match(body)
        if hm:
            blocks.append(Block("heading", {"level": len(hm.group(1)), "quote": quote,
                                            "container": depth},
                                line, [hm.group(2) or ""], start_line))
            i += 1
            continue

        if HR_RE.match(body):
            blocks.append(Block("hr", {"quote": quote, "container": depth}, body.strip(), [],
                                start_line))
            i += 1
            continue

        if "|" in body and i + 1 < n and _is_table_sep(_strip_quote(lines[i + 1], quote)):
            # Body rows run until a blank line or the start of another block,
            # with or without pipes.
            rows = [i]
            j = i + 2
            while j < n and lines[j].strip() and _quote_depth(lines[j])[0] == quote:
                if _starts_block(_strip_quote(lines[j], quote), False):
                    break
                rows.append(j)
                j += 1
            has_html = any(HTML_TAG_RE.search(_strip_quote(lines[r], quote)) for r in rows)
            for idx, r in enumerate(rows):
                row_body = _strip_quote(lines[r], quote)
                cells = _split_cells(row_body)
                if has_html:
                    blocks.append(Block("table_raw", {"quote": quote, "container": depth},
                                        lines[r], [], r + 1))
                else:
                    blocks.append(Block("table_row", {"quote": quote, "container": depth,
                                                      "cols": len(cells)},
                                        lines[r], cells, r + 1))
                if idx == 0:
                    sep = _strip_quote(lines[i + 1], quote)
                    sep_norm = re.sub(r"[ \t]", "", sep).strip("|")
                    blocks.append(Block("table_sep", {"quote": quote, "container": depth},
                                        sep_norm, [], i + 2))
            i = j
            continue

        lm = LIST_ITEM_RE.match(body)
        if lm:
            marker = lm.group("marker")
            after_marker = ebody[indent + len(marker):]
            gap = len(after_marker) - len(after_marker.lstrip(" "))
            if gap >= 5 or not after_marker.strip():
                gap = 1
            list_stack.append((indent, indent + len(marker) + gap))
            ordered = marker[-1] in ".)"
            task = lm.group("task")
            task_norm = task.strip().lower() if task else ""
            attrs = {
                "quote": quote,
                "depth": depth,
                "ordered": ordered,
                "marker": marker,
                "task": task_norm,
            }
            item_fence = _is_fence_open(lm.group("rest"))
            if item_fence:
                # A fence that opens on the marker line is kept verbatim with
                # the marker.
                end = _fence_end(lines, i + 1, quote, item_fence)
                blocks.append(Block("list_fence", attrs, "\n".join(lines[i:end + 1]), [],
                                    start_line))
                i = end + 1
                continue
            content = [_prose_line(lm.group("rest"))]
            j = i + 1
            while j < n:
                nxt = lines[j]
                nq, nbody = _quote_depth(nxt)
                if not nxt.strip():
                    break
                if nq not in (0, quote):
                    break
                nbody = _strip_quote(nxt, quote)
                if _starts_block(nbody, True):
                    break
                if "|" in nbody and j + 1 < n and _is_table_sep(_strip_quote(lines[j + 1], quote)):
                    break
                content.append(_prose_line(nbody))
                j += 1
            blocks.append(Block("list_item", attrs, "\n".join(lines[i:j]), ["\n".join(content)],
                                start_line))
            i = j
            continue

        # Paragraph, possibly a setext heading. An underline only counts when
        # it sits in the same blockquote as the paragraph; a lazy "---" line
        # outside the quote is a thematic break.
        content = [_prose_line(body)]
        j = i + 1
        setext_level = 0
        while j < n:
            nxt = lines[j]
            if not nxt.strip():
                break
            nq, _ = _quote_depth(nxt)
            if nq not in (0, quote):
                break
            nbody = _strip_quote(nxt, quote)
            sm = SETEXT_RE.match(nbody)
            if sm and nq == quote:
                setext_level = 1 if sm.group(1)[0] == "=" else 2
                j += 1
                break
            if _starts_block(nbody, False):
                break
            if "|" in nbody and j + 1 < n and _is_table_sep(_strip_quote(lines[j + 1], quote)):
                break
            content.append(_prose_line(nbody))
            j += 1
        if setext_level:
            blocks.append(Block("heading", {"level": setext_level, "quote": quote,
                                            "container": depth},
                                "\n".join(lines[i:j]), ["\n".join(content)], start_line))
        else:
            blocks.append(Block("paragraph", {"quote": quote, "container": depth},
                                "\n".join(lines[i:j]), ["\n".join(content)], start_line))
        i = j

    return blocks


def prose_block_count(text):
    return len([b for b in parse_blocks(text) if b.kind not in RAW_KINDS])


def check_document(source, candidate, block_ratio=BLOCK_RATIO_BOUNDS, doc_ratio=DOC_RATIO_BOUNDS):
    """Verify a Markdown or text candidate against its source. Raises GuardReject."""
    if candidate.count("\r") != source.count("\r"):
        raise GuardReject("structure", "carriage-return line endings changed")
    src_blocks = parse_blocks(source)
    cand_blocks = parse_blocks(candidate)
    if len(src_blocks) != len(cand_blocks):
        detail = "source has %d blocks, candidate has %d" % (len(src_blocks), len(cand_blocks))
        for a, b in zip(src_blocks, cand_blocks):
            if a.kind != b.kind or a.attrs != b.attrs:
                detail += "; first difference at source line %d (%s vs %s)" % (a.line, a.kind, b.kind)
                break
        raise GuardReject("structure", detail)
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
            s_len, c_len = compare_prose(su, cu, unit_where, block_ratio)
            total_src += s_len
            total_cand += c_len
    check_ratio(total_src, total_cand, doc_ratio, "document")


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
    state = {"body": False, "head": False, "title": 0}

    def eligible_context():
        if excluded:
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
            tag_eligible = (eligible_context() and lowered not in EXCLUDED_ELEMENTS
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
                if (tag_eligible and name in ELIGIBLE_ATTRS and quote and value is not None
                        and value.strip() and not _has_template_syntax(value)):
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
    if run_start is not None:
        flush_run(run_start, len(source))
    return spans, skeleton


def html_extract(source):
    """Return (spans, segments_text) or raise UnsupportedInput."""
    spans, _ = _analyze_html(source)
    segments = [("s%d" % (k + 1), collapse_ws(span.core)) for k, span in enumerate(spans)]
    return spans, (format_segments(segments) if segments else "")


def _escape_text(text, quote=""):
    out = re.sub(r"&(?!(?:[A-Za-z][A-Za-z0-9]{1,31}|#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6});)", "&amp;", text)
    out = out.replace("<", "&lt;").replace(">", "&gt;")
    if quote == '"':
        out = out.replace('"', "&quot;")
    elif quote == "'":
        out = out.replace("'", "&#39;")
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
            pieces.append(span.lead + _escape_text(new_text, span.quote) + span.trail)
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
