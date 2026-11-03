"""Shared pytest fixtures: a programmatic EPUB factory.

Each test gets a real EPUB (built on the fly, never extracted to disk)
with a controlled defect, so every check has a fixture exercising it.
"""

from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path

import pytest

OPF_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:1234-5678</dc:identifier>
    <dc:title>Precheck Fixture Book</dc:title>
    <dc:language>en</dc:language>
{meta_cover_line}  </metadata>
  <manifest>
{manifest_items}  </manifest>
  <spine>
{spine_items}  </spine>
</package>
"""

CONTAINER_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:specification:container:rootfile">
  <rootfiles>
    <rootfile full-path="{opf_path}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

PAGE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>{title}</title></head>
  <body><h1>{title}</h1>{body}</body>
</html>
"""

NAV_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>TOC</title></head>
  <body>
    <nav epub:type="toc" id="toc">
      <ol>
{nav_entries}      </ol>
    </nav>
  </body>
</html>
"""


def _page(title: str, body: str = "") -> str:
    return PAGE_TEMPLATE.format(title=title, body=body)


class EPUBBuilder:
    """Collects zip members (in order) and writes a real EPUB archive."""

    def __init__(self):
        self.entries: list[list] = []  # mutable [name, data, compress_type]

    def add(self, name: str, data: bytes | str, *, compress_type: int | None = None) -> None:
        """Add an entry, or overwrite its data if the name already exists."""
        self.replace(name, data, compress_type=compress_type)

    def replace(self, name: str, data: bytes | str, *, compress_type: int | None = None) -> None:
        """Replace an existing entry's data (or add it if absent) in place."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        for entry in self.entries:
            if entry[0] == name:
                entry[1] = data
                if compress_type is not None:
                    entry[2] = compress_type
                return
        if compress_type is None:
            compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
        self.entries.append([name, data, compress_type])

    def remove(self, name: str) -> None:
        self.entries = [entry for entry in self.entries if entry[0] != name]

    def corrupt_mimetype(self, text: str = "text/plain", deflate: bool = True) -> None:
        for entry in self.entries:
            if entry[0] == "mimetype":
                entry[1] = text.encode("utf-8")
                if deflate:
                    entry[2] = zipfile.ZIP_DEFLATED

    def demote_mimetype_order(self) -> None:
        """Move 'mimetype' off position 0 (insert after the first member)."""
        mt = next((e for e in self.entries if e[0] == "mimetype"), None)
        if mt is None or mt is self.entries[0]:
            self.remove("mimetype")
            mt = ["mimetype", b"application/epub+zip", zipfile.ZIP_STORED]
        self.entries = [e for e in self.entries if e[0] != "mimetype"]
        self.entries.insert(1, mt)

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            for name, data, ctype in self.entries:
                zf.writestr(zipfile.ZipInfo(name), bytes(data), compress_type=ctype)
        return path


def build_epub(
    *,
    chapters: list[str] | None = None,
    nav: bool = True,
    nav_in_spine: bool = True,
    cover_jpg: bool = True,
    meta_cover: bool = True,
    opf_dir: str = "OEBPS",
    opf_name: str = "content.opf",
) -> tuple[EPUBBuilder, dict[str, str]]:
    """Build a minimal valid EPUB 3. Returns (builder, path map)."""
    if chapters is None:
        chapters = ["chapter-1", "chapter-2"]
    b = EPUBBuilder()

    opf_path = posixpath.join(opf_dir, opf_name) if opf_dir else opf_name
    base = posixpath.dirname(opf_path)
    b.add("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

    manifest_items: list[str] = []
    spine_items: list[str] = []
    paths: dict[str, str | None] = {"opf": opf_path}

    chapters_img_data = {}
    if cover_jpg:
        manifest_items.append('<item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>')
        paths["cover-image"] = posixpath.normpath(posixpath.join(base, "images/cover.jpg"))
        b.add(paths["cover-image"], b"FAKE-JPEG-BYTES")

    manifest_items.append('<item id="css" href="styles.css" media-type="text/css"/>')
    b.add(posixpath.normpath(posixpath.join(base, "styles.css")), "body { color: #222; }")

    for idx, chapter in enumerate(chapters):
        iid = f"ch{idx + 1}"
        href = f"{chapter}.xhtml"
        resolved = posixpath.normpath(posixpath.join(base, href))
        paths[iid] = resolved
        manifest_items.append(f'<item id="{iid}" href="{href}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'<itemref idref="{iid}"/>')
        chapters_img_data[iid] = b"\x89PNG-fake-bytes"
        image_name = posixpath.normpath(posixpath.join(base, f"images/{chapter}.jpg"))
        b.add(image_name, chapters_img_data[iid])
        page = _page(chapter, f'<p>Text of {chapter}.</p><img src="images/{chapter}.jpg" alt="{chapter}"/>')
        b.add(resolved, page)

    if nav:
        nav_href = "nav.xhtml"
        nav_name = posixpath.normpath(posixpath.join(base, nav_href))
        nav_local = posixpath.dirname(nav_name)
        links = "".join(
            f"\n        <li><a href=\"{posixpath.relpath(paths[f'ch{i + 1}'], start=nav_local or '.')}\">{c}</a></li>"
            for i, c in enumerate(chapters)
        )
        manifest_items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        b.add(nav_name, NAV_TEMPLATE.format(nav_entries=links))
        paths["nav"] = nav_name
        if nav_in_spine:
            spine_items.append('<itemref idref="nav" linear="no"/>')

    meta_cover_line = '<meta name="cover" content="cover-image"/>\n    ' if meta_cover else ""
    opf_text = OPF_TEMPLATE.format(
        meta_cover_line=meta_cover_line,
        manifest_items="\n    " + "\n    ".join(manifest_items) + "\n  ",
        spine_items="\n    " + "\n    ".join(spine_items) + "\n  ",
    )
    b.add(opf_path, opf_text)
    b.add("META-INF/container.xml", CONTAINER_TEMPLATE.format(opf_path=opf_path))
    return b, paths


# --------------------------------------------------------------------------
# Fixtures: a clean EPUB + one deliberately defective EPUB per check.
# --------------------------------------------------------------------------

ALL_E2E_FIXTURES = []


def _fixture(path_name: str):
    def decorator(func):
        ALL_E2E_FIXTURES.append(path_name)
        return pytest.fixture(name=path_name)(func)

    return decorator


@pytest.fixture
def epub_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def clean_epub(epub_dir: Path) -> Path:
    """A fully valid EPUB: every check should pass."""
    b, _ = build_epub()
    return b.write(epub_dir / "clean.epub")


@pytest.fixture
def bad_zip_epub(epub_dir: Path) -> Path:
    """zip check: not a zip at all."""
    p = epub_dir / "not-a-zip.epub"
    p.write_bytes(b"this is definitely not a zip archive, just text bytes")
    return p


@pytest.fixture
def truncated_epub(clean_epub: Path) -> Path:
    """zip check: the archive is cut off mid-file (bad central directory)."""
    data = clean_epub.read_bytes()
    p = clean_epub.parent / "truncated.epub"
    p.write_bytes(data[: len(data) // 2])
    return p


@pytest.fixture
def unsafe_path_epub(epub_dir: Path) -> Path:
    """zip check: a member with a '../' path."""
    b, _ = build_epub()
    b.entries = [e for e in b.entries if e[0] == "mimetype"]
    b.add("OEBPS/../evil.txt", "boom", compress_type=zipfile.ZIP_DEFLATED)
    b.add("META-INF/container.xml", CONTAINER_TEMPLATE.format(opf_path="OEBPS/content.opf"),
          compress_type=zipfile.ZIP_DEFLATED)
    b.add("OEBPS/content.opf",
          OPF_TEMPLATE.format(meta_cover_line="", manifest_items="", spine_items=""),
          compress_type=zipfile.ZIP_DEFLATED)
    return b.write(epub_dir / "unsafe-path.epub")


@pytest.fixture
def bad_mimetype_epub(epub_dir: Path) -> Path:
    """mimetype check: wrong content, compressed."""
    b, _ = build_epub()
    b.corrupt_mimetype("text/plain", deflate=True)
    return b.write(epub_dir / "bad-mimetype.epub")


@pytest.fixture
def mimetype_not_first_epub(epub_dir: Path) -> Path:
    """mimetype check: correct mimetype but inserted as entry #2."""
    b, _ = build_epub()
    b.demote_mimetype_order()
    return b.write(epub_dir / "mimetype-not-first.epub")


@pytest.fixture
def missing_container_epub(epub_dir: Path) -> Path:
    """container check: no META-INF/container.xml."""
    b, _ = build_epub()
    b.remove("META-INF/container.xml")
    return b.write(epub_dir / "no-container.epub")


@pytest.fixture
def container_no_rootfile_epub(epub_dir: Path) -> Path:
    """container check: container.xml has no rootfile full-path."""
    b, _ = build_epub()
    b.replace(
        "META-INF/container.xml",
        '<?xml version="1.0" encoding="UTF-8"?>\n<container version="1.0" xmlns="urn:oasis:names:specification:container:rootfile"><rootfiles></rootfiles></container>',
    )
    return b.write(epub_dir / "container-no-rootfile.epub")


@pytest.fixture
def missing_opf_epub(epub_dir: Path) -> Path:
    """container check: rootfile points at an OPF not present in the zip."""
    b, _ = build_epub()
    b.remove("OEBPS/content.opf")
    return b.write(epub_dir / "no-opf.epub")


@pytest.fixture
def malformed_opf_epub(epub_dir: Path) -> Path:
    """opf check: OPF is broken XML."""
    b, _ = build_epub()
    b.replace("OEBPS/content.opf", "<package><manifest>")
    return b.write(epub_dir / "malformed-opf.epub")


@pytest.fixture
def missing_chapter_epub(epub_dir: Path) -> Path:
    """manifest/spine check: spine references ch2, whose file was removed."""
    b, paths = build_epub()
    b.remove(paths["ch2"])
    return b.write(epub_dir / "missing-chapter.epub")


@pytest.fixture
def bad_spine_epub(epub_dir: Path) -> Path:
    """spine check: spine references a manifest id that doesn't exist."""
    b, _ = build_epub()
    text = next(d for n, d, _ in b.entries if n == "OEBPS/content.opf").decode()
    b.replace("OEBPS/content.opf", text.replace('<itemref idref="ch1"/>', '<itemref idref="ghost-chapter"/>'))
    return b.write(epub_dir / "bad-spine.epub")


@pytest.fixture
def no_nav_epub(epub_dir: Path) -> Path:
    """nav check: no path properties='nav' manifest item."""
    b, _ = build_epub(nav=False)
    return b.write(epub_dir / "no-nav.epub")


@pytest.fixture
def nav_missing_file_epub(epub_dir: Path) -> Path:
    """nav check: nav declared but nav.xhtml removed from the archive."""
    b, _ = build_epub()
    b.remove("OEBPS/nav.xhtml")
    return b.write(epub_dir / "nav-missing-file.epub")


@pytest.fixture
def nav_broken_link_epub(epub_dir: Path) -> Path:
    """nav check: TOC links to a file that was removed."""
    b, paths = build_epub()
    b.remove(paths["ch2"])
    nav_text = next(d for n, d, _ in b.entries if n == "OEBPS/nav.xhtml").decode()
    assert "chapter-2.xhtml" in nav_text  # the dead link is still there
    return b.write(epub_dir / "nav-broken-link.epub")


@pytest.fixture
def broken_image_epub(epub_dir: Path) -> Path:
    """images check: chapter-2 references images/deleted-image.jpg which is gone."""
    b, paths = build_epub(chapters=["chapter-1", "chapter-2"])
    page = next(d for n, d, _ in b.entries if n == paths["ch2"]).decode()
    page = page.replace("images/chapter-2.jpg", "images/deleted-image.jpg")
    b.replace(paths["ch2"], page)
    return b.write(epub_dir / "broken-image.epub")


@pytest.fixture
def no_cover_epub(epub_dir: Path) -> Path:
    """cover check: no cover metadata, no properties, no cover-named item."""
    b, _ = build_epub(cover_jpg=False, meta_cover=False)
    return b.write(epub_dir / "no-cover.epub")


@pytest.fixture
def missing_cover_file_epub(epub_dir: Path) -> Path:
    """cover check: cover registered but images/cover.jpg removed."""
    b, paths = build_epub()
    b.remove(paths["cover-image"])
    return b.write(epub_dir / "missing-cover-file.epub")


@pytest.fixture
def oversized_epub(epub_dir: Path) -> Path:
    """sizes check: one member over a custom 1 MB per-file limit."""
    b, _ = build_epub(chapters=["chapter-1"])
    b.add("OEBPS/images/huge.png", b"\x00" * (1500 * 1024), compress_type=zipfile.ZIP_DEFLATED)
    return b.write(epub_dir / "oversized.epub")


@pytest.fixture
def multi_defect_epub(epub_dir: Path) -> Path:
    """Several unrelated defects at once: bad mimetype + removed cover file."""
    b, paths = build_epub()
    b.corrupt_mimetype("text/plain", deflate=True)
    b.remove(paths["cover-image"])
    return b.write(epub_dir / "multi-defect.epub")
