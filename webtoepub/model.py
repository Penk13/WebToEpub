"""Plain data passed between the scraper, the sources and the EPUB builder."""

from dataclasses import dataclass, field


@dataclass
class Block:
    """One piece of body content. Text is plain (unescaped)."""

    kind: str  # "h" (heading), "p" (paragraph) or "quote" (blockquote)
    text: str
    level: int = 0  # heading level 1-6; 0 for non-headings


@dataclass
class Series:
    """What every EPUB of one run has in common."""

    name: str  # display name and calibre:series
    author: str
    unit: str  # "Message", "Chapter" or "Page" - used in the description
    slug: str  # output folder name


@dataclass
class PageRef:
    """A page discovered on an index page, before it is fetched."""

    number: int
    url: str
    title: str | None = None  # None: take it from the page itself
    kicker: str = ""  # small line shown above the title


@dataclass
class Chapter:
    """A fetched, cleaned page ready to become one EPUB."""

    number: int
    title: str
    blocks: list[Block] = field(default_factory=list)
    kicker: str = ""
