"""Collected Works of Watchman Nee (one EPUB per page).

Two kinds of index page exist:
  index titles  (e.g. Vol. 12-14, The Spiritual Man): the index links carry the
                page title plus "section N" / "ch.N" markers, so the EPUB gets a
                "Section Two  •  Chapter 3" kicker.
  page titles   (e.g. Vol. 01-02): index links carry only sub-heading text. The
                title is the page's first descriptive <h1>, and a bare
                "CHAPTER ONE" heading becomes the kicker.
"auto" picks index titles when the index has any "section N" marker.
"""

import logging
import re

from bs4 import BeautifulSoup

from webtoepub.clean import GENERIC_HEADING, normalize
from webtoepub.fetch import Fetcher
from webtoepub.model import Block, PageRef, Series
from webtoepub.sources import Source
from webtoepub.sources.books import BOOKS_PATH, book_slug, clean_book_title

log = logging.getLogger(__name__)

_SECTION = re.compile(r"\s+section[.\s]+(\d+)\s*$", re.I)
_CHAPTER = re.compile(r"\s*ch\.(\d+)\s*$", re.I)
_ANCHOR_LINK = re.compile(r"/(\d+)/#")
_PAGE_LINK = re.compile(r"/(\d+)/$")
_SET_VOL = re.compile(r"-set-(\d+)-vol-(\d+)-", re.I)

_NUMBER_WORDS = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]


def section_label(n: int) -> str:
    return f"Section {_NUMBER_WORDS[n - 1]}" if 1 <= n <= len(_NUMBER_WORDS) else f"Section {n}"


def kicker(section: int | None, chapter: int | None) -> str:
    parts = []
    if section:
        parts.append(section_label(section))
    if chapter:
        parts.append(f"Chapter {chapter}")
    return "  •  ".join(parts)


def series_name(book_title: str, url: str) -> tuple[str, str]:
    """("CWWN (1.12) - The Spiritual Man (1)", "cwwn-set-1-vol-12")."""
    m = _SET_VOL.search(url)
    if not m:
        return book_title, "cwwn"
    set_no, vol = int(m.group(1)), int(m.group(2))
    sub = re.search(r"Vol\.?\s*\d+\s*:\s*(.+)$", book_title)
    name = f"CWWN ({set_no}.{vol:02d}) - {sub.group(1).strip() if sub else book_title}"
    return name, f"cwwn-set-{set_no}-vol-{vol:02d}"


def parse_index(soup: BeautifulSoup, slug: str) -> tuple[int, dict[int, dict], bool]:
    """Return (page count, {page: {title, section, chapter}}, saw section markers)."""
    total = 0
    info: dict[int, dict] = {}
    section: int | None = None
    chapter: int | None = None
    saw_markers = False

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if slug not in href:
            continue
        m_anchor = _ANCHOR_LINK.search(href)
        m_page = _PAGE_LINK.search(href)
        if m_anchor:
            page = int(m_anchor.group(1))
            total = max(total, page)
            label = a.get_text(" ", strip=True)
            if not label or label.isdigit() or len(label) <= 2:
                continue
            sm = _SECTION.search(label)
            if sm:
                saw_markers = True
                section, chapter = int(sm.group(1)), None
                label = label[: sm.start()].strip()
            cm = _CHAPTER.search(label)
            if cm:
                chapter = int(cm.group(1))
                label = label[: cm.start()].strip()
            if label and page not in info:
                info[page] = {"title": label, "section": section, "chapter": chapter}
        elif m_page:
            total = max(total, int(m_page.group(1)))
    return total, info, saw_markers


class Cwwn(Source):
    def __init__(self, titles: str = "auto") -> None:
        self.titles_mode = titles
        self.use_index_titles = False
        self.page_info: dict[int, dict] = {}

    def discover(self, fetcher: Fetcher, url: str) -> tuple[Series, list[PageRef]]:
        if BOOKS_PATH not in url:
            raise SystemExit(f"CWWN URLs must be under {BOOKS_PATH}")
        soup = fetcher.soup(url)
        if soup is None:
            raise SystemExit(f"Cannot fetch the index page: {url}")
        h1 = soup.find("h1") or soup.find("title")
        self.series_title = clean_book_title(h1.get_text(strip=True)) if h1 else "Unknown Book"

        total, info, saw_markers = parse_index(soup, book_slug(url))
        if total == 0:
            raise SystemExit("No pages found. Pass the book index URL, not a chapter URL.")
        self.use_index_titles = (
            self.titles_mode == "index" or (self.titles_mode == "auto" and saw_markers)
        )
        log.info("Titles from: %s", "index page" if self.use_index_titles else "each page")
        if self.use_index_titles:
            for n in range(1, total + 1):
                info.setdefault(n, {"title": f"Page {n}", "section": None, "chapter": None})
            self.page_info = info

        name, slug = series_name(self.series_title, url)
        base = url.rstrip("/")
        refs = [PageRef(n, f"{base}/{n}/") for n in range(1, total + 1)]
        self.apply_page_info(refs)
        return Series(name, "Watchman Nee", "Page", slug), refs

    def apply_page_info(self, refs: list[PageRef]) -> None:
        """Copy (possibly user-corrected) index info onto the refs."""
        if not self.use_index_titles:
            return
        for ref in refs:
            i = self.page_info[ref.number]
            ref.title = i["title"]
            ref.kicker = kicker(i["section"], i["chapter"])

    def title_from_blocks(self, blocks: list[Block]) -> str:
        book = normalize(self.series_title)
        h1s = [b.text for b in blocks if b.kind == "h" and b.level == 1 and normalize(b.text) != book]
        for text in h1s:
            if not GENERIC_HEADING.match(text.strip()):
                return text
        return h1s[0] if h1s else ""
