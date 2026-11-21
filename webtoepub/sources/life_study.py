"""Life-Study of the Bible: /life-study-of-the-bible/<series>/ (author Witness Lee)."""

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from webtoepub.fetch import Fetcher
from webtoepub.model import PageRef, Series
from webtoepub.sources import Source

log = logging.getLogger(__name__)

_MSG_LABEL = re.compile(r"\b(?:msg\.|message)\s*(\d+)", re.I)


def _slug(url: str) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[-1] if parts else "life-study"


def _series_title(soup: BeautifulSoup, url: str) -> str:
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    if soup.title:
        parts = soup.title.get_text().split("|")
        if len(parts) >= 2:
            return parts[-1].strip()
    return _slug(url).replace("-", " ").title()


def _titles(soup: BeautifulSoup) -> dict[int, str]:
    """Message titles from index links: "msg. N" (Genesis) or "Message N" (Exodus)."""
    titles: dict[int, str] = {}
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        m = _MSG_LABEL.search(text)
        if not m:
            continue
        num = int(m.group(1))
        bold = a.find(["b", "strong"])
        title = bold.get_text(strip=True) if bold else _MSG_LABEL.sub("", text).strip(" :-")
        if title and num not in titles:
            titles[num] = title
    return titles


class LifeStudy(Source):
    def discover(self, fetcher: Fetcher, url: str) -> tuple[Series, list[PageRef]]:
        soup = fetcher.soup(url)
        if soup is None:
            raise SystemExit(f"Cannot fetch the index page: {url}")
        self.series_title = _series_title(soup, url)

        slug = _slug(url)
        link = re.compile(rf"/{re.escape(slug)}/(\d+)/?$")
        urls: dict[int, str] = {}
        for a in soup.find_all("a", href=True):
            m = link.search(a["href"])
            if m:
                urls.setdefault(int(m.group(1)), urljoin(url, a["href"]))
        if not urls:
            raise SystemExit("No message links found. The page structure may have changed.")

        titles = _titles(soup)
        refs = [
            PageRef(n, urls[n], titles.get(n, f"Message {n}"), f"Message {n}")
            for n in sorted(urls)
        ]
        series = Series(self.series_title, "Witness Lee", "Message", slug)
        return series, refs

    def skip(self, tag_name: str, text: str) -> bool:
        # Some pages repeat the whole outline in one long block that starts
        # with "Message N".
        return len(text) > 500 and bool(re.match(r"^Message\s+\d+\b", text))

    def echoes(self, ref: PageRef, title: str) -> set[str]:
        return super().echoes(ref, title) | {f"Message {ref.number}"}
