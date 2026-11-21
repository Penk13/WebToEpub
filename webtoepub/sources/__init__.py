"""Site sections. Each source parses its index page and finishes each chapter.

A source provides:
  discover(fetcher, url) -> (Series, list[PageRef])
  skip(tag_name, text) -> bool         extra noise filter for page bodies
  finish(ref, blocks) -> Chapter       title, kicker and header de-duplication
"""

import re

from webtoepub.model import Block, Chapter, PageRef
from webtoepub.clean import promote_headings, smart_title, strip_leading_echoes


class Source:
    series_title = ""  # the site's own title for the book/series (an echo to drop)

    def skip(self, tag_name: str, text: str) -> bool:
        return False

    def echoes(self, ref: PageRef, title: str) -> set[str]:
        echoes = {title, self.series_title}
        # Numbered parts: the index says "The Rehearsal of the Law (1)" but the
        # page shows "The Rehearsal of the Law" and then a "(1)" line.
        part = re.search(r"\s*(\(\d+\))$", title)
        if part:
            echoes |= {title[: part.start()], part.group(1)}
        return echoes

    def finish(self, ref: PageRef, blocks: list[Block]) -> Chapter:
        title = ref.title or self.title_from_blocks(blocks) or f"Page {ref.number}"
        title = smart_title(title)
        body, generic = strip_leading_echoes(blocks, self.echoes(ref, title))
        kicker = ref.kicker or (smart_title(generic) if generic else "")
        return Chapter(ref.number, title, promote_headings(body), kicker)

    def title_from_blocks(self, blocks: list[Block]) -> str:
        return ""
