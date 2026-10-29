# WebToEpub

Python scripts that scrape Christian ministry books from [bibleread.online](https://bibleread.online) and convert them into **one EPUB file per message/chapter**, ready for Kindle or any e-reader app.

Each EPUB includes:

- Clean body text (site navigation, footers, and UI noise stripped)
- A table-of-contents page that opens first, linking to every heading in the message
- A nested reader TOC (NCX/Nav) built from the page's `h1`–`h4` headings
- Metadata: title, author, and Calibre series name + series index, so Calibre groups the files as a series in order

## Scripts

| Script | Source on bibleread.online | Author | Output folder |
|---|---|---|---|
| `life-studies.py` | A *Life-Study of the Bible* series index (`/life-study-of-the-bible/<series>/`) | Witness Lee | `./<series-slug>/` |
| `bibleread-books.py` | Any book under `/all-books-by-Watchman-Nee-and-Witness-Lee/` | Detected from URL | `./<book-slug>/` |
| `cwwn_vol_1.py` | *Collected Works of Watchman Nee*, Set 1, Vol. 01 | Watchman Nee | `./ccwn_vol01/` |
| `cwwn_vol_12_14.py` | *Collected Works of Watchman Nee*, Set 1, Vol. 12–14 (*The Spiritual Man*) | Watchman Nee | `./ccwn_vol<NN>/` |

`cwwn_vol_12_14.py` reads section and chapter numbers from the index page and shows them above each title. It prints a table first and then **prompts** you to correct any page's section/chapter (`<page> <section> <chapter>`, `0` clears a value; press Enter on a blank line to continue). Vol. 01's index has no such markers, so `cwwn_vol_1.py` takes titles from each page's first `<h1>` and does not prompt.

## Setup

Requires Python 3.10+ (developed on 3.13).

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux
pip install requests beautifulsoup4 lxml EbookLib
```

> `requirements.txt` holds `pip list` output (a table), not `pip freeze` output, so `pip install -r requirements.txt` will fail. Install the packages above by name, or regenerate the file with `pip freeze > requirements.txt`.

## Usage

Pass the index URL of the series/book. EPUBs are written to a folder in the **current directory**.

```bash
python life-studies.py https://bibleread.online/life-study-of-the-bible/life-study-of-romans/
```

```bash
python bibleread-books.py https://bibleread.online/all-books-by-Watchman-Nee-and-Witness-Lee/book-abiding-in-the-lord-to-enjoy-his-life-Witness-Lee-read-online/
```

```bash
python cwwn_vol_1.py "https://bibleread.online/all-books-by-Watchman-Nee-and-Witness-Lee/book-collected-works-of-watchman-nee-the-set-1-vol-01-the-christian-life-and-warfare-Watchman-Nee-read-online/"
```

```bash
python cwwn_vol_12_14.py "https://bibleread.online/all-books-by-Watchman-Nee-and-Witness-Lee/book-collected-works-of-watchman-nee-the-set-1-vol-12-the-spiritual-man-1-Watchman-Nee-read-online/"
```

Files are named `NNN-Title.epub` (zero-padded message/page number). Run without arguments to print a script's help text.

### Behaviour notes

- Requests are throttled (1.0–1.5 s between pages) to be polite to the site.
- A page that fails to download is not retried; the EPUB is still built with a placeholder note, and the run summary reports how many had no body.
- Scraping depends on bibleread.online's current HTML layout. If the site changes, the noise filters (`_SKIP_TEXT_PATTERNS`, `BOILERPLATE_FRAGMENTS`) or link patterns may need updating.

## How it works

1. **Discover**: fetch the index page and collect message/chapter links and titles.
2. **Scrape**: fetch each page, keep `p` and `h1`–`h4` content, drop navigation and boilerplate, stop at the site footer, and de-duplicate repeated blocks.
3. **Build**: assemble an EPUB with [EbookLib](https://github.com/aerkalov/ebooklib): CSS, a TOC page, a chapter page with heading anchors, and a nested TOC.

## Generated output (`results/`)

Previously generated EPUBs, moved here after each run:

| Folder | Content | Files |
|---|---|---|
| `life-study-of-exodus/` | Life-Study of Exodus | 185 |
| `life-study-of-hebrews/` | Life-Study of Hebrews | 69 |
| `life-study-of-romans/` | Life-Study of Romans | 69 |
| `ccwn_vol01/` | CWWN Vol. 01: *The Christian Life and Warfare* | 23 |
| `ccwn_vol12/` – `ccwn_vol14/` | CWWN Vol. 12–14: *The Spiritual Man* | 15 / 16 / 12 |

## Copyright

The source texts belong to their publisher. Use the generated EPUBs for personal study only, and do not redistribute them.
