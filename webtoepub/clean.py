"""Turn a bibleread.online page into a list of content blocks.

Site UI strings (menus, buttons, footer) are short. Every filter here only
applies to text up to MAX_UI_LENGTH characters, so a real paragraph that
happens to mention "Living Stream Ministry" or "today's reading" is kept.
"""

import re
from collections.abc import Callable

from bs4 import BeautifulSoup, Tag

from webtoepub.model import Block

MAX_UI_LENGTH = 200

STRIP_TAGS = ["script", "style", "nav", "header", "footer", "iframe", "noscript"]
CONTENT_TAGS = ["p", "h1", "h2", "h3", "h4", "blockquote"]
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

    blocks: list[Block] = []
    for el in root.find_all(CONTENT_TAGS):
        # A <p> inside a <blockquote> is emitted with the blockquote.
        if el.find_parent(CONTENT_TAGS):
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
            block = Block("p", text)
        elif el.name == "blockquote":
            block = Block("quote", text)
        else:
            block = Block("h", text, int(el.name[1]))

        # The site sometimes repeats a block back to back; a refrain repeated
        # further apart is real content and stays.
        if blocks and blocks[-1] == block:
            continue
        blocks.append(block)
    return blocks


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
