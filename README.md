# WebToEpub

Scrapes Christian ministry books from [bibleread.online](https://bibleread.online) and converts them into **one EPUB file per message/chapter**, ready for Kindle or any e-reader app.

Every EPUB has the same layout:

- Opens on a **contents page** linking to every heading in the message
- Chapter page: a small kicker line (`Message 6`, `Section Two • Chapter 3`), the title, the series name, then the body text (site navigation, footers and repeated title lines stripped)
- A nested reader TOC (NCX/Nav) built from the page's headings
- Metadata: title `NNN - Title`, author, description, and Calibre series + series index, so Calibre and Kindle sort the files in reading order

## Setup

Requires Python 3.10+ (developed on 3.13).

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

## Usage

```bash
python -m webtoepub <source> <index-url> [options]
```

| Source | Index URL | Author | Output folder |
|---|---|---|---|
| `life-study` | `/life-study-of-the-bible/<series>/` | Witness Lee | `life-study-of-romans/` |
| `book` | any book under `/all-books-by-Watchman-Nee-and-Witness-Lee/` | detected from URL | `abiding-in-the-lord-to-enjoy-his-life/` |
| `cwwn` | a *Collected Works of Watchman Nee* volume | Watchman Nee | `cwwn-set-1-vol-12/` |

```bash
python -m webtoepub life-study https://bibleread.online/life-study-of-the-bible/life-study-of-romans/
python -m webtoepub book https://bibleread.online/all-books-by-Watchman-Nee-and-Witness-Lee/book-abiding-in-the-lord-to-enjoy-his-life-Witness-Lee-read-online/
python -m webtoepub cwwn "https://bibleread.online/all-books-by-Watchman-Nee-and-Witness-Lee/book-collected-works-of-watchman-nee-the-set-1-vol-12-the-spiritual-man-1-Watchman-Nee-read-online/"
```

Options (all sources):

| Option | Meaning |
|---|---|
| `--out DIR` | parent folder for the EPUB folder (default `output/`, git-ignored) |
| `--skip-existing` | skip pages whose `NNN-*.epub` already exists, to resume a run |
| `--delay S` | seconds between requests (default 1.2) |
| `--cache DIR` | keep downloaded HTML and reuse it on later runs (no re-download) |

`cwwn` only:

| Option | Meaning |
|---|---|
| `--titles auto\|index\|page` | where titles come from (default `auto`, see below) |
| `--overrides FILE` | section/chapter corrections, one `<page> <section> <chapter>` per line (`0` clears) |
| `--no-prompt` | do not ask for corrections interactively |

CWWN index pages come in two kinds. In Vol. 12–14 (*The Spiritual Man*) the index links carry each page's title with `section N` / `ch.N` markers; the run prints a table and lets you correct any page's section/chapter before scraping. In Vol. 01–02 they don't, so the title is each page's first descriptive heading and a bare `CHAPTER ONE` heading becomes the kicker. `auto` picks index titles when the index has any `section N` marker.

Files are named `NNN-Title-Slug.epub`: zero-padded number, apostrophes dropped (`Gods-Choice`), other punctuation turned into dashes, at most 80 characters. All-caps titles from the site are converted to title case.

### Behaviour notes

- Requests are throttled (`--delay`) and retried up to 3 times with backoff on connection errors, timeouts and HTTP 429/5xx. A page that still fails gets an EPUB with a placeholder note, and the run summary counts it.
- Scraping depends on bibleread.online's current HTML. If the site changes, the filters in `webtoepub/clean.py` (`FOOTER_SENTINELS`, `NAV_PATTERNS`) or the link patterns in `webtoepub/sources/` may need updating. All filters only apply to short text (≤ 200 characters), so a real paragraph that mentions e.g. "Living Stream Ministry" is never treated as site UI.

## Code layout

```
webtoepub/
  cli.py          command line, run loop, CWWN correction prompt
  fetch.py        HTTP session: retries, delay, optional HTML cache
  clean.py        page -> content blocks: filters, header de-duplication, heading levels
  epub_build.py   one EPUB builder used by every source
  naming.py       filenames
  model.py        Block / PageRef / Chapter / Series
  sources/        index-page parsing per site section: life_study, books, cwwn
tests/            pytest tests on small synthetic HTML
```

Run the tests:

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Generated output (`results/`)

| Folder | Content | Files |
|---|---|---|
| `life-study-of-deuteronomy/` | Life-Study of Deuteronomy | 30 |
| `life-study-of-exodus/` | Life-Study of Exodus | 185 |
| `life-study-of-hebrews/` | Life-Study of Hebrews | 69 |
| `life-study-of-romans/` | Life-Study of Romans | 69 |
| `cwwn-set-1-vol-01/` | CWWN (1.01) - The Christian Life and Warfare | 23 |
| `cwwn-set-1-vol-02/` | CWWN (1.02) - The Word of the Cross | 11 |
| `cwwn-set-1-vol-12/` – `cwwn-set-1-vol-14/` | CWWN (1.12–1.14) - The Spiritual Man (1)–(3) | 15 / 16 / 12 |

## Copyright

The source texts belong to their publisher. Use the generated EPUBs for personal study only, and do not redistribute them.
