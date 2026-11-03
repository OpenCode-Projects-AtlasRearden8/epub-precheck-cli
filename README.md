# epub-precheck

Before you upload your EPUB, run it through this first.

**epub-precheck** is a friendly, offline pre-checker for EPUB 3 books. It unzip
-reads your file locally (nothing is uploaded anywhere), verifies the packaging
a retail checker will demand, and prints a plain-English, fix-by-fix report.
It fills the gap between a messy draft and the full `kdp-spread-checker` pass.

Built by [Asdale Dynamics, LLC](https://dylanasdale.github.io) — the small company
behind *The Massive AI Manual* — as one of our local-first publishing tools.
Simple enough for a first-time author, strict enough to be worth running.

## What it checks

| Check | Catches |
|-------|---------|
| zip | not a real ZIP, truncated archives, unsafe member paths |
| mimetype | missing/wrong first `mimetype` entry, wrong bytes, unexpected compression |
| container | missing `META-INF/container.xml`, no `rootfile`, OPF path listed but absent |
| opf | package file that won't parse or lacks a `<package>` root |
| manifest | manifest entries that point at files not in the archive; missing id/href |
| spine | spine idrefs with no matching manifest entry, empty spine, missing `<spine>` |
| nav | no EPUB 3 TOC (properties="nav"), nav file missing, TOC links that go nowhere, nav not in spine |
| images | `<img>` / SVG `<image>` / `<link>` references to images that aren't in the EPUB |
| cover | no cover declared at all, or registered cover image missing |
| sizes | any single file over the per-file limit (default 650 MB), plus total unpacked size |

Every finding prints two lines: what's wrong, and how to fix it.

## Install & run

Python 3.10+ on Windows, macOS, or Linux. Standard library only — `pip install`
is not required, though it works if you want it.

```bash
# straight from the source tree
python3 -m epub_precheck path/to/book.epub

# or install it into your environment
pip install .
epub-precheck path/to/book.epub
```

### Options

```text
epub --max-size 100      # tighten the per-file limit to 100 MB
epub -q                  # terse mode: hide INFO lines
epub --version
```

Exit codes: `0` = ship-ready, `1` = blocking issues found, `2` = file not found.
Handy in scripts or a pre-upload checklist.

### Example output

```
epub-precheck · my-book.epub
NOT READY — 2 blocking issue(s) to fix

[x] (images) 'chapter-02.xhtml' references image 'old-cover.jpg', which is not in the EPUB.
    fix: Add 'EPUB/images/old-cover.jpg' to the archive or fix the reference in 'chapter-02.xhtml'.
[x] (cover) No cover detected: no properties="cover-image", no meta[name=cover], and no cover-named image.
    fix: Add a cover image, mark it as the cover in your writing tool, and re-export.
[ ] (sizes) Archive looks healthy: 2.1 MB unpacked across 31 files.

summary: 31 files · 18 spine docs · 17 TOC entries · 2.1 MB unpacked
```

## How it works

Pure Python, zero dependencies: it uses only the standard library
(`zipfile` + `xml.etree`), so it runs identically on Windows, macOS, and
Linux with Python 3.10+. Nothing is extracted to disk — members are read
in memory, and paths are sanitized before anything is opened.

## Privacy

**Everything stays on your machine.** The tool never opens a network
connection — no uploads, no telemetry, no phone-home. Books contain personal
work; epub-precheck treats yours accordingly.

## Running the tests

```bash
python3 -m pytest            # 34 tests; one fixture EPUB per check
python3 -m pytest -v         # see each check named
```

Every check ships with a deliberately broken fixture EPUB (built
programmatically in `tests/conftest.py` — no binary blobs in the repo) plus a
clean control EPUB that must always pass.

## Credits

Created by **Asdale Dynamics, LLC** — Dylan Asdale's LLC for beginner-friendly
AI education, author tools, and practical local-first utilities that the LLC
publishes and sells. See the hub site at dylanasdale.github.io and the book
*The Massive AI Manual* for more plain-English guides.

Licensed under the [MIT License](LICENSE) —
"Copyright (c) 2026 Asdale Dynamics, LLC" applies to all source and docs.
