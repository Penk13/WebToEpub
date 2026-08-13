#!/usr/bin/env python3
"""
bibleread-books.py
--------------------------
Converts a book from bibleread.online/all-books-by-Watchman-Nee-and-Witness-Lee/
into individual EPUB files — one per chapter — ready for Kindle/reading apps.

Usage:
    python bibleread-books.py <book_url>

Example:
    python bibleread-books.py \
        https://bibleread.online/all-books-by-Watchman-Nee-and-Witness-Lee/book-abiding-in-the-lord-to-enjoy-his-life-Witness-Lee-read-online/

Output:
    ./<book-slug>/001-Chapter-Title.epub
    ./<book-slug>/002-Another-Title.epub
    ...
"""

import re
import sys
import time
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from ebooklib import epub

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

REQUEST_DELAY   = 1.2
REQUEST_TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Noise / footer filters (same approach as lifestudy_to_epub.py)
# ──────────────────────────────────────────────────────────────────────────────

_STRIP_TAGS = {"script", "style", "nav", "header", "footer", "iframe", "noscript"}

_SKIP_TEXT_PATTERNS = [
    re.compile(r"Matt\.\s+Mark\s+Luke",           re.I),
    re.compile(r"Gen\.\s+Exo\.\s+Lev\.",           re.I),
    re.compile(r"Book messages\s*[«»]",             re.I),
    re.compile(r"^[\d\s]+$"),
    re.compile(r"quick transfer",                   re.I),
    re.compile(r"download android app",             re.I),
    re.compile(r"listen on youtube",                re.I),
    re.compile(r"search in the bible",              re.I),
    re.compile(r"my study of the bible",            re.I),
    re.compile(r"write about error",                re.I),
    re.compile(r"show header|hide header",          re.I),
    re.compile(r"bookmarks|my readings|today.*?reading", re.I),
    re.compile(r"^(NT|OT|С)$"),
    re.compile(r"Ru\s+Библия|Biblia leer|閱讀中文聖經", re.I),
    re.compile(r"Living Stream Ministry",           re.I),
    re.compile(r"Speaking the Truth in Love",       re.I),
    re.compile(r"Advise you to read",               re.I),
    re.compile(r"Alphabetically search",            re.I),
    re.compile(r"Hover your cursor",                re.I),
    re.compile(r"You can hide links",               re.I),
    re.compile(r"New book\b",                       re.I),
    re.compile(r"denominations are formed",         re.I),
    re.compile(r"^ch\.\s*\d+",                     re.I),
    re.compile(r"^←\s*Back",                       re.I),
]

_FOOTER_SENTINELS = [
    "Ru Библия",
    "Living Stream Ministry",
    "Alphabetically search",
    "閱讀中文聖經",
]


def _is_nav_text(text: str) -> bool:
    return any(p.search(text) for p in _SKIP_TEXT_PATTERNS)


def _is_footer(text: str) -> bool:
    return any(s in text for s in _FOOTER_SENTINELS)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def fetch(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as exc:
        log.warning("⚠  Failed to fetch %s — %s", url, exc)
        return None


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text.strip())
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def _book_slug_from_url(url: str) -> str:
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    return parts[-1] if parts else "book"


def _detect_author(url: str) -> str:
    url_lower = url.lower()
    if "watchman-nee" in url_lower:
        return "Watchman Nee"
    if "witness-lee" in url_lower:
        return "Witness Lee"
    return "Witness Lee / Watchman Nee"


# ──────────────────────────────────────────────────────────────────────────────
# Phase 1 — Discover chapters from the book index page
# ──────────────────────────────────────────────────────────────────────────────

def discover_chapters(book_url: str) -> tuple[str, str, list[dict]]:
    """
    Parse the book index page and return (book_title, author, chapters).
    Each chapter dict: {number, title, url}
    """
    log.info("Fetching book page: %s", book_url)
    soup = fetch(book_url)
    if soup is None:
        raise SystemExit(f"Cannot fetch book page: {book_url}")

    author = _detect_author(book_url)

    # Book title from <h1>
    h1 = soup.find("h1")
    book_title = h1.get_text(strip=True) if h1 else "Unknown Book"
    log.info("Book: %s  |  Author: %s", book_title, author)

    book_slug = _book_slug_from_url(book_url)

    # Chapter URLs: outline links point to /all-books-by-.../<book-slug>/<N>/#contN
    # Strip the anchor to get the clean chapter URL.
    outline_pattern = re.compile(
        rf"/all-books-by-Watchman-Nee-and-Witness-Lee/{re.escape(book_slug)}/(\d+)/#cont",
        re.IGNORECASE,
    )

    ch_urls: dict[int, str] = {}
    for a in soup.find_all("a", href=True):
        m = outline_pattern.search(a["href"])
        if m:
            num = int(m.group(1))
            if num not in ch_urls:
                ch_urls[num] = book_url.rstrip("/") + f"/{num}/"

    # Fallback: "Chapters: 1 2 3" nav links → /books-search/<slug>/<N>/
    if not ch_urls:
        nav_pattern = re.compile(
            rf"/books-search/{re.escape(book_slug)}/(\d+)/",
            re.IGNORECASE,
        )
        for a in soup.find_all("a", href=True):
            m = nav_pattern.search(a["href"])
            if m:
                num = int(m.group(1))
                if num not in ch_urls:
                    ch_urls[num] = urljoin(book_url, a["href"]).rstrip("/") + "/"

    if not ch_urls:
        # Single-chapter book — the index page IS the content
        log.info("No chapter links found; using book page itself as chapter 1.")
        ch_urls[1] = book_url

    # Chapter titles from bold outline links (first bold link per chapter number)
    ch_titles: dict[int, str] = {}
    for a in soup.find_all("a", href=True):
        m = outline_pattern.search(a["href"])
        if not m:
            continue
        num = int(m.group(1))
        if num in ch_titles:
            continue
        bold = a.find(["b", "strong"])
        if bold:
            title = re.sub(r"\s+ch\.\s*\d+$", "", bold.get_text(strip=True), flags=re.I).strip()
            if title:
                ch_titles[num] = title

    chapters = [
        {
            "number": num,
            "title":  ch_titles.get(num, f"Chapter {num}"),
            "url":    ch_urls[num],
        }
        for num in sorted(ch_urls)
    ]

    log.info("Found %d chapter(s).", len(chapters))
    return book_title, author, chapters


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — Scrape chapter body
# ──────────────────────────────────────────────────────────────────────────────

def scrape_chapter_body(url: str) -> str:
    soup = fetch(url)
    if soup is None:
        return ""

    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    content_blocks: list[str] = []
    seen_texts: set[str] = set()

    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4"]):
        text = tag.get_text(" ", strip=True)

        if _is_footer(text):
            break
        if len(text) < 15:
            continue
        if _is_nav_text(text):
            continue

        key = text[:120]
        if key in seen_texts:
            continue
        seen_texts.add(key)

        if tag.name in ("h1", "h2", "h3", "h4"):
            content_blocks.append(f"<{tag.name}>{text}</{tag.name}>")
        else:
            content_blocks.append(f"<p>{text}</p>")

    return "\n".join(content_blocks)


# ──────────────────────────────────────────────────────────────────────────────
# Phase 3 — Build EPUB (one per chapter)
# ──────────────────────────────────────────────────────────────────────────────

_CSS = """
body {
    font-family: Georgia, serif;
    font-size: 1em;
    line-height: 1.7;
    margin: 1em 2em;
    color: #1a1a1a;
}
h1 { font-size: 1.4em; margin-top: 1.5em; }
h2 { font-size: 1.2em; margin-top: 1.2em; }
h3 { font-size: 1.1em; margin-top: 1em; }
p  { margin: 0.6em 0; text-align: justify; }
"""


def build_epub(
    book_title: str,
    author: str,
    ch: dict,
    body_html: str,
    output_path: Path,
) -> None:
    num   = ch["number"]
    title = ch["title"]

    book = epub.EpubBook()
    book.set_identifier(f"{slugify(book_title)}-ch-{num:03d}")
    book.set_title(f"{num:03d} - {title}")
    book.set_language("en")
    book.add_author(author)

    # Calibre series metadata
    book.add_metadata("DC", "subject", book_title)
    book.add_metadata(None, "meta", "", {"name": "calibre:series",       "content": book_title})
    book.add_metadata(None, "meta", "", {"name": "calibre:series_index", "content": str(num)})

    css_item = epub.EpubItem(
        uid="style",
        file_name="style/main.css",
        media_type="text/css",
        content=_CSS,
    )
    book.add_item(css_item)

    if not body_html:
        body_html = "<p><em>(Content could not be retrieved for this chapter.)</em></p>"

    xhtml = f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="../style/main.css"/>
</head>
<body>
  <h1>Chapter {num:03d}: {title}</h1>
  <p><em>{book_title}</em></p>
  <hr/>
  {body_html}
</body>
</html>"""

    chapter_item = epub.EpubHtml(title=title, file_name="chapter.xhtml", lang="en")
    chapter_item.content = xhtml.encode("utf-8")
    chapter_item.add_item(css_item)
    book.add_item(chapter_item)

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.toc   = (epub.Link("chapter.xhtml", title, "chapter"),)
    book.spine = [chapter_item]

    epub.write_epub(str(output_path), book, {})


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    book_url = sys.argv[1].rstrip("/") + "/"

    # Phase 1 — Discover
    book_title, author, chapters = discover_chapters(book_url)

    # Output folder: strip author suffix from slug for a clean name
    book_slug = _book_slug_from_url(book_url)
    folder_name = re.sub(r"-(witness-lee|watchman-nee)-read-online$", "", book_slug, flags=re.I)
    folder_name = re.sub(r"^book-", "", folder_name, flags=re.I)
    out_dir = Path(folder_name)
    out_dir.mkdir(exist_ok=True)
    log.info("Output folder: %s/", out_dir)

    total   = len(chapters)
    success = 0
    skipped = 0

    for i, ch in enumerate(chapters, 1):
        num   = ch["number"]
        title = ch["title"]
        fname = f"{num:03d}-{slugify(title)}.epub"
        output_path = out_dir / fname

        log.info("[%d/%d] Chapter %03d: %s", i, total, num, title)

        # Phase 2 — Scrape
        time.sleep(REQUEST_DELAY)
        body_html = scrape_chapter_body(ch["url"])

        if not body_html:
            log.warning("  ↳ No body content retrieved.")
            skipped += 1

        # Phase 3 — Build EPUB
        try:
            build_epub(book_title, author, ch, body_html, output_path)
            log.info("  ↳ Saved: %s", output_path)
            success += 1
        except Exception as exc:
            log.warning("  ↳ EPUB build failed for chapter %d: %s", num, exc)

    log.info("─" * 60)
    log.info(
        "Done. %d/%d EPUBs created in '%s/'  (%d had no body content)",
        success, total, out_dir, skipped,
    )


if __name__ == "__main__":
    main()