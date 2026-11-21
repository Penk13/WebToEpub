import zipfile
from xml.dom import minidom

from bs4 import BeautifulSoup

from webtoepub.epub_build import build_epub
from webtoepub.model import Block, Chapter, Series
from webtoepub.naming import epub_filename, slugify
from webtoepub.sources.cwwn import kicker, parse_index, series_name


def test_slugify():
    assert slugify("God's Choice") == "Gods-Choice"
    assert slugify("God’s demand and Pharaoh's resistance (1)") == "Gods-demand-and-Pharaohs-resistance-1"
    assert slugify("The analysis of the spirit — the intuition") == "The-analysis-of-the-spirit-the-intuition"
    assert slugify("Trailing dots...") == "Trailing-dots"
    assert slugify("???") == "untitled"
    long = slugify("word " * 40)
    assert len(long) <= 80 and not long.endswith("-")


def test_epub_filename():
    assert epub_filename(7, "A & B") == "007-A-B.epub"


def test_cwwn_series_name():
    url = "https://x/book-collected-works-of-watchman-nee-the-set-1-vol-12-the-spiritual-man-1-Watchman-Nee-read-online/"
    title = "Collected Works of Watchman Nee, The (Set 1) Vol. 12: The Spiritual Man (1)"
    assert series_name(title, url) == ("CWWN (1.12) - The Spiritual Man (1)", "cwwn-set-1-vol-12")


def test_cwwn_parse_index_markers():
    slug = "book-x"
    html = (
        f'<a href="/b/{slug}/1/#cont1">Introduction section 1</a>'
        f'<a href="/b/{slug}/2/#cont2">The spirit ch.1</a>'
        f'<a href="/b/{slug}/3/#cont3">The soul ch.2</a>'
        f'<a href="/b/{slug}/4/">4</a>'
    )
    total, info, markers = parse_index(BeautifulSoup(html, "lxml"), slug)
    assert total == 4 and markers
    assert info[1] == {"title": "Introduction", "section": 1, "chapter": None}
    assert info[3] == {"title": "The soul", "section": 1, "chapter": 2}
    assert kicker(1, 2) == "Section One  •  Chapter 2"


def test_build_epub_is_valid_and_escaped(tmp_path):
    series = Series("A & B <Series>", "Witness Lee", "Message", "a-b")
    ch = Chapter(
        3,
        'Title with "quotes" & <tags>',
        [Block("h", "Sec & 1", 2), Block("p", "x < y"), Block("h", "Sub", 3), Block("quote", "q")],
        kicker="Message 3",
    )
    path = tmp_path / "out.epub"
    build_epub(series, ch, path)

    z = zipfile.ZipFile(path)
    for name in z.namelist():
        if name.endswith((".xhtml", ".opf", ".ncx")):
            minidom.parseString(z.read(name))  # raises if not well-formed
    chapter = z.read("EPUB/chapter.xhtml").decode()
    assert "x &lt; y" in chapter and 'id="h1"' in chapter and 'id="h2"' in chapter
    opf = z.read("EPUB/content.opf").decode()
    assert "003 - Title with" in opf
    assert 'name="calibre:series_index" content="3"' in opf
    # Opens on the contents page, then the chapter; nav is not in the spine.
    assert opf.index('idref="contents"') < opf.index('idref="chapter"')
    assert 'idref="nav"' not in opf
