"""Filenames and identifiers."""

import re

MAX_SLUG_LENGTH = 80


def slugify(text: str, max_length: int = MAX_SLUG_LENGTH) -> str:
    """Filesystem-safe slug: "God's Will — Part 1" -> "Gods-Will-Part-1".

    Apostrophes are dropped (not turned into a dash), every other run of
    non-word characters becomes one dash, and long slugs are cut at a dash.
    """
    text = re.sub(r"['’‘`]", "", text)
    text = re.sub(r"[^\w]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"_+", "-", text).strip("-")
    if len(text) > max_length:
        cut = text[:max_length]
        text = cut.rsplit("-", 1)[0] if "-" in cut else cut
    return text or "untitled"


def epub_filename(number: int, title: str) -> str:
    # The NNN- prefix also keeps Windows reserved names (CON, NUL...) safe.
    return f"{number:03d}-{slugify(title)}.epub"
