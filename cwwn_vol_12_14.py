#!/usr/bin/env python3
"""
cwwn_vol_12_14.py
---------------
Converts a "Collected Works of Watchman Nee (The Spiritual Man)" book on bibleread.online
into one EPUB file per page, with Calibre series metadata.

  - Each EPUB has the book's section and chapter number above its title.
  - Filename format: NNN-Title.epub  (NNN = page number, zero-padded)

Usage:
    python cwwn_vol_12_14.py <book_index_url>

Example:
    python cwwn_vol_12_14.py "https://bibleread.online/all-books-by-Watchman-Nee-and-Witness-Lee/book-collected-works-of-watchman-nee-the-set-1-vol-12-the-spiritual-man-1-Watchman-Nee-read-online/"

Output:
    ./output/<NNN>-<Title>.epub
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


def ordinal_section(n: int) -> str:
    """Return 'Section One', 'Section Two', etc. up to 10; fallback to numeric."""
    words = ["One","Two","Three","Four","Five","Six","Seven","Eight","Nine","Ten"]
    if 1 <= n <= len(words):
        return f"Section {words[n-1]}"
    return f"Section {n}"


# ---------------------------------------------------------------------------
# Step 1 – Parse the index page
# ---------------------------------------------------------------------------

def parse_index(index_url: str):
    """
    Returns:
        book_title  – str
        page_info   – dict  page_num -> {title, section, chapter}
        total_pages – int
        base_url    – str (no trailing slash)
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

    # Patterns for href matching
    anchor_pat = re.compile(r"/(\d+)/#")   # /N/#contXX  — carries real title text
    nav_pat    = re.compile(r"/(\d+)/$")   # /N/         — bare nav buttons

    # ---------------------------------------------------------------------------
    # Patterns for extracting section/chapter markers from link text.
    #
    # The site encodes structural metadata by appending tags to the link text:
    #   "An introduction concerning the spirit, the soul, and the body section 1"
    #   "The spirit, the soul, and the body ch.1"
    #
    # "section N" → marks the START of a new book section; the title before it
    #               is the section's own heading title.
    # "ch.N"      → marks which chapter this page belongs to; the title before
    #               it is the chapter title.
    #
    # Both suffixes must be stripped from the title before it is stored,
    # so filenames are clean (no "section 1" or "ch.1" appended).
    # ---------------------------------------------------------------------------
    # Matches " section N" or " Section N" or " section.N" at the end of a label (with leading space)
    section_pat = re.compile(r"\s+section[.\s]+(\d+)\s*$", re.I)
    # Matches " ch.N" at the end (with optional leading space)
    chapter_pat = re.compile(r"\s+ch\.(\d+)\s*$", re.I)
    # Matches "ch.N" glued directly to the title (no space before)
    chapter_glued_pat = re.compile(r"ch\.(\d+)\s*$", re.I)

    current_section: int | None = None
    current_chapter: int | None = None
    total_pages = 0
    page_info: dict[int, dict] = {}

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if book_slug not in href:
            continue

        m_anchor = anchor_pat.search(href)
        m_nav    = nav_pat.search(href)

        if m_anchor:
            page_num = int(m_anchor.group(1))
            total_pages = max(total_pages, page_num)

            raw_label = a.get_text(separator=" ", strip=True)
            if not raw_label or raw_label.isdigit() or len(raw_label) <= 2:
                continue

            # --- Detect and strip "section N" suffix ---
            # This marks the beginning of a new book section.
            sm = section_pat.search(raw_label)
            if sm:
                current_section = int(sm.group(1))
                current_chapter = None          # chapter counter resets each section
                raw_label = raw_label[:sm.start()].strip()

            # --- Detect and strip "ch.N" suffix (with or without leading space) ---
            cm = chapter_pat.search(raw_label) or chapter_glued_pat.search(raw_label)
            if cm:
                current_chapter = int(cm.group(1))
                raw_label = re.sub(r"\s*ch\.\d+\s*$", "", raw_label, flags=re.I).strip()

            # Record only the first meaningful title per page
            if raw_label and page_num not in page_info:
                page_info[page_num] = {
                    "title":   raw_label,
                    "section": current_section,
                    "chapter": current_chapter,
                }

        elif m_nav:
            page_num = int(m_nav.group(1))
            total_pages = max(total_pages, page_num)

    if total_pages == 0:
        raise ValueError(
            "Could not detect any chapter pages from the index page.\n"
            "Make sure you passed the book index URL (not a chapter URL)."
        )

    # Fill any gaps
    for n in range(1, total_pages + 1):
        if n not in page_info:
            page_info[n] = {"title": f"Page {n}", "section": None, "chapter": None}

    print(f"[index] Book      : {book_title!r}")
    print(f"[index] Pages     : {total_pages}")
    print(f"\n  {'Page':>4}  {'Sec':>4}  {'Ch':>4}  Title")
    print(f"  {'-'*60}")
    for n in sorted(page_info):
        info = page_info[n]
        sec = str(info["section"]) if info["section"] else "-"
        ch  = str(info["chapter"]) if info["chapter"] else "-"
        print(f"  {n:>4}  {sec:>4}  {ch:>4}  {info['title']}")

    return book_title, page_info, total_pages, base_url


# ---------------------------------------------------------------------------
# Step 2 – Scrape content from a chapter page
# ---------------------------------------------------------------------------

def scrape_page(page_url: str) -> str:
    soup = fetch(page_url)
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
    page_num:    int,
    page_title:  str,
    section:     int | None,
    chapter:     int | None,
    book_title:  str,
    content_html: str,
    output_dir:  Path,
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

    # Build the subtitle line shown above the title
    # e.g. "Section Two  •  Chapter 3"  or  "Section One"  or nothing
    subtitle_parts = []
    if section is not None:
        subtitle_parts.append(ordinal_section(section))
    if chapter is not None:
        subtitle_parts.append(f"Chapter {chapter}")
    subtitle_html = (
        f'<p class="subtitle">{" &bull; ".join(subtitle_parts)}</p>\n'
        if subtitle_parts else ""
    )

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
        "    .subtitle  { font-family: sans-serif; font-size: 0.85em;\n"
        "                 color: #666; letter-spacing: 0.05em;\n"
        "                 text-transform: uppercase; margin-bottom: 0.2em; }\n"
        "    blockquote { border-left: 3px solid #ccc; margin-left: 1em;\n"
        "                 padding-left: 1em; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"{subtitle_html}"
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

    book_title, page_info, total_pages, base_url = parse_index(index_url)

    # --- Interactive correction of section / chapter values ---
    print("\nReview the table above.")
    print("You may now override section and chapter for any page.")
    print("Format: <page> <section> <chapter>  (use 0 to clear a value)")
    print("Enter a blank line when done.\n")
    while True:
        raw = input("  Override (or Enter to continue): ").strip()
        if not raw:
            break
        parts = raw.split()
        if len(parts) != 3:
            print("  Please enter exactly three numbers: page section chapter")
            continue
        try:
            pg, sec, ch = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            print("  All three values must be integers.")
            continue
        if pg not in page_info:
            print(f"  Page {pg} not found (valid range: 1–{total_pages}).")
            continue
        page_info[pg]["section"] = sec if sec != 0 else None
        page_info[pg]["chapter"] = ch  if ch  != 0 else None
        print(f"  Page {pg} → section={page_info[pg]['section'] or '-'}, "
              f"chapter={page_info[pg]['chapter'] or '-'}")

    vol_match = re.search(r"-vol-(\d+)-", index_url)
    vol_number = vol_match.group(1) if vol_match else "0"
    output_dir = Path(f"ccwn_vol{vol_number}")
    output_dir.mkdir(exist_ok=True)

    success = 0
    for page_num in range(1, total_pages + 1):

        info = page_info.get(page_num, {"title": f"Page {page_num}",
                                         "section": None, "chapter": None})
        title   = info["title"]
        section = info["section"]
        chapter = info["chapter"]

        page_url = f"{base_url}/{page_num}/"
        print(f"\n[{page_num}/{total_pages}] {title!r}  "
              f"(sec={section or '-'}, ch={chapter or '-'})")
        print(f"  URL : {page_url}")

        try:
            content_html = scrape_page(page_url)
            out_path = build_epub(
                page_num=page_num,
                page_title=title,
                section=section,
                chapter=chapter,
                book_title=book_title,
                content_html=content_html,
                output_dir=output_dir,
            )
            print(f"  EPUB: {out_path}  ({out_path.stat().st_size:,} bytes)")
            success += 1
        except Exception as exc:
            print(f"  ERROR: {exc}")

        if page_num < total_pages:
            time.sleep(DELAY_SECONDS)

    print(f"\n{'='*60}")
    print(f"Done: {success}/{total_pages} EPUB files saved → ./{output_dir}/")


if __name__ == "__main__":
    main()