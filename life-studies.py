#!/usr/bin/env python3
"""
life-studies.py
--------------------
Converts a Life-Study of the Bible series from bibleread.online into
individual EPUB files — one per message — ready for Kindle/reading apps.

Usage:
    python life-studies.py <series_index_url>

Examples:
    python life-studies.py https://bibleread.online/life-study-of-the-bible/life-study-of-romans/
    python life-studies.py https://bibleread.online/life-study-of-the-bible/life-study-of-matthew/

Output:
    ./<series-slug>/001-Message-Title.epub
    ./<series-slug>/002-Another-Title.epub
    ...
"""

import re
import sys
import time
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from ebooklib import epub

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

REQUEST_DELAY = 1.0          # seconds between HTTP requests
REQUEST_TIMEOUT = 20         # seconds before a request times out
MAX_RETRIES = 0              # no retries — skip on first failure (per spec)
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
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def fetch(url: str) -> BeautifulSoup | None:
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as exc:
        log.warning("⚠  Failed to fetch %s — %s", url, exc)
        return None


def slugify(text: str) -> str:
    """Turn a title into a safe filename component."""
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"[\s_]+", "-", text.strip())
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def series_slug_from_url(url: str) -> str:
    """Extract the series slug from the index URL, e.g. 'life-study-of-romans'."""
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    return parts[-1] if parts else "life-study"


# ──────────────────────────────────────────────────────────────────────────────
# Phase 1 — Discover messages from the index page
# ──────────────────────────────────────────────────────────────────────────────

def discover_messages(index_url: str) -> tuple[str, list[dict]]:
    """
    Parse the series index page.

    Returns:
        series_title  — e.g. "Life-Study of Romans"
        messages      — list of dicts: {number, title, url}
    """
    log.info("Fetching index page: %s", index_url)
    soup = fetch(index_url)
    if soup is None:
        raise SystemExit("Cannot fetch the index page. Check the URL and your connection.")

    series_title = _extract_series_title(soup, index_url)
    log.info("Series: %s", series_title)

    msg_links: dict[int, str] = {}
    base_slug = series_slug_from_url(index_url)
    pattern = re.compile(rf"/{re.escape(base_slug)}/(\d+)/?$")

    for a in soup.find_all("a", href=True):
        m = pattern.search(a["href"])
        if m:
            num = int(m.group(1))
            if num not in msg_links:
                msg_links[num] = urljoin(index_url, a["href"])

    if not msg_links:
        raise SystemExit("No message links found. The page structure may have changed.")

    log.info("Found %d messages.", len(msg_links))
    title_map = _extract_titles(soup)

    messages = []
    for num in sorted(msg_links):
        title = title_map.get(num, f"Message {num}")
        messages.append({"number": num, "title": title, "url": msg_links[num]})

    return series_title, messages


def _extract_series_title(soup: BeautifulSoup, index_url: str) -> str:
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    if soup.title:
        parts = soup.title.string.split("|")
        if len(parts) >= 2:
            return parts[-1].strip()
    slug = series_slug_from_url(index_url)
    return slug.replace("-", " ").title()


def _extract_titles(soup: BeautifulSoup) -> dict[int, str]:
    title_map: dict[int, str] = {}
    # Match both "msg. N" (Genesis-style) and "Message N" (Exodus-style)
    pattern = re.compile(r"\b(?:msg\.|message)\s*(\d+)", re.IGNORECASE)
    for a in soup.find_all("a", href=True):
        a_text = a.get_text(" ", strip=True)
        m = pattern.search(a_text)
        if not m:
            continue
        num = int(m.group(1))
        bold = a.find(["b", "strong"])
        if bold:
            title = bold.get_text(strip=True)
        else:
            title = pattern.sub("", a_text).strip(" :-")
        if title and num not in title_map:
            title_map[num] = title
    return title_map


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — Scrape individual message body
# ──────────────────────────────────────────────────────────────────────────────

_STRIP_TAGS = {"script", "style", "nav", "header", "footer", "iframe", "noscript"}

_SKIP_TEXT_PATTERNS = [
    re.compile(r"Matt\.\s+Mark\s+Luke", re.I),
    re.compile(r"Gen\.\s+Exo\.\s+Lev\.", re.I),
    re.compile(r"Book messages\s*[«»]", re.I),
    re.compile(r"^[\d\s]+$"),
    re.compile(r"quick transfer", re.I),
    re.compile(r"download android app", re.I),
    re.compile(r"listen on youtube", re.I),
    re.compile(r"search in the bible", re.I),
    re.compile(r"my study of the bible", re.I),
    re.compile(r"write about error", re.I),
    re.compile(r"show header|hide header", re.I),
    re.compile(r"bookmarks|my readings|today.*?reading", re.I),
    re.compile(r"^(NT|OT|С)$"),
    re.compile(r"Ru\s+Библия|Biblia leer|閱讀中文聖經", re.I),
    re.compile(r"Living Stream Ministry", re.I),
    re.compile(r"Speaking the Truth in Love", re.I),
    re.compile(r"Advise you to read", re.I),
    re.compile(r"Alphabetically search", re.I),
    re.compile(r"Hover your cursor", re.I),
    re.compile(r"You can hide links", re.I),
    re.compile(r"New book\b", re.I),
    re.compile(r"denominations are formed", re.I),
    # Short UI strings that would slip past a low length floor
    re.compile(r"^play audio$", re.I),
    re.compile(r"^fill in the form$", re.I),
    re.compile(r"^notes$", re.I),
    re.compile(r"^search$", re.I),
    re.compile(r"^← back$", re.I),
    re.compile(r"^[+\-–]$"),                    # lone +/- buttons
    re.compile(r"^!$"),                          # lone ! icon text
    re.compile(r"^↑$"),                          # lone arrow icon
]

_FOOTER_SENTINELS = [
    "Ru Библия",
    "Living Stream Ministry",
    "Alphabetically search",
    "閱讀中文聖經",
]

# Minimum character length for <p> tags only — NOT applied to headings.
# Set to 3 to skip truly empty or whitespace-only nodes while allowing
# short-but-real paragraph content (e.g. single-sentence sub-points).
_MIN_P_LENGTH = 3


def _is_nav_text(text: str) -> bool:
    return any(p.search(text) for p in _SKIP_TEXT_PATTERNS)


def _is_footer(text: str) -> bool:
    return any(s in text for s in _FOOTER_SENTINELS)


def scrape_message_body(url: str, msg_number: int) -> tuple[str, list[dict]]:
    """
    Fetch a single message page and return:
      - clean HTML body content (str) — headings include id="hN" anchor attributes
      - list of heading dicts: [{level, text, anchor_id}, ...]

    The headings list drives the EPUB TOC.
    Returns ("", []) on failure.
    """
    soup = fetch(url)
    if soup is None:
        return "", []

    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    content_blocks: list[str] = []
    headings: list[dict] = []
    seen_texts: set[str] = set()
    heading_counter = 0

    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4"]):
        text = tag.get_text(" ", strip=True)

        if _is_footer(text):
            break

        # For <p> tags apply a small floor to skip truly empty nodes.
        # Headings are never filtered by length — even short ones like
        # "1. The fathers" are real content.
        if tag.name == "p" and len(text) < _MIN_P_LENGTH:
            continue

        if _is_nav_text(text):
            continue
        if re.match(rf"^Message\s+{msg_number}\b", text) and len(text) > 500:
            continue

        key = text[:120]
        if key in seen_texts:
            continue
        seen_texts.add(key)

        if tag.name in ("h1", "h2", "h3", "h4"):
            heading_counter += 1
            anchor_id = f"h{heading_counter}"
            level = int(tag.name[1])

            # Record for TOC
            headings.append({"level": level, "text": text, "anchor_id": anchor_id})

            # Emit with anchor id so TOC links jump here
            content_blocks.append(
                f'<{tag.name} id="{anchor_id}">{text}</{tag.name}>'
            )
        else:
            content_blocks.append(f"<p>{text}</p>")

    return "\n".join(content_blocks), headings


# ──────────────────────────────────────────────────────────────────────────────
# Phase 3 — Build EPUB
# ──────────────────────────────────────────────────────────────────────────────

_CSS = """
body {
    font-family: Georgia, serif;
    font-size: 1em;
    line-height: 1.6;
    margin: 1em 2em;
    color: #1a1a1a;
}
h1 { font-size: 1.4em; margin-top: 1.5em; }
h2 { font-size: 1.2em; margin-top: 1.2em; }
h3 { font-size: 1.1em; margin-top: 1em; }
p  { margin: 0.6em 0; text-align: justify; }
"""


def _build_toc_tree(headings: list[dict], chapter_filename: str) -> list:
    """
    Convert a flat list of heading dicts into a nested ebooklib TOC structure.

    We use only epub.Link (never epub.Section) to avoid the dropdown-arrow /
    duplicate-title behaviour that Section triggers in Kindle and most readers.

    ebooklib supports two tuple forms:
      - epub.Link                  → plain leaf entry
      - (epub.Link, [children])    → entry with nested children, no arrow/dropdown

    The nesting is expressed via a stack.  Each entry owns a live `children`
    list; sub-headings are appended into it after the tuple is already built,
    which works because Python lists are mutable references.
    """
    root: list = []
    stack: list[tuple[int, list]] = []  # (level, live_children_list)

    for h in headings:
        level = h["level"]
        href = f"{chapter_filename}#{h['anchor_id']}"
        link = epub.Link(href=href, title=h["text"], uid=h["anchor_id"])

        # Close any open nodes at the same or deeper level
        while stack and stack[-1][0] >= level:
            stack.pop()

        children: list = []
        entry = (link, children)  # children is the live list

        if not stack:
            root.append(entry)
        else:
            stack[-1][1].append(entry)

        # Push so sub-headings append into our children list
        stack.append((level, children))

    return root


def _build_toc_page(
    series_title: str,
    msg: dict,
    headings: list[dict],
    css_item: epub.EpubItem,
) -> epub.EpubHtml:
    """
    Build a standalone HTML TOC page that opens first when the book is loaded.

    Each heading becomes a clickable link that jumps to the anchor in chapter.xhtml.
    Indentation is driven by the heading level (h2 → no indent, h3 → 1 level, h4 → 2).
    """
    msg_title_str = f"Message {msg['number']:03d}: {msg['title']}"

    if headings:
        items_html: list[str] = []
        for h in headings:
            # h2 → indent 0, h3 → indent 1, h4 → indent 2
            indent = h["level"] - 2
            indent_style = f"margin-left:{indent * 1.5}em;" if indent > 0 else ""
            items_html.append(
                f'<p class="toc-entry" style="{indent_style}">'
                f'<a href="chapter.xhtml#{h["anchor_id"]}">{h["text"]}</a>'
                f'</p>'
            )
        toc_body = "\n  ".join(items_html)
    else:
        toc_body = '<p><em>No sections found.</em></p>'

    html = f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>Contents — {msg['title']}</title>
  <link rel="stylesheet" type="text/css" href="../style/main.css"/>
  <style type="text/css">
    .toc-title   {{ font-size: 1.1em; font-weight: bold; margin: 0 0 0.2em 0; }}
    .toc-series  {{ font-size: 0.9em; color: #555; margin: 0 0 1.5em 0; }}
    .toc-heading {{ font-size: 1em; font-weight: bold; margin: 1.2em 0 0.6em 0;
                   text-transform: uppercase; letter-spacing: 0.05em;
                   color: #444; border-bottom: 1px solid #ccc; padding-bottom: 0.2em; }}
    .toc-entry   {{ margin: 0.35em 0; }}
    .toc-entry a {{ text-decoration: none; color: #1a1a1a; }}
    .toc-entry a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <p class="toc-title"><a href="chapter.xhtml#msg-title">{msg_title_str}</a></p>
  <p class="toc-series"><em>{series_title}</em></p>
  <p class="toc-heading">Contents</p>
  {toc_body}
</body>
</html>"""

    page = epub.EpubHtml(
        title=f"Contents — {msg['title']}",
        file_name="toc-page.xhtml",
        lang="en",
    )
    page.content = html.encode("utf-8")
    page.add_item(css_item)
    return page


def build_epub(
    series_title: str,
    msg: dict,
    body_html: str,
    headings: list[dict],
    output_path: Path,
) -> None:
    """Assemble and write a single EPUB file."""
    book = epub.EpubBook()

    uid = f"{slugify(series_title)}-msg-{msg['number']:03d}"
    book.set_identifier(uid)
    book.set_title(f"{msg['number']:03d} - {msg['title']}")
    book.set_language("en")
    book.add_author("Witness Lee")

    book.add_metadata("DC", "subject", series_title)
    book.add_metadata("DC", "description",
                      f"Message {msg['number']:03d} of {series_title}")
    book.add_metadata(None, "meta", "", {
        "name": "calibre:series",
        "content": series_title,
    })
    book.add_metadata(None, "meta", "", {
        "name": "calibre:series_index",
        "content": str(msg["number"]),
    })

    css_item = epub.EpubItem(
        uid="style",
        file_name="style/main.css",
        media_type="text/css",
        content=_CSS,
    )
    book.add_item(css_item)

    if not body_html:
        body_html = "<p><em>(Body content could not be retrieved for this message.)</em></p>"

    chapter_html = f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>{msg['title']}</title>
  <link rel="stylesheet" type="text/css" href="../style/main.css"/>
</head>
<body>
  <h1 id="msg-title">Message {msg['number']:03d}: {msg['title']}</h1>
  <p><em>{series_title}</em></p>
  <hr/>
  {body_html}
</body>
</html>"""

    chapter = epub.EpubHtml(
        title=msg["title"],
        file_name="chapter.xhtml",
        lang="en",
    )
    chapter.content = chapter_html.encode("utf-8")
    chapter.add_item(css_item)
    book.add_item(chapter)

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # ── TOC page (shown first when book opens) ────────────────────────────────
    toc_page = _build_toc_page(series_title, msg, headings, css_item)
    book.add_item(toc_page)

    # ── NCX / Nav TOC (used by the reader's built-in TOC panel) ──────────────
    # Structure (Link-only, no Section — avoids dropdown arrows and duplicates):
    #   Message NNN: Title          ← plain link to #msg-title
    #   Section I: …                ← h2 (indented under it if it has children)
    #     A. Sub …                  ← h3
    #     B. Sub …
    #   Section II: …
    msg_title_str = f"Message {msg['number']:03d}: {msg['title']}"
    msg_title_href = "chapter.xhtml#msg-title"
    msg_title_link = epub.Link(msg_title_href, msg_title_str, "msg-title")

    if headings:
        heading_tree = _build_toc_tree(headings, "chapter.xhtml")
        book.toc = (msg_title_link, *heading_tree)
    else:
        book.toc = (msg_title_link,)

    # TOC page is first in spine so the book opens there
    book.spine = [toc_page, chapter]
    epub.write_epub(str(output_path), book, {})


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    index_url = sys.argv[1].rstrip("/") + "/"

    series_title, messages = discover_messages(index_url)

    series_slug = series_slug_from_url(index_url)
    out_dir = Path(series_slug)
    out_dir.mkdir(exist_ok=True)
    log.info("Output folder: %s/", out_dir)

    total = len(messages)
    success = 0
    skipped = 0

    for i, msg in enumerate(messages, 1):
        num = msg["number"]
        title = msg["title"]
        filename = f"{num:03d}-{slugify(title)}.epub"
        output_path = out_dir / filename

        log.info("[%d/%d] Message %03d: %s", i, total, num, title)

        time.sleep(REQUEST_DELAY)
        body_html, headings = scrape_message_body(msg["url"], num)

        if not body_html:
            log.warning("  ↳ No body content retrieved — will include outline only.")
            skipped += 1
        else:
            log.info("  ↳ Found %d headings for TOC.", len(headings))

        try:
            build_epub(series_title, msg, body_html, headings, output_path)
            log.info("  ↳ Saved: %s", output_path)
            success += 1
        except Exception as exc:
            log.warning("  ↳ EPUB build failed for message %d: %s", num, exc)

    log.info("─" * 60)
    log.info(
        "Done. %d/%d EPUBs created in '%s/'  (%d had no body content)",
        success, total, series_slug, skipped,
    )


if __name__ == "__main__":
    main()