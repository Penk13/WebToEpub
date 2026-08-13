#!/usr/bin/env python3
"""
cwwn_vol_1.py
-------------
Converts "Collected Works of Watchman Nee (Set 1) Vol. 01: The Christian Life
and Warfare" on bibleread.online into one EPUB file per page, with Calibre
series metadata.

Differences from cwwn_vol_12_14.py:
  - The vol-01 index page's #cont anchors carry sub-heading text, NOT page
    titles with "section N" / "ch.N" markers, so section/chapter metadata
    is not available.
  - Page titles are taken from each page's own first <h1> heading.
  - No subtitle line ("Section X  •  Chapter Y") above the title.
  - No interactive override prompt.

Usage:
    python cwwn_vol_1.py <book_index_url>

Example:
    python cwwn_vol_1.py "https://bibleread.online/all-books-by-Watchman-Nee-and-Witness-Lee/book-collected-works-of-watchman-nee-the-set-1-vol-01-the-christian-life-and-warfare-Watchman-Nee-read-online/"

Output:
    ./ccwn_vol01/<NNN>-<Title>.epub
"""

import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ebooklib import epub


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
DELAY_SECONDS = 1.5
OUTPUT_DIR = Path("output")

BOILERPLATE_FRAGMENTS = [
    "Ru Библия читать онлайн",
    "Es Biblia leer en línea",
    "Zh 閱讀中文聖經",
    "Living Stream Ministry",
    "Download Android app",
    "Play audio",
    "Alphabetically search",
    "Fill in the form",
    "Quick transfer",
    "Hover your cursor",
    "You can hide links",
    "New book",
    "Speaking the Truth in Love",
    "This is how denominations",
    "Advise you to read",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def slugify(text: str) -> str:
    text = text.strip()
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_boilerplate(text: str) -> bool:
    return any(frag in text for frag in BOILERPLATE_FRAGMENTS)


# ---------------------------------------------------------------------------
# Step 1 – Parse the index page
# ---------------------------------------------------------------------------

def parse_index(index_url: str):
    """
    Returns:
        book_title  – str
        total_pages – int
        base_url    – str (no trailing slash)

    Unlike vol 12-14, the vol-01 index anchors only carry sub-heading text,
    so titles are NOT extracted here — each page's first <h1> is used instead.
    The index page is used only to discover the book title and page count
    (from the "Chapters: [1] [2] ... [N]" navigation buttons).
    """
    print(f"[index] Fetching {index_url}")
    soup = fetch(index_url)

    # Book title
    h1 = soup.find("h1")
    if h1:
        book_title = h1.get_text(strip=True)
    else:
        title_tag = soup.find("title")
        book_title = title_tag.get_text(strip=True) if title_tag else "Unknown Book"
    book_title = re.sub(r"\s+read online\s*$", "", book_title, flags=re.I).strip()

    base_url = index_url.rstrip("/")
    book_slug = base_url.split("/")[-1]

    # Nav buttons:  /N/  (bare page links)
    nav_pat = re.compile(r"/(\d+)/$")

    total_pages = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if book_slug not in href:
            continue
        m_nav = nav_pat.search(href)
        if m_nav:
            total_pages = max(total_pages, int(m_nav.group(1)))

    if total_pages == 0:
        raise ValueError(
            "Could not detect any chapter pages from the index page.\n"
            "Make sure you passed the book index URL (not a chapter URL)."
        )

    print(f"[index] Book      : {book_title!r}")
    print(f"[index] Pages     : {total_pages}")
    return book_title, total_pages, base_url


# ---------------------------------------------------------------------------
# Step 2 – Page title and content scraping
# ---------------------------------------------------------------------------

def page_title(soup: BeautifulSoup) -> str:
    """Return the page's first <h1> heading text (used as the EPUB title)."""
    h1 = soup.find("h1")
    return h1.get_text(separator=" ", strip=True) if h1 else "Page"


def scrape_page(soup: BeautifulSoup) -> str:
    body = soup.find("body")
    if not body:
        return "<p>(no content)</p>"

    content_parts: list[str] = []
    recording = False

    for el in body.descendants:
        if not hasattr(el, "name") or el.name is None:
            continue

        tag = el.name.lower()
        if tag not in {"h1", "h2", "h3", "h4", "p", "blockquote"}:
            continue

        cls = " ".join(el.get("class", [])).lower()
        eid = el.get("id", "").lower()
        if any(kw in cls for kw in ["nav", "header", "footer", "button", "menu"]):
            continue
        if any(kw in eid for kw in ["nav", "header", "footer"]):
            continue

        text = el.get_text(separator=" ", strip=True)
        if not text:
            continue

        if is_boilerplate(text):
            break

        if len(text) < 50 and re.match(
            r"^(←|→|ch\.|Listen|Back|Show|Hide|\d+\s*/|\s*ch\s+\d)", text, re.I
        ):
            continue

        if tag in {"h1", "h2", "h3", "h4"}:
            recording = True

        if not recording:
            continue

        if tag == "h1":
            content_parts.append(f"<h1>{text}</h1>")
        elif tag == "h2":
            content_parts.append(f"<h2>{text}</h2>")
        elif tag == "h3":
            content_parts.append(f"<h3>{text}</h3>")
        elif tag == "h4":
            content_parts.append(f"<h4>{text}</h4>")
        elif tag == "p":
            content_parts.append(f"<p>{text}</p>")
        elif tag == "blockquote":
            content_parts.append(f"<blockquote><p>{text}</p></blockquote>")

    # Remove consecutive duplicate lines
    deduped: list[str] = []
    prev = None
    for part in content_parts:
        if part != prev:
            deduped.append(part)
        prev = part

    return "\n".join(deduped) if deduped else "<p>(no content retrieved)</p>"


# ---------------------------------------------------------------------------
# Step 3 – Build a TOC page from the content headings
# ---------------------------------------------------------------------------

def build_toc_page(page_title: str, content_html: str) -> str:
    """
    Parse all headings (h1–h4) from content_html and return an XHTML string
    for a Table of Contents page with anchor links into chapter.xhtml.
    """
    soup = BeautifulSoup(content_html, "lxml")
    headings = soup.find_all(["h1", "h2", "h3", "h4"])

    # Assign a stable anchor id to each heading: h-0, h-1, …
    items: list[tuple[str, str, str]] = []   # (tag, anchor_id, text)
    for i, h in enumerate(headings):
        anchor_id = f"h-{i}"
        text = h.get_text(strip=True)
        items.append((h.name, anchor_id, text))

    # Indentation per heading level
    indent = {"h1": "0", "h2": "1.5em", "h3": "3em", "h4": "4.5em"}

    rows = []
    for tag, anchor_id, text in items:
        margin = indent.get(tag, "0")
        rows.append(
            f'    <li style="margin-left:{margin}">'
            f'<a href="chapter.xhtml#{anchor_id}">{text}</a></li>'
        )

    toc_body = "\n".join(rows)

    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<head>\n"
        f"  <title>Contents – {page_title}</title>\n"
        '  <meta charset="utf-8"/>\n'
        "  <style>\n"
        "    body { font-family: sans-serif; margin: 1.5em; line-height: 1.8; }\n"
        "    h2   { font-size: 1em; text-transform: uppercase;\n"
        "           letter-spacing: 0.08em; color: #555; margin-bottom: 0.5em; }\n"
        "    ul   { list-style: none; margin: 0; padding: 0; }\n"
        "    li   { margin-bottom: 0.15em; }\n"
        "    a    { text-decoration: none; color: #222; }\n"
        "    a:hover { text-decoration: underline; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <h2>Contents</h2>\n"
        "  <ul>\n"
        f"{toc_body}\n"
        "  </ul>\n"
        "</body>\n"
        "</html>"
    )


# ---------------------------------------------------------------------------
# Step 4 – Inject anchor ids into content_html to match the TOC links
# ---------------------------------------------------------------------------

def inject_anchors(content_html: str) -> str:
    """
    Add id="h-N" attributes to every h1–h4 in content_html so TOC links resolve.
    Returns the modified HTML string.
    """
    counter = [0]

    def add_id(m: re.Match) -> str:
        tag  = m.group(1)   # e.g. "h2"
        rest = m.group(2)   # everything up to >
        text = m.group(3)
        anchor_id = f"h-{counter[0]}"
        counter[0] += 1
        return f"<{tag} id=\"{anchor_id}\"{rest}>{text}</{tag}>"

    return re.sub(
        r"<(h[1-4])([^>]*)>(.*?)</h[1-4]>",
        add_id,
        content_html,
        flags=re.DOTALL,
    )


# ---------------------------------------------------------------------------
# Step 5 – Build EPUB
# ---------------------------------------------------------------------------

def build_epub(
    page_num:     int,
    page_title:   str,
    book_title:   str,
    content_html: str,
    output_dir:   Path,
) -> Path:
    book = epub.EpubBook()
    book.set_identifier(f"{book_title}--{page_num}")
    book.set_title(page_title)
    book.set_language("en")
    book.add_author("Watchman Nee")

    # Calibre series metadata
    book.add_metadata("OPF", "meta", None,
                      {"name": "calibre:series", "content": book_title})
    book.add_metadata("OPF", "meta", None,
                      {"name": "calibre:series_index", "content": str(page_num)})

    # Inject anchors into content so TOC links resolve
    anchored_html = inject_anchors(content_html)
    toc_xhtml = build_toc_page(page_title, content_html)

    chapter_item = epub.EpubHtml(
        title=page_title,
        file_name="chapter.xhtml",
        lang="en",
    )
    chapter_item.content = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<head>\n"
        f"  <title>{page_title}</title>\n"
        '  <meta charset="utf-8"/>\n'
        "  <style>\n"
        "    body       { font-family: serif; margin: 1.5em; line-height: 1.6; }\n"
        "    h1, h2, h3 { font-family: sans-serif; }\n"
        "    blockquote { border-left: 3px solid #ccc; margin-left: 1em;\n"
        "                 padding-left: 1em; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"{anchored_html}\n"
        "</body>\n"
        "</html>"
    ).encode("utf-8")

    toc_item = epub.EpubHtml(
        title=f"Contents – {page_title}",
        file_name="toc.xhtml",
        lang="en",
    )
    toc_item.content = toc_xhtml.encode("utf-8")

    book.add_item(toc_item)
    book.add_item(chapter_item)
    book.toc = [
        epub.Link("toc.xhtml",     f"Contents – {page_title}", "toc"),
        epub.Link("chapter.xhtml", page_title,                  "chapter"),
    ]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", toc_item, chapter_item]

    safe_title = slugify(page_title)[:80]
    filename = f"{page_num:03d}-{safe_title}.epub"
    out_path = output_dir / filename
    epub.write_epub(str(out_path), book)
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    index_url = sys.argv[1].rstrip("/") + "/"

    parsed = urlparse(index_url)
    if "bibleread.online" not in parsed.netloc:
        print("ERROR: This script only works with bibleread.online URLs.")
        sys.exit(1)
    if "/all-books-by-Watchman-Nee-and-Witness-Lee/" not in index_url:
        print(
            "ERROR: URL must be from the /all-books-by-Watchman-Nee-and-Witness-Lee/ section."
        )
        sys.exit(1)

    book_title, total_pages, base_url = parse_index(index_url)

    vol_match = re.search(r"-vol-(\d+)-", index_url)
    vol_number = vol_match.group(1) if vol_match else "0"
    output_dir = Path(f"ccwn_vol{vol_number}")
    output_dir.mkdir(exist_ok=True)

    success = 0
    for page_num in range(1, total_pages + 1):

        page_url = f"{base_url}/{page_num}/"
        print(f"\n[{page_num}/{total_pages}]  URL : {page_url}")

        try:
            soup = fetch(page_url)
            title = page_title(soup)
            content_html = scrape_page(soup)
            out_path = build_epub(
                page_num=page_num,
                page_title=title,
                book_title=book_title,
                content_html=content_html,
                output_dir=output_dir,
            )
            print(f"  Title: {title!r}")
            print(f"  EPUB : {out_path}  ({out_path.stat().st_size:,} bytes)")
            success += 1
        except Exception as exc:
            print(f"  ERROR: {exc}")

        if page_num < total_pages:
            time.sleep(DELAY_SECONDS)

    print(f"\n{'='*60}")
    print(f"Done: {success}/{total_pages} EPUB files saved → ./{output_dir}/")


if __name__ == "__main__":
    main()
