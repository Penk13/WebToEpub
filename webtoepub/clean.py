"""Turn a bibleread.online page into a list of content blocks.

Site UI strings (menus, buttons, footer) are short. Every filter here only
applies to text up to MAX_UI_LENGTH characters, so a real paragraph that
happens to mention "Living Stream Ministry" or "today's reading" is kept.
"""

import re
from collections.abc import Callable

from bs4 import BeautifulSoup, NavigableString, Tag

from webtoepub.model import Block

MAX_UI_LENGTH = 200

STRIP_TAGS = ["script", "style", "nav", "header", "footer", "iframe", "noscript"]
CONTENT_TAGS = ["p", "h1", "h2", "h3", "h4", "blockquote"]
LIST_TAGS = ["ol", "ul"]
UI_CLASS_WORDS = ("nav", "header", "footer", "button", "menu")
UI_ID_WORDS = ("nav", "header", "footer")

# Reaching one of these means the article is over: stop reading the page.
FOOTER_SENTINELS = (
    "Ru Библия",
    "Es Biblia leer",
    "閱讀中文聖經",
    "Living Stream Ministry",
    "Alphabetically search",
)

# Short UI strings to skip (reading continues).
NAV_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"Matt\.\s+Mark\s+Luke",
        r"Gen\.\s+Exo\.\s+Lev\.",
        r"Book messages\s*[«»]",
        r"^[\d\s]+$",
        r"quick transfer",
        r"download android app",
        r"listen on youtube",
        r"search in the bible",
        r"my study of the bible",
        r"write about error",
        r"show header|hide header",
        r"^(bookmarks|my readings|today.?s reading)$",
        r"^(NT|OT|С)$",
        r"Speaking the Truth in Love",
        r"Advise you to read",
        r"Hover your cursor",
        r"You can hide links",
        r"New book\b",
        r"denominations are formed",
        r"^play audio$",
        r"^fill in the form$",
        r"^notes$",
        r"^search$",
        r"^ch\.\s*\d+",
        r"^[←→]",
        r"^\d+\s*/",
        r"^(Listen|Back|Show|Hide)\b(\s+\w+)?$",
    )
]

# Structural headings that carry no title of their own: "CHAPTER ONE",
# "Section two", "Message 12".
GENERIC_HEADING = re.compile(
    r"^(?:chapter|section|message)\s+(?:[ivxlcdm]+|[a-z]+|\d+)$", re.I
)

_HAS_WORD_CHAR = re.compile(r"\w")


def is_footer(text: str) -> bool:
    if len(text) > MAX_UI_LENGTH:
        return False
    return any(s in text for s in FOOTER_SENTINELS)


def is_nav(text: str) -> bool:
    if len(text) > MAX_UI_LENGTH:
        return False
    return any(p.search(text) for p in NAV_PATTERNS)


def _is_ui_element(el: Tag) -> bool:
    cls = " ".join(el.get("class") or []).lower()
    eid = (el.get("id") or "").lower()
    return any(w in cls for w in UI_CLASS_WORDS) or any(w in eid for w in UI_ID_WORDS)


def extract_blocks(
    soup: BeautifulSoup,
    skip: Callable[[str, str], bool] | None = None,
) -> list[Block]:
    """Return the page's content blocks in reading order.

    `skip(tag_name, text)` lets a source drop extra, source-specific noise.
    """
    for tag in soup.find_all(STRIP_TAGS):
        tag.decompose()
    root = soup.body or soup
    _wrap_loose_text(soup, root)

    blocks: list[Block] = []

    def add(block: Block) -> None:
        # The site sometimes repeats a block back to back; a refrain repeated
        # further apart is real content and stays.
        if not (blocks and blocks[-1] == block):
            blocks.append(block)

    for el in root.find_all(CONTENT_TAGS + LIST_TAGS):
        if el.name in LIST_TAGS:
            # Nested lists are emitted with their parent list.
            if el.find_parent(CONTENT_TAGS + LIST_TAGS) or _is_ui_element(el):
                continue
            if not _emit_list(el, 1, add, skip):
                break
            continue
        # A <p> inside a <blockquote> or a list item is emitted with it.
        if el.find_parent(CONTENT_TAGS + ["li"]):
            continue
        if _is_ui_element(el):
            continue
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if is_footer(text):
            break
        if not _HAS_WORD_CHAR.search(text) or is_nav(text):
            continue
        if skip and skip(el.name, text):
            continue

        if el.name == "p":
            add(Block("p", text))
        elif el.name == "blockquote":
            add(Block("quote", text))
        else:
            add(Block("h", text, int(el.name[1])))
    return blocks


# Inline tags that may sit in a run of loose text next to bare strings.
_INLINE_TAGS = {"a", "b", "i", "em", "strong", "span", "sup", "sub", "u", "small", "font"}


def _wrap_loose_text(soup: BeautifulSoup, root: Tag) -> None:
    """Wrap text that sits directly in a block container in <p> tags.

    Some pages put lines as bare text between <br/> tags (e.g. an outline)
    instead of in <p>. Each <br/>-separated run becomes one <p>, so it is
    read like any other paragraph. Runs inside site UI containers are left
    alone.
    """
    skip_parents = CONTENT_TAGS + LIST_TAGS + ["li", "table"]
    containers = []
    for string in root.find_all(string=True):
        parent = string.parent
        if (
            not string.strip()
            or not isinstance(parent, Tag)
            or parent.name in _INLINE_TAGS
            or parent.name in skip_parents
            or parent.find_parent(skip_parents)
            or _is_ui_element(parent)
            or any(_is_ui_element(p) for p in parent.parents if isinstance(p, Tag))
        ):
            continue
        if parent not in containers:
            containers.append(parent)

    for container in containers:
        run: list = []

        def flush() -> None:
            if any((n.get_text() if isinstance(n, Tag) else str(n)).strip() for n in run):
                p = soup.new_tag("p")
                run[0].insert_before(p)
                for n in run:
                    p.append(n.extract())
            run.clear()

        for child in list(container.children):
            if isinstance(child, Tag) and child.name not in _INLINE_TAGS:
                flush()  # <br/> or a block element ends the run
            elif isinstance(child, Tag) or type(child) is NavigableString:  # not Comment etc.
                run.append(child)
        flush()


_ROMAN_NUMERALS = [
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
    (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
]


def _roman(n: int) -> str:
    out = ""
    for value, numeral in _ROMAN_NUMERALS:
        while n >= value:
            out += numeral
            n -= value
    return out


def _alpha(n: int) -> str:
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(ord("a") + r) + out
    return out


def list_marker(list_el: Tag, n: int) -> str:
    """Marker for the n-th item: "I.", "A.", "1.", "a." or a bullet.

    The site sets the numbering style with a class (upper-roman, upper-alpha,
    decimal, lower-alpha, lower-roman); an inline list-style-type also counts.
    """
    if list_el.name == "ul":
        return "•"
    style = " ".join(list_el.get("class") or []) + " " + (list_el.get("style") or "")
    style = style.lower()
    if "upper-roman" in style:
        return _roman(n).upper() + "."
    if "lower-roman" in style:
        return _roman(n) + "."
    if "upper-alpha" in style or "upper-latin" in style:
        return _alpha(n).upper() + "."
    if "lower-alpha" in style or "lower-latin" in style:
        return _alpha(n) + "."
    return f"{n}."


def _item_text(li: Tag) -> str:
    """The item's own text, without its nested lists."""
    parts = []
    for child in li.children:
        if isinstance(child, Tag):
            if child.name in LIST_TAGS:
                continue
            parts.append(child.get_text(" ", strip=True))
        else:
            parts.append(str(child).strip())
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def _emit_list(
    list_el: Tag,
    depth: int,
    add: Callable[[Block], None],
    skip: Callable[[str, str], bool] | None,
) -> bool:
    """Emit each item as an "li" block (level = nesting depth), recursing into
    nested lists. Returns False when a footer sentinel is reached."""
    try:
        n = int(list_el.get("start") or 1)
    except ValueError:
        n = 1
    for li in list_el.find_all("li", recursive=False):
        if li.get("value", "").isdigit():
            n = int(li["value"])
        text = _item_text(li)
        if text:
            if is_footer(text):
                return False
            if _HAS_WORD_CHAR.search(text) and not is_nav(text) and not (skip and skip("li", text)):
                add(Block("li", f"{list_marker(list_el, n)} {text}", depth))
        for sub in li.find_all(LIST_TAGS, recursive=False):
            if not _emit_list(sub, depth + 1, add, skip):
                return False
        n += 1
    return True


def normalize(text: str) -> str:
    """Comparison key: case-folded, straight quotes, single spaces, no end punctuation."""
    text = text.replace("’", "'").replace("‘", "'").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text.strip(" .:;-–—")


def strip_leading_echoes(
    blocks: list[Block], echoes: set[str]
) -> tuple[list[Block], str]:
    """Drop the lines at the top of a page that repeat the EPUB header.

    The site starts each page with the series name, "Message N", a bare
    "CHAPTER ONE" heading and the title; the EPUB header already shows those.
    Only leading blocks are dropped; the first other block ends the search.

    Returns (remaining blocks, first generic heading found or "").
    """
    keys = {normalize(e) for e in echoes if e}
    generic = ""
    i = 0
    while i < len(blocks):
        text = blocks[i].text
        if normalize(text) in keys:
            i += 1
        elif blocks[i].kind == "h" and GENERIC_HEADING.match(text.strip()):
            generic = generic or text.strip()
            i += 1
        else:
            break
    return blocks[i:], generic


def promote_headings(blocks: list[Block]) -> list[Block]:
    """Shift heading levels so the body's top level is h2 (h1 is the EPUB title)."""
    levels = [b.level for b in blocks if b.kind == "h"]
    if not levels:
        return blocks
    shift = 2 - min(levels)
    if shift == 0:
        return blocks
    return [
        Block(b.kind, b.text, min(6, max(2, b.level + shift))) if b.kind == "h" else b
        for b in blocks
    ]


_SMALL_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into",
    "nor", "of", "on", "or", "the", "to", "with",
}
# Only I/V/X: no English word besides "I" is spelled with just those letters.
_ROMAN = re.compile(r"^[IVX]{1,5}[.),:]?$")


def smart_title(text: str) -> str:
    """Title-case text that the site set in ALL CAPS; leave other text alone."""
    letters = [c for c in text if c.isalpha()]
    if not letters or not all(c.isupper() for c in letters):
        return text
    words = text.lower().split(" ")
    out = []
    for i, w in enumerate(words):
        if _ROMAN.match(w.upper()):
            out.append(w.upper())
        elif i > 0 and w in _SMALL_WORDS and not out[-1].endswith((":", "?", "!")):
            out.append(w)
        else:
            # capitalize() keeps "god's" -> "God's" (str.title gives "God'S")
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)
