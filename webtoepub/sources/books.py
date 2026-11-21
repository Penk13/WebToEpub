"""Any book under /all-books-by-Watchman-Nee-and-Witness-Lee/ (one EPUB per chapter)."""

import logging
import re
from urllib.parse import urljoin, urlparse

from webtoepub.fetch import Fetcher
from webtoepub.model import PageRef, Series
from webtoepub.sources import Source

log = logging.getLogger(__name__)

BOOKS_PATH = "/all-books-by-Watchman-Nee-and-Witness-Lee/"


def book_slug(url: str) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[-1] if parts else "book"


def folder_slug(url: str) -> str:
    """book-abiding-in-the-lord-...-Witness-Lee-read-online -> abiding-in-the-lord-..."""
    slug = re.sub(r"-(witness-lee|watchman-nee)-read-online$", "", book_slug(url), flags=re.I)
    return re.sub(r"^book-", "", slug, flags=re.I).lower()


def detect_author(url: str) -> str:
    u = url.lower()
    if "watchman-nee" in u:
        return "Watchman Nee"
    if "witness-lee" in u:
        return "Witness Lee"
    return "Witness Lee / Watchman Nee"


def clean_book_title(title: str) -> str:
    return re.sub(r"\s+read online\s*$", "", title, flags=re.I).strip()


class Book(Source):
    def discover(self, fetcher: Fetcher, url: str) -> tuple[Series, list[PageRef]]:
        soup = fetcher.soup(url)
        if soup is None:
            raise SystemExit(f"Cannot fetch book page: {url}")
        h1 = soup.find("h1")
        self.series_title = clean_book_title(h1.get_text(strip=True)) if h1 else "Unknown Book"

        slug = book_slug(url)
        # Outline links: /<book-slug>/<N>/#contN  - bold text is the chapter title.
        outline = re.compile(rf"{re.escape(BOOKS_PATH)}{re.escape(slug)}/(\d+)/#cont", re.I)
        urls: dict[int, str] = {}
        titles: dict[int, str] = {}
        for a in soup.find_all("a", href=True):
            m = outline.search(a["href"])
            if not m:
                continue
            num = int(m.group(1))
            urls.setdefault(num, url.rstrip("/") + f"/{num}/")
            bold = a.find(["b", "strong"])
            if bold and num not in titles:
                title = re.sub(r"\s+ch\.\s*\d+$", "", bold.get_text(strip=True), flags=re.I).strip()
                if title:
                    titles[num] = title

        if not urls:  # "Chapters: 1 2 3" buttons -> /books-search/<slug>/<N>/
            nav = re.compile(rf"/books-search/{re.escape(slug)}/(\d+)/", re.I)
            for a in soup.find_all("a", href=True):
                m = nav.search(a["href"])
                if m:
                    urls.setdefault(int(m.group(1)), urljoin(url, a["href"]).rstrip("/") + "/")

        if not urls:
            log.info("No chapter links found; using the book page itself as chapter 1.")
            urls[1] = url

        refs = [
            PageRef(n, urls[n], titles.get(n, f"Chapter {n}"), f"Chapter {n}")
            for n in sorted(urls)
        ]
        series = Series(self.series_title, detect_author(url), "Chapter", folder_slug(url))
        return series, refs

    def echoes(self, ref: PageRef, title: str) -> set[str]:
        return super().echoes(ref, title) | {f"Chapter {ref.number}"}
