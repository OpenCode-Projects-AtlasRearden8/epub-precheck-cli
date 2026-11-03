# STATUS.md — epub-precheck

Built 2026-11-03 by Asdale Dynamics, LLC.
Version 1.0.0. Working directory: `epub-precheck-cli`.

## What was built

`epub-precheck` is a stdlib-only Python CLI that pre-checks an EPUB 3 file
before you upload it to a retailer (KDP, Draft2Digital, etc.). It reads the
archive entirely in memory — nothing is extracted to disk — and prints a
friendly, fix-by-fix report where every finding has a one-line explanation
and a one-line fix.

Checks implemented (each in `epub_precheck/checks.py`):

- zip — real ZIP, fully readable, safe member paths (no `../`, no absolute)
- mimetype — first entry is `mimetype`, holds `application/epub+zip`, stored not deflated
- container — `META-INF/container.xml` present, parses, `rootfile full-path` present
- opf — referenced package file exists, parses, has `<package>` root
- manifest — every item has id/href and every href resolves to a real member
- spine — every idref maps to a manifest id; empty spine flagged
- nav — EPUB 3 TOC (properties="nav") declared, file present, linked targets exist, warned if nav not in spine
- images — `<img>`, SVG `<image>`, and `<link>` references in XHTML checked against the archive
- cover — detected via properties="cover-image", meta[name=cover], or cover-named item; missing cover image is an ERROR
- sizes — any member over the per-file limit (default 650 MB) is an ERROR; overall unpacked size INFO/WARN

CLI (`epub_precheck/cli.py`, also `python -m epub_precheck` and the installed
`epub-precheck` entry point): flags `--max-size MB`, `-q/--quiet`, `--version`.
Exit codes: 0 ship-ready, 1 blocking issues, 2 file not found. Output uses
color on a terminal and plain text when piped (and stays plain on Windows).

## How to run it

```bash
python3 -m epub_precheck path/to/book.epub        # from the repo, no install needed
python3 -m epub_precheck -q book.epub             # terse mode
python3 -m epub_precheck --max-size 50 book.epub  # custom per-file limit

pip install -e .            # optional
epub-precheck book.epub     # installed entry point
```

Requires Python 3.10+. Works on Windows/macOS/Linux (stdlib `zipfile` +
`xml.etree` only). Fully offline — the tool never opens a network connection.

## Verification results

- `python3 -m pytest` — **35 passed, 0 failed** (`tests/conftest.py` builds a
  fixture EPUB programmatically for every check, plus a clean control EPUB);
- `python3 -m pyflakes epub_precheck tests` — clean, no issues;
- `pip install -e .` succeeds; entry point `epub-precheck --version` prints
  `epub-precheck 1.0.0`;
- Manual CLI smoke tests:
  - clean built EPUB → `exit 0`, "Looks ship-ready", stats line shown;
  - EPUB with corrupted mimetype + removed cover file → `exit 1`,
    "NOT READY — 3 blocking issue(s)", each with a `fix:` line (mimetype,
    manifest, cover all surfaced);
  - `--max-size 0.0005` correctly flags a 961-byte OPF with the custom limit;
  - grep of the source tree: no secrets, keys, or personal data (only fake
    fixture bytes like `FAKE-JPEG-BYTES`).

## Repository layout

```
epub_precheck/__init__.py    version + package docstring
epub_precheck/checks.py      all inspection logic + Report/Finding model
epub_precheck/cli.py         argparse CLI + report formatting
epub_precheck/__main__.py    python -m entry
tests/conftest.py            EPUBBuilder factory + 15 defect fixtures
tests/test_checks.py         one test group per check
tests/test_cli.py            exit codes + formatting tests
```

## Known gaps

- EPUB 2 (no EPUB 3 nav) is supported only down to the OPF level; old fallback
  NCX TOCs are not yet validated.
- Media-type validation (declared vs actual file sniffing) is not done — only
  existence and reference resolution.
- Internal anchors (`chapter.xhtml#sec-3`) resolve by file only, not to the
  anchor id; broken fragment targets aren't detected.
- Font/audio/video reference resolution inside CSS files is not checked.
- The corrupted-`mimetype` fixture halts at the mimetype error by design but
  the remaining checks do continue and surface; deeper recovery (finding the
  OPF even without a valid container.xml) is not attempted.
- Fixture EPUBs are built in tests, so no pre-made `.epub` demo ships in the
  repo (intentional — keeps the repo text-only; prepare one locally with the
  `tests/conftest.py` factory if useful).
