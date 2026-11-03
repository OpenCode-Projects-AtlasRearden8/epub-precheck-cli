"""Unit tests for each epub-precheck check.

Every fixture is a real EPUB built in conftest.py, one per check,
plus a clean control EPUB that must always pass.
"""

from __future__ import annotations

from pathlib import Path

from epub_precheck.checks import (_human, _resolve, _resolve_dir,
                                  DEFAULT_MAX_FILE_BYTES, run_all)


def run(path: Path, max_bytes: int = DEFAULT_MAX_FILE_BYTES):
    return run_all(path, max_bytes=max_bytes)


def check_msgs(report, check: str):
    return [f for f in report.by_check if f.check == check] if hasattr(report, "by_check") else [
        f for f in report.findings if f.check == check
    ]


def has_error(report, check: str, contains: str | None = None) -> bool:
    for f in report.errors():
        if f.check == check and (contains is None or contains in f.message):
            return True
    return False


def has_warning(report, check: str, contains: str | None = None) -> bool:
    for f in report.warnings():
        if f.check == check and (contains is None or contains in f.message):
            return True
    return False


class TestCleanEPUB:
    """The control: a well-formed fixture must produce zero errors."""

    def test_clean_epub_passes(self, clean_epub: Path):
        report = run(clean_epub)
        assert report.errors() == [], [f.message for f in report.errors()]

    def test_clean_epub_stats(self, clean_epub: Path):
        report = run(clean_epub)
        assert report.stats["spine_docs"] == 3  # 2 chapters + nav
        assert report.stats["nav_entries"] >= 1


class TestZipCheck:
    def test_not_a_zip(self, bad_zip_epub: Path):
        report = run(bad_zip_epub)
        assert not report.passed
        assert has_error(report, "zip")

    def test_truncated_zip(self, truncated_epub: Path):
        report = run(truncated_epub)
        assert not report.passed
        assert has_error(report, "zip")
        assert "member_count" not in report.stats


class TestMimetypeCheck:
    def test_wrong_mimetype_content(self, bad_mimetype_epub: Path):
        report = run(bad_mimetype_epub)
        assert has_error(report, "mimetype")
        flagged = [f for f in report.errors() if f.check == "mimetype"]
        assert any("mimetype" in f.message for f in flagged)

    def test_mimetype_not_first_entry(self, mimetype_not_first_epub: Path):
        report = run(mimetype_not_first_epub)
        assert has_error(report, "mimetype")


class TestContainerCheck:
    def test_missing_container(self, missing_container_epub: Path):
        report = run(missing_container_epub)
        assert has_error(report, "container", "missing")

    def test_container_without_rootfile(self, container_no_rootfile_epub: Path):
        report = run(container_no_rootfile_epub)
        assert has_error(report, "container")

    def test_opf_file_not_in_zip(self, missing_opf_epub: Path):
        report = run(missing_opf_epub)
        assert has_error(report, "container")


class TestOPFCheck:
    def test_malformed_opf(self, malformed_opf_epub: Path):
        report = run(malformed_opf_epub)
        assert has_error(report, "opf")
        assert "XML" in [f.message for f in report.errors() if f.check == "opf"][0] or \
            any("not valid XML" in f.message for f in report.errors() if f.check == "opf")


class TestSpineCheck:
    def test_spine_refs_missing_manifest_id(self, bad_spine_epub: Path):
        report = run(bad_spine_epub)
        assert has_error(report, "spine", "ghost-chapter")

    def test_manifest_lists_removed_file(self, missing_chapter_epub: Path):
        report = run(missing_chapter_epub)
        assert has_error(report, "manifest", "isn't in the EPUB")
        # spine still references the missing doc, so error surfaced either way

    def test_spine_count_on_clean(self, clean_epub: Path):
        report = run(clean_epub)
        assert "spine_docs" in report.stats


class TestNavCheck:
    def test_no_nav_item(self, no_nav_epub: Path):
        report = run(no_nav_epub)
        assert has_warning(report, "nav", "properties")

    def test_nav_file_removed(self, nav_missing_file_epub: Path):
        report = run(nav_missing_file_epub)
        assert has_error(report, "nav", "missing from the archive")

    def test_nav_link_to_missing_file(self, nav_broken_link_epub: Path):
        report = run(nav_broken_link_epub)
        assert has_error(report, "nav", "link")
        texts = [f.message for f in report.errors() if f.check == "nav"]
        assert any("chapter-2.xhtml" in t for t in texts)


class TestImagesCheck:
    def test_broken_image_reference(self, broken_image_epub: Path):
        report = run(broken_image_epub)
        assert has_error(report, "images", "not in the EPUB")
        matched = [f for f in report.errors() if f.check == "images"]
        assert any("deleted-image.jpg" in f.message for f in matched)

    def test_clean_epub_image_refs_ok(self, clean_epub: Path):
        report = run(clean_epub)
        assert not [f for f in report.errors() if f.check == "images"]


class TestCoverCheck:
    def test_no_cover(self, no_cover_epub: Path):
        report = run(no_cover_epub)
        assert has_warning(report, "cover")

    def test_missing_cover_file(self, missing_cover_file_epub: Path):
        report = run(missing_cover_file_epub)
        assert has_error(report, "cover", "missing from the archive")

    def test_clean_has_cover(self, clean_epub: Path):
        report = run(clean_epub)
        assert not [f for f in report.warnings() if f.check == "cover"]


class TestSizesCheck:
    def test_oversized_member(self, oversized_epub: Path):
        report = run(oversized_epub, max_bytes=1024 * 1024)
        assert has_error(report, "sizes", "over the")
        big = [f for f in report.errors() if f.check == "sizes"]
        assert any("huge.png" in f.message for f in big)

    def test_custom_limit_default_650mb(self, oversized_epub: Path):
        # with the default 650 MB limit the tiny fixture is fine
        report = run(oversized_epub)
        assert not [f for f in report.errors() if f.check == "sizes"]


class TestEveryFixHasText:
    def test_all_findings_have_fixes(self, broken_image_epub: Path, no_cover_epub: Path):
        for report in (run(broken_image_epub), run(no_cover_epub)):
            for f in report.findings:
                assert f.fix, f"finding missing fix: {f.message}"
                assert f.message


class TestHelpers:
    def test_resolve(self):
        assert _resolve("OEBPS", "nav.xhtml") == "OEBPS/nav.xhtml"
        assert _resolve("OEBPS", "/x/y") == "x/y"
        assert _resolve("", "a/b") == "a/b"

    def test_resolve_dir(self):
        assert _resolve_dir("OEBPS/nav.xhtml", "ch1.xhtml") == "OEBPS/ch1.xhtml"
        assert _resolve_dir("OEBPS/ch1.xhtml", "../images/a.jpg") == "images/a.jpg"

    def test_human(self):
        assert _human(500) == "500 bytes"
        assert _human(2048) == "2.0 KB"
        assert _human(1500 * 1024) == "1.5 MB"


class TestMultipleDefects:
    def test_multi_defect_reports_all_checks(self, multi_defect_epub: Path):
        report = run(multi_defect_epub)
        checks_seen = {f.check for f in report.errors()}
        assert {"mimetype", "manifest", "cover"} <= checks_seen

    def test_one_fixture_can_surface_several_checks(self, nav_broken_link_epub: Path):
        report = run(nav_broken_link_epub)
        checks_seen = {f.check for f in report.errors()}
        assert "nav" in checks_seen
        assert "manifest" in checks_seen  # removed chapter-2 file is also listed in the manifest

    def test_missing_cover_file_still_flags_manifest(self, missing_cover_file_epub: Path):
        report = run(missing_cover_file_epub)
        checks_seen = {f.check for f in report.errors()}
        assert "cover" in checks_seen
        assert "manifest" in checks_seen
