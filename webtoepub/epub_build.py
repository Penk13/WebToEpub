"""Build one EPUB from a Chapter.

Every EPUB has the same layout:
  contents.xhtml  opens first: title, series, links to each heading
  chapter.xhtml   kicker line, title, series line, then the body
  nav / ncx       reader TOC: the title, then headings nested by level
"""

import os
from html import escape
from pathlib import Path

from ebooklib import epub

from webtoepub.model import Block, Chapter, Series

CSS = """
body { font-family: Georgia, serif; line-height: 1.6; margin: 1em 2em; color: #1a1a1a; }
h1 { font-size: 1.4em; margin: 0.2em 0 0.3em 0; }
h2 { font-size: 1.2em; margin-top: 1.2em; }
h3 { font-size: 1.1em; margin-top: 1em; }
h4, h5, h6 { font-size: 1em; margin-top: 1em; }
p { margin: 0.6em 0; text-align: justify; }
.li { text-align: left; margin: 0.3em 0; text-indent: -1.5em; }
blockquote { border-left: 3px solid #ccc; margin: 0.8em 0 0.8em 1em; padding-left: 1em; }
.kicker { font-family: sans-serif; font-size: 0.85em; color: #666;
          letter-spacing: 0.05em; text-transform: uppercase; margin: 0; text-align: left; }
.series { font-style: italic; color: #555; margin: 0 0 1em 0; text-align: left; }
.toc-heading { font-family: sans-serif; font-weight: bold; text-transform: uppercase;
               letter-spacing: 0.05em; color: #444; border-bottom: 1px solid #ccc;
               margin: 1.2em 0 0.6em 0; padding-bottom: 0.2em; }
.toc-entry { margin: 0.35em 0; text-align: left; }
.toc-entry a { text-decoration: none; color: #1a1a1a; }
"""

TITLE_ANCHOR = "title"


def _anchored_headings(blocks: list[Block]) -> list[tuple[Block, str]]:
    """Pair each block with its anchor id ("" for non-headings)."""
    out = []
    n = 0
    for b in blocks:
        if b.kind == "h":
            n += 1
            out.append((b, f"h{n}"))
        else:
            out.append((b, ""))
    return out


def _render_body(anchored: list[tuple[Block, str]]) -> str:
    parts = []
    for b, anchor in anchored:
        text = escape(b.text)
        if b.kind == "h":
            parts.append(f'<h{b.level} id="{anchor}">{text}</h{b.level}>')
        elif b.kind == "li":
            # Flat, indented paragraphs: e-readers render nested <ol> poorly
            # and the marker ("I.", "A.") is already part of the text.
            parts.append(f'<p class="li" style="margin-left:{b.level * 1.5}em">{text}</p>')
        elif b.kind == "quote":
            parts.append(f"<blockquote><p>{text}</p></blockquote>")
        else:
            parts.append(f"<p>{text}</p>")
    return "\n".join(parts)


def _xhtml(title: str, body: str) -> bytes:
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        f"<head><title>{escape(title)}</title></head>\n"
        f"<body>\n{body}\n</body>\n</html>"
    ).encode("utf-8")


def _toc_tree(headings: list[tuple[Block, str]]) -> list:
    """Nest headings by level: (Link, [children]) for parents, Link for leaves."""
    root: list = []
    stack: list[tuple[int, list]] = []
    for b, anchor in headings:
        while stack and stack[-1][0] >= b.level:
            stack.pop()
        children: list = []
        entry = [epub.Link(f"chapter.xhtml#{anchor}", b.text, anchor), children]
        (stack[-1][1] if stack else root).append(entry)
        stack.append((b.level, children))

    def finish(entries: list) -> list:
        return [
            (link, finish(children)) if children else link
            for link, children in entries
        ]

    return finish(root)


def build_epub(series: Series, ch: Chapter, out_path: Path) -> None:
    num = f"{ch.number:03d}"
    book = epub.EpubBook()
    book.set_identifier(f"webtoepub-{series.slug}-{num}")
    book.set_title(f"{num} - {ch.title}")
    book.set_language("en")
    book.add_author(series.author)
    book.add_metadata("DC", "subject", series.name)
    book.add_metadata("DC", "description", f"{series.unit} {ch.number} of {series.name}")
    book.add_metadata(None, "meta", "", {"name": "calibre:series", "content": series.name})
    book.add_metadata(None, "meta", "", {"name": "calibre:series_index", "content": str(ch.number)})

    css = epub.EpubItem(uid="style", file_name="style/main.css", media_type="text/css", content=CSS)
    book.add_item(css)

    blocks = ch.blocks or [Block("p", "(Content could not be retrieved for this page.)")]
    anchored = _anchored_headings(blocks)
    headings = [(b, a) for b, a in anchored if a]

    kicker = f'<p class="kicker">{escape(ch.kicker)}</p>\n' if ch.kicker else ""
    chapter_body = (
        f"{kicker}"
        f'<h1 id="{TITLE_ANCHOR}">{escape(ch.title)}</h1>\n'
        f'<p class="series">{escape(series.name)}</p>\n'
        "<hr/>\n"
        f"{_render_body(anchored)}"
    )
    chapter = epub.EpubHtml(uid="chapter", title=ch.title, file_name="chapter.xhtml", lang="en")
    chapter.content = _xhtml(ch.title, chapter_body)
    chapter.add_item(css)

    entries = [
        f'<p class="toc-entry" style="margin-left:{(b.level - 2) * 1.5}em">'
        f'<a href="chapter.xhtml#{a}">{escape(b.text)}</a></p>'
        for b, a in headings
    ] or ["<p><em>No sections.</em></p>"]
    contents_body = (
        f"{kicker}"
        f'<h1><a href="chapter.xhtml#{TITLE_ANCHOR}">{escape(ch.title)}</a></h1>\n'
        f'<p class="series">{escape(series.name)}</p>\n'
        '<p class="toc-heading">Contents</p>\n' + "\n".join(entries)
    )
    contents = epub.EpubHtml(uid="contents", title=f"Contents - {ch.title}", file_name="contents.xhtml", lang="en")
    contents.content = _xhtml(f"Contents - {ch.title}", contents_body)
    contents.add_item(css)

    book.add_item(contents)
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.toc = (
        epub.Link(f"chapter.xhtml#{TITLE_ANCHOR}", ch.title, TITLE_ANCHOR),
        *_toc_tree(headings),
    )
    # Opens on the contents page; the reader's own nav page is not in the spine.
    book.spine = [contents, chapter]
    # Write to a temp name, then rename: an interrupted run never leaves a
    # half-written NNN-*.epub that --skip-existing would treat as done.
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    try:
        epub.write_epub(str(tmp_path), book, {})
        os.replace(tmp_path, out_path)
    finally:
        tmp_path.unlink(missing_ok=True)
