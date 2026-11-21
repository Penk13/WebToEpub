"""HTTP fetching: one session with retries, a polite delay and an optional disk cache."""

import hashlib
import logging
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# The site can stall on the read phase, so the read timeout is generous.
DEFAULT_TIMEOUT = (30, 90)
DEFAULT_DELAY = 1.2


class Fetcher:
    """Fetch pages as BeautifulSoup. Failures are logged and return None."""

    def __init__(
        self,
        delay: float = DEFAULT_DELAY,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        cache_dir: Path | None = None,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0

        retry = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".html")

    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def get_bytes(self, url: str) -> bytes | None:
        cached = self._cache_path(url)
        if cached and cached.exists():
            return cached.read_bytes()
        self._throttle()
        try:
            r = self.session.get(url, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Failed to fetch %s: %s", url, exc)
            return None
        if cached:
            cached.write_bytes(r.content)
        return r.content

    def soup(self, url: str) -> BeautifulSoup | None:
        data = self.get_bytes(url)
        if data is None:
            return None
        # Raw bytes, so BeautifulSoup reads the page's declared encoding.
        # requests' r.text guesses latin-1 without a charset header (God�s).
        return BeautifulSoup(data, "lxml")
