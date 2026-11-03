"""Command-line interface for epub-precheck."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .checks import DEFAULT_MAX_FILE_BYTES, Report, run_all

_BULLET = {"ERROR": "[x]", "WARN": "[!]", "INFO": "[ ]"}

_COLORS = {
    "ERROR": "\033[1;31m",
    "WARN": "\033[1;33m",
    "INFO": "\033[36m",
    "OK": "\033[1;32m",
    "RESET": "\033[0m",
}


def _use_color() -> bool:
    if not sys.stdout.isatty() or sys.platform == "win32":
        return False
    return (sys.stdout.encoding or "").lower() not in ("utf-32", "bytestring")


def _c(text: str, key: str) -> str:
    if not _use_color():
        return text
    return f"{_COLORS.get(key, '')}{text}{_COLORS['RESET']}"


def format_report(report: Report, quiet: bool = False) -> str:
    """Human-friendly, fix-by-fix report."""
    lines: list[str] = []
    errors = report.errors()
    warnings = report.warnings()
    infos = report.infos()
    blocking = [f for f in errors]

    lines.append(_c(f"epub-precheck · {report.path.name}", "OK"))
    if blocking:
        verdict = f"NOT READY — {len(blocking)} blocking issue(s) to fix"
        lines.append(_c(verdict, "ERROR"))
    elif warnings:
        verdict = f"Likely ready — {len(warnings)} warning(s), nothing blocking"
        lines.append(_c(verdict, "WARN"))
    else:
        verdict = "Looks ship-ready — no issues found"
        lines.append(_c(verdict, "OK"))
    lines.append("")

    for level, items in (("ERROR", errors), ("WARN", warnings)):
        if quiet and level == "ERROR" and items:
            continue
        for f in items[:]:
            icon = _BULLET[f.level]
            bare = f"{icon} ({f.check}) {f.message}"
            colored = _c(bare, f.level)
            lines.append(colored)
            lines.append(f"    fix: {f.fix}")
    if not quiet:
        for f in infos:
            lines.append(f"{_BULLET['INFO']} ({f.check}) {f.message}")
    lines.append("")

    stats = []
    if "member_count" in report.stats:
        stats.append(f"{report.stats['member_count']} files")
    if "spine_docs" in report.stats:
        stats.append(f"{report.stats['spine_docs']} spine docs")
    if "nav_entries" in report.stats:
        stats.append(f"{report.stats['nav_entries']} TOC entries")
    if "total_uncompressed_bytes" in report.stats:
        n = report.stats["total_uncompressed_bytes"]
        stat_line = f"{n / 1024 / 1024:.1f} MB unpacked"
        stats.append(stat_line)
    if stats:
        lines.append("summary: " + " · ".join(stats))
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epub-precheck",
        description=(
            "Offline pre-check for EPUB files: catches bad mimetype, broken "
            "spine/nav, dead image references, missing covers, oversized files, "
            "and prints a friendly fix-by-fix report. stdlib only."
        ),
    )
    parser.add_argument("epub", type=Path, help="path to the .epub file to check")
    parser.add_argument(
        "--max-size",
        type=float,
        default=None,
        metavar="MB",
        help=f"per-file size limit in MB (default: {DEFAULT_MAX_FILE_BYTES // 1024 // 1024})",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress INFO lines for a terse verdict")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    path: Path = args.epub
    if not path.exists():
        print(f"epub-precheck: error: file not found: {path}", file=sys.stderr)
        return 2
    if not path.is_file():
        print(f"epub-precheck: error: not a file: {path}", file=sys.stderr)
        return 2
    max_bytes = int(args.max_size * 1024 * 1024) if args.max_size else DEFAULT_MAX_FILE_BYTES
    report = run_all(path, max_bytes=max_bytes)
    print(format_report(report, quiet=args.quiet))
    return 1 if not report.passed else 0


if __name__ == "__main__":
    raise SystemExit(main())
