from bs4 import BeautifulSoup

from webtoepub.clean import (
    extract_blocks,
    is_footer,
    is_nav,
    promote_headings,
    smart_title,
    strip_leading_echoes,
)
from webtoepub.model import Block

LONG = "word " * 50  # > 200 chars: real content, never UI


def soup(body: str) -> BeautifulSoup:
    return BeautifulSoup(f"<html><body>{body}</body></html>", "lxml")


def test_footer_stops_reading():
    blocks = extract_blocks(soup("<p>Real text here.</p><p>Living Stream Ministry</p><p>After footer.</p>"))
    assert [b.text for b in blocks] == ["Real text here."]


def test_long_paragraph_mentioning_footer_phrase_is_kept():
    para = f"He read books put out by the Living Stream Ministry. {LONG}"
    blocks = extract_blocks(soup(f"<p>{para}</p><p>Still here.</p>"))
    assert [b.text for b in blocks] == [para.strip(), "Still here."]


def test_nav_strings_skipped_but_reading_continues():
    blocks = extract_blocks(soup("<p>Play audio</p><p>12</p><p>!</p><p>Content.</p>"))
    assert [b.text for b in blocks] == ["Content."]


def test_long_text_is_never_nav():
    assert is_nav("Show header")
    assert not is_nav(f"Show header {LONG}")
    assert not is_footer(f"Alphabetically search {LONG}")


def test_strip_tags_and_ui_classes():
    html = (
        '<nav><p>Menu item</p></nav><p class="nav-link">Nav p</p>'
        '<h2 id="header-title">Site</h2><h2>Heading</h2><p>Body.</p>'
    )
    # Only the element's own class/id is checked: an article wrapper with a
    # class like "content-header" must not hide the article.
    assert [b.text for b in extract_blocks(soup(html))] == ["Heading", "Body."]


def test_blockquote_emitted_once():
    blocks = extract_blocks(soup("<blockquote><p>Quoted.</p></blockquote><p>After.</p>"))
    assert blocks == [Block("quote", "Quoted."), Block("p", "After.")]


def test_only_consecutive_repeats_dropped():
    html = "<p>Refrain!</p><p>Refrain!</p><p>Verse.</p><p>Refrain!</p>"
    assert [b.text for b in extract_blocks(soup(html))] == ["Refrain!", "Verse.", "Refrain!"]


def test_source_skip_hook():
    blocks = extract_blocks(soup("<p>Drop me</p><p>Keep me</p>"), skip=lambda tag, t: t == "Drop me")
    assert [b.text for b in blocks] == ["Keep me"]


def test_strip_leading_echoes():
    blocks = [
        Block("p", "Life-Study of Romans"),
        Block("p", "Message 2"),
        Block("h", "CHAPTER ONE", 1),
        Block("h", "The Gospel of God", 1),
        Block("p", "Scripture Reading"),
        Block("p", "Life-Study of Romans"),  # not leading: kept
    ]
    body, generic = strip_leading_echoes(
        blocks, {"The Gospel of God", "Life-Study of Romans", "Message 2"}
    )
    assert [b.text for b in body] == ["Scripture Reading", "Life-Study of Romans"]
    assert generic == "CHAPTER ONE"


def test_numbered_title_echo():
    from webtoepub.model import PageRef
    from webtoepub.sources import Source

    src = Source()
    ch = src.finish(
        PageRef(6, "u", "The Rehearsal of the Law (1)"),
        [Block("h", "The Rehearsal of the Law", 1), Block("p", "(1)"), Block("p", "Body.")],
    )
    assert [b.text for b in ch.blocks] == ["Body."]


def test_echo_match_ignores_case_quotes_and_end_punctuation():
    body, _ = strip_leading_echoes([Block("h", "GOD’S WILL.", 1), Block("p", "x")], {"God's will"})
    assert [b.text for b in body] == ["x"]


def test_promote_headings():
    blocks = [Block("h", "a", 1), Block("p", "t"), Block("h", "b", 2)]
    assert [b.level for b in promote_headings(blocks) if b.kind == "h"] == [2, 3]
    already = [Block("h", "a", 2), Block("h", "b", 3)]
    assert promote_headings(already) == already


def test_smart_title():
    assert smart_title("WALKING IN GOD'S WILL") == "Walking in God's Will"
    assert smart_title("I. DYING WITH THE LORD TO SIN") == "I. Dying with the Lord to Sin"
    assert smart_title("THE WORD OF THE CROSS") == "The Word of the Cross"
    assert smart_title("UNIVERSAL FATHERHOOD: A FALLACY") == "Universal Fatherhood: A Fallacy"
    assert smart_title("Living by faith") == "Living by faith"  # not all caps: unchanged
