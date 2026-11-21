"""Command line: python -m webtoepub <life-study|book|cwwn> URL [options]."""

import argparse
import logging
import sys
from pathlib import Path

from webtoepub.clean import extract_blocks
from webtoepub.epub_build import build_epub
from webtoepub.fetch import DEFAULT_DELAY, Fetcher
from webtoepub.naming import epub_filename
from webtoepub.sources import Source
from webtoepub.sources.books import Book
from webtoepub.sources.cwwn import Cwwn, kicker
from webtoepub.sources.life_study import LifeStudy

log = logging.getLogger("webtoepub")

EXAMPLES = """\
examples:
  python -m webtoepub life-study https://bibleread.online/life-study-of-the-bible/life-study-of-romans/
  python -m webtoepub book https://bibleread.online/all-books-by-Watchman-Nee-and-Witness-Lee/book-abiding-in-the-lord-to-enjoy-his-life-Witness-Lee-read-online/
  python -m webtoepub cwwn "https://bibleread.online/all-books-by-Watchman-Nee-and-Witness-Lee/book-collected-works-of-watchman-nee-the-set-1-vol-12-the-spiritual-man-1-Watchman-Nee-read-online/"
"""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("url", help="index page of the series or book")
    common.add_argument("--out", type=Path, default=Path("output"),
                        help="parent folder for the EPUB folder (default: output)")
    common.add_argument("--skip-existing", action="store_true",
                        help="skip pages whose NNN-*.epub already exists (resume a run)")
    common.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"seconds between requests (default: {DEFAULT_DELAY})")
    common.add_argument("--cache", type=Path,
                        help="keep downloaded HTML in this folder and reuse it")

    p = argparse.ArgumentParser(
        prog="python -m webtoepub",
        description="Convert a bibleread.online series or book into one EPUB per message/chapter.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="source", required=True)
    sub.add_parser("life-study", parents=[common], help="Life-Study of the Bible series")
    sub.add_parser("book", parents=[common], help="any book under /all-books-by-Watchman-Nee-and-Witness-Lee/")
    cw = sub.add_parser("cwwn", parents=[common], help="Collected Works of Watchman Nee volume")
    cw.add_argument("--titles", choices=["auto", "index", "page"], default="auto",
                    help="take titles from the index page or each page (default: auto)")
    cw.add_argument("--overrides", type=Path,
                    help='file of "<page> <section> <chapter>" lines (0 clears a value)')
    cw.add_argument("--no-prompt", action="store_true",
                    help="do not ask for section/chapter corrections")
    return p.parse_args(argv)


def _set_page(info: dict[int, dict], line: str) -> str | None:
    """Apply one "<page> <section> <chapter>" correction. Returns an error or None."""
    parts = line.split()
    if len(parts) != 3:
        return "expected three numbers: page section chapter"
    try:
        page, sec, ch = (int(x) for x in parts)
    except ValueError:
        return "all three values must be integers"
    if page not in info:
        return f"page {page} not found (1-{len(info)})"
    info[page]["section"] = sec or None
    info[page]["chapter"] = ch or None
    return None


def review_cwwn(source: Cwwn, args: argparse.Namespace) -> None:
    info = source.page_info
    print(f"\n  {'Page':>4}  {'Sec':>4}  {'Ch':>4}  Title")
    print(f"  {'-' * 60}")
    for n in sorted(info):
        i = info[n]
        print(f"  {n:>4}  {i['section'] or '-':>4}  {i['chapter'] or '-':>4}  {i['title']}")

    if args.overrides:
        for line in args.overrides.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                if err := _set_page(info, line):
                    raise SystemExit(f"{args.overrides}: {line!r}: {err}")

    if args.no_prompt or not sys.stdin.isatty():
        return
    print('\nCorrect any page as "<page> <section> <chapter>" (0 clears). Blank line to continue.')
    while line := input("  Override: ").strip():
        if err := _set_page(info, line):
            print(f"  {err}")
        else:
            n = int(line.split()[0])
            print(f"  Page {n}: {kicker(info[n]['section'], info[n]['chapter']) or '-'}")


def run(source: Source, args: argparse.Namespace) -> int:
    fetcher = Fetcher(delay=args.delay, cache_dir=args.cache)
    series, refs = source.discover(fetcher, args.url.rstrip("/") + "/")
    log.info("Series: %s  |  Author: %s  |  %d pages", series.name, series.author, len(refs))

    if isinstance(source, Cwwn) and source.use_index_titles:
        review_cwwn(source, args)
        source.apply_page_info(refs)

    out_dir = args.out / series.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    built = empty = skipped = failed = 0

    for i, ref in enumerate(refs, 1):
        if args.skip_existing and any(out_dir.glob(f"{ref.number:03d}-*.epub")):
            skipped += 1
            continue
        soup = fetcher.soup(ref.url)
        blocks = extract_blocks(soup, source.skip) if soup is not None else []
        chapter = source.finish(ref, blocks)
        if not chapter.blocks:
            empty += 1
            log.warning("[%d/%d] %03d has no body content", i, len(refs), ref.number)
        path = out_dir / epub_filename(ref.number, chapter.title)
        try:
            build_epub(series, chapter, path)
        except Exception as exc:  # keep going; one bad page should not stop the run
            failed += 1
            log.error("[%d/%d] %03d EPUB build failed: %s", i, len(refs), ref.number, exc)
            continue
        built += 1
        log.info("[%d/%d] %s", i, len(refs), path.name)

    log.info("Done: %d built, %d skipped, %d failed, %d without body -> %s",
             built, skipped, failed, empty, out_dir)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
                        datefmt="%H:%M:%S")
    args = parse_args(argv)
    source: Source
    if args.source == "life-study":
        source = LifeStudy()
    elif args.source == "book":
        source = Book()
    else:
        source = Cwwn(args.titles)
    return run(source, args)
