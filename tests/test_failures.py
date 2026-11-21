import argparse

import pytest
from bs4 import BeautifulSoup

from webtoepub import cli, epub_build
from webtoepub.epub_build import build_epub
from webtoepub.model import Block, Chapter, PageRef, Series
from webtoepub.sources import Source

SERIES = Series("S", "Witness Lee", "Message", "s")


def test_build_epub_leaves_no_temp_file(tmp_path):
    path = tmp_path / "001-x.epub"
    build_epub(SERIES, Chapter(1, "X", [Block("p", "body")]), path)
    assert [p.name for p in tmp_path.iterdir()] == ["001-x.epub"]


def test_build_epub_failure_leaves_nothing(tmp_path, monkeypatch):
    def broken_write(name, book, opts):
        open(name, "wb").write(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(epub_build.epub, "write_epub", broken_write)
    with pytest.raises(OSError):
        build_epub(SERIES, Chapter(1, "X", [Block("p", "body")]), tmp_path / "001-x.epub")
    assert list(tmp_path.iterdir()) == []


class FakeFetcher:
    pages = {}

    def __init__(self, **kwargs):
        pass

    def soup(self, url):
        html = self.pages.get(url)
        return BeautifulSoup(html, "lxml") if html else None


class FakeSource(Source):
    def discover(self, fetcher, url):
        return SERIES, [PageRef(1, "u1", "One"), PageRef(2, "u2", "Two")]


def test_failed_fetch_writes_no_epub(tmp_path, monkeypatch):
    FakeFetcher.pages = {"u1": "<body><p>Real text here.</p></body>"}  # u2 fails
    monkeypatch.setattr(cli, "Fetcher", FakeFetcher)
    args = argparse.Namespace(url="http://x/", out=tmp_path, skip_existing=False,
                              delay=0, cache=None)

    assert cli.run(FakeSource(), args) == 1
    assert sorted(p.name for p in (tmp_path / "s").iterdir()) == ["001-One.epub"]

    # A resumed run retries the failed page instead of skipping it.
    FakeFetcher.pages["u2"] = "<body><p>Now it works.</p></body>"
    args.skip_existing = True
    assert cli.run(FakeSource(), args) == 0
    assert sorted(p.name for p in (tmp_path / "s").iterdir()) == ["001-One.epub", "002-Two.epub"]
