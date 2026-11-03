"""Tests for the CLI: exit codes and friendly report formatting."""

from __future__ import annotations

from pathlib import Path

from epub_precheck.cli import format_report, main
from epub_precheck.checks import run_all


def test_exit_code_clean(clean_epub: Path, capsys):
    assert main([str(clean_epub)]) == 0
    out = capsys.readouterr().out
    assert "Looks ship-ready" in out


def test_exit_code_broken(bad_spine_epub: Path, capsys):
    assert main([str(bad_spine_epub)]) == 1
    out = capsys.readouterr().out
    assert "NOT READY" in out
    assert "fix:" in out


def test_file_not_found(tmp_path: Path):
    assert main([str(tmp_path / "nope.epub")]) == 2


def test_report_formatting(broken_image_epub: Path):
    report = run_all(broken_image_epub)
    text = format_report(report)
    assert "[x] (images)" in text
    assert "fix:" in text
    assert "summary:" in text


def test_quiet_drops_info(no_cover_epub: Path):
    report = run_all(no_cover_epub)
    full = format_report(report, quiet=False)
    terse = format_report(report, quiet=True)
    assert terse.count("\n") <= full.count("\n")
