"""Core EPUB inspection logic for epub-precheck.

Everything here runs offline using only the Python standard library
(zipfile + xml.etree). No network, no third-party dependencies.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

# Rough size ceiling that mirrors what retailers (e.g. Kindle Direct
# Publishing) accept for EPUB uploads. Configurable via CLI.
DEFAULT_MAX_FILE_BYTES = 650 * 1024 * 1024  # 650 MB

MIME_MIMETYPE = "application/epub+zip"

OPF_NS = "http://www.idpf.org/2007/opf"
HTML_IMAGE_EXTS = ("jpg", "jpeg", "png", "gif", "svg", "webp")


@dataclass
class Finding:
    """One issue found during the pre-check."""

    level: str  # "ERROR" | "WARN" | "INFO"
    check: str  # short check name, e.g. "spine"
    message: str  # human-friendly explanation
    fix: str  # how the user can fix it

    @property
    def is_blocking(self) -> bool:
        return self.level == "ERROR"


@dataclass
class Report:
    """Aggregated result of a full pre-check run."""

    path: Path
    findings: list[Finding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, level: str, check: str, message: str, fix: str) -> None:
        self.findings.append(Finding(level=level.upper(), check=check, message=message, fix=fix))

    def by_level(self, level: str) -> list[Finding]:
        return [f for f in self.findings if f.level == level.upper()]

    def errors(self) -> list[Finding]:
        return self.by_level("ERROR")

    def warnings(self) -> list[Finding]:
        return self.by_level("WARN")

    def infos(self) -> list[Finding]:
        return self.by_level("INFO")

    @property
    def passed(self) -> bool:
        return not self.errors()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _local(tag: str) -> str:
    """Strip XML namespace from a tag name, e.g. '{ns}spine' -> 'spine'."""
    return tag.rsplit("}", 1)[-1]


def _q(name: str) -> str:
    return f"{{{OPF_NS}}}{name}"


def _safe_member_name(name: str) -> bool:
    """Reject zip members with paths that escape or look unsafe."""
    if name.startswith("/") or "\\" in name:
        return False
    return ".." not in name.split("/")


def _resolve(base: str, href: str) -> str:
    """Join a manifest href (relative to the OPF location) into an archive path."""
    href = href.split("#")[0]
    if href.startswith("/"):
        return posixpath.normpath(href.lstrip("/"))
    return posixpath.normpath(posixpath.join(base, href))


def _resolve_dir(path: str, rel: str) -> str:
    """Resolve rel relative to the *directory* of path (a file path)."""
    rel = rel.split("#")[0]
    if rel.startswith("/"):
        return posixpath.normpath(rel.lstrip("/"))
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(path), rel))
    while joined.startswith("../"):
        joined = joined[3:]
    return joined or "."


def _human(n: int) -> str:
    for power, unit in ((3, "GB"), (2, "MB"), (1, "KB")):
        if n >= 1024**power:
            return f"{n / 1024**power:.1f} {unit}"
    return f"{n} bytes"


class EPUBZip:
    """Thin, safe wrapper around a zipfile. Never extracts anything to disk."""

    def __init__(self, path: Path):
        self.path = path
        self.zf: zipfile.ZipFile | None = None
        self.open_error: str | None = None
        try:
            self.zf = zipfile.ZipFile(path, "r")
        except (zipfile.BadZipFile, OSError) as exc:
            self.open_error = str(exc)

    @property
    def ok(self) -> bool:
        return self.zf is not None

    def infolist(self) -> list[zipfile.ZipInfo]:
        if not self.zf:
            return []
        return self.zf.infolist()

    def names(self) -> list[str]:
        if not self.zf:
            return []
        return [zi.filename for zi in self.zf.infolist() if _safe_member_name(zi.filename)]

    def unsafe_names(self) -> list[str]:
        if not self.zf:
            return []
        return [zi.filename for zi in self.zf.infolist() if not _safe_member_name(zi.filename)]

    def read(self, name: str) -> bytes:
        return self.zf.read(name)

    def read_text(self, name: str) -> str:
        return self.read(name).decode("utf-8")

    def size(self, name: str) -> int:
        for zi in self.zf.infolist():
            if zi.filename == name:
                return zi.file_size
        raise KeyError(name)

    def close(self) -> None:
        if self.zf:
            self.zf.close()


# ---------------------------------------------------------------------------
# Baseline checks
# ---------------------------------------------------------------------------


def check_zip_readable(epub: EPUBZip, report: Report) -> bool:
    """File is a real, fully readable zip with safe member paths."""
    if not epub.ok:
        report.add(
            "ERROR",
            "zip",
            f"'{epub.path.name}' is not a valid ZIP archive ({epub.open_error}).",
            "Re-export the EPUB from your writing tool; don't rename a .zip by hand.",
        )
        return False
    if epub.unsafe_names():
        report.add(
            "ERROR",
            "zip",
            "One or more archive members have unsafe paths (absolute or containing '..').",
            "Repackage the EPUB so all internal paths are clean and relative.",
        )
        return False
    for zi in epub.infolist():
        try:
            with epub.zf.open(zi.filename) as fh:
                while fh.read(1 << 16):
                    pass
        except (zipfile.BadZipFile, OSError, EOFError, RuntimeError):
            report.add(
                "ERROR",
                "zip",
                f"The archive is truncated or corrupt: '{zi.name}' cannot be read.",
                "Re-export the EPUB; a partial upload/copy is the usual cause.",
            )
            return False
    return True


def check_mimetype(epub: EPUBZip, report: Report) -> bool:
    """The first zip entry must be 'mimetype' holding application/epub+zip, stored."""
    infos = epub.infolist()
    if not infos or infos[0].filename != "mimetype":
        report.add(
            "ERROR",
            "mimetype",
            "The first file in the archive must be 'mimetype' — it isn't.",
            "Re-export the EPUB with proper packaging (mimetype must be entry #1, stored).",
        )
        return False
    zi = infos[0]
    content = epub.read("mimetype").decode("utf-8", errors="replace").strip()
    problems = []
    if content != MIME_MIMETYPE:
        problems.append(f"contains '{content}' instead of '{MIME_MIMETYPE}'")
    if zi.compress_type != zipfile.ZIP_STORED:
        problems.append("is compressed (EPUB requires it stored uncompressed)")
    if problems:
        report.add("ERROR", "mimetype", f"The 'mimetype' entry {'; '.join(problems)}.", "Re-export the EPUB with proper tooling.")
        return False
    return True


def check_container(epub: EPUBZip, report: Report) -> str | None:
    """META-INF/container.xml must exist, parse, and point at the OPF."""
    name = "META-INF/container.xml"
    if name not in epub.names():
        report.add(
            "ERROR",
            "container",
            f"'{name}' is missing, so readers can't locate your book file.",
            "Re-export the EPUB; container.xml is written by every EPUB tool.",
        )
        return None
    try:
        root = ET.fromstring(epub.read(name))
    except ET.ParseError as exc:
        report.add(
            "ERROR",
            "container",
            f"'{name}' is not valid XML: {exc}.",
            "Re-export the EPUB rather than hand-editing container.xml.",
        )
        return None
    rootfile = None
    for el in root.iter():
        if _local(el.tag) == "rootfile" and el.get("full-path"):
            rootfile = el
            break
    if rootfile is None:
        report.add(
            "ERROR",
            "container",
            "'container.xml' has no rootfile with a full-path pointing at the OPF.",
            "Re-export the EPUB; the rootfile entry is generated automatically.",
        )
        return None
    return rootfile.get("full-path")


def check_opf(epub: EPUBZip, report: Report, opf_path: str) -> ET.Element | None:
    """The package document must exist and parse. Returns the <package> element."""
    if opf_path not in epub.names():
        report.add(
            "ERROR",
            "container",
            f"The package file '{opf_path}' listed in container.xml is not in the archive.",
            "Re-export the EPUB; content files must live inside the zip.",
        )
        return None
    try:
        root = ET.fromstring(epub.read_text(opf_path))
    except ET.ParseError as exc:
        report.add(
            "ERROR",
            "opf",
            f"'{opf_path}' is not valid XML: {exc}.",
            f"Fix the XML error in '{opf_path}' or re-export the EPUB.",
        )
        return None
    if _local(root.tag) != "package":
        report.add(
            "ERROR",
            "opf",
            f"'{opf_path}' does not start with an <package> element.",
            "Re-export the EPUB; the OPF structure is generated by your tool.",
        )
        return None
    return root


# ---------------------------------------------------------------------------
# Manifest / spine / nav
# ---------------------------------------------------------------------------


def _manifest_items(opf: ET.Element) -> list[ET.Element]:
    manifest = opf.find(_q("manifest"))
    if manifest is None:
        return []
    return [item for item in manifest.iter() if _local(item.tag) == "item"]


def _check_manifest(epub: EPUBZip, report: Report, opf_path: str, opf: ET.Element) -> dict[str, str]:
    """Validate manifest entries. Returns id -> resolved archive path."""
    base = posixpath.dirname(opf_path)
    ids: dict[str, str] = {}
    missing = []
    malformed = []
    for item in _manifest_items(opf):
        iid = item.get("id")
        href = item.get("href")
        if not iid or not href:
            malformed.append(True)
            continue
        resolved = _resolve(base, href)
        ids[iid] = resolved
        if resolved not in epub.names():
            missing.append((iid, href, resolved))
    if malformed:
        report.add(
            "ERROR",
            "manifest",
            f"{len(malformed)} manifest item(s) in '{opf_path}' are missing an id or href.",
            f"Fix or remove the malformed <item> entries in '{opf_path}'.",
        )
    for iid, href, resolved in missing:
        report.add(
            "ERROR",
            "manifest",
            f"Manifest item id='{iid}' points at '{href}', but that file isn't in the EPUB.",
            f"Add '{resolved}' to the archive, or drop the manifest entry from '{opf_path}'.",
        )
    return ids


def check_spine(epub: EPUBZip, report: Report, opf_path: str, opf: ET.Element) -> list[str]:
    """Every spine idref must exist in the manifest. Returns ordered doc paths."""
    manifest_ids = _check_manifest(epub, report, opf_path, opf)
    spine = opf.find(_q("spine"))
    if spine is None:
        report.add(
            "ERROR",
            "spine",
            f"'{opf_path}' has no <spine>, which tells readers your chapter order.",
            "Re-export the EPUB; reading order comes from the spine.",
        )
        return []
    spine_docs: list[str] = []
    bad_refs: list[str] = []
    no_idref = False
    for itemref in spine.iter():
        if _local(itemref.tag) != "itemref":
            continue
        idref = itemref.get("idref")
        if not idref:
            no_idref = True
            continue
        if idref not in manifest_ids:
            bad_refs.append(idref)
            continue
        spine_docs.append(manifest_ids[idref])
    if no_idref:
        report.add(
            "ERROR",
            "spine",
            "A <spine> entry in '{opf}' has no idref attribute.".format(opf=opf_path),
            f"Fix the empty <itemref> in '{opf_path}'.",
        )
    for idref in bad_refs:
        report.add(
            "ERROR",
            "spine",
            f"The spine includes id='{idref}', but no manifest entry has that id.",
            f"Remove the spine reference to '{idref}' or add a matching manifest item.",
        )
    if not spine_docs:
        report.add(
            "ERROR",
            "spine",
            "The spine lists no reading order — readers would open an empty book.",
            "Re-export the EPUB with your chapters included.",
        )
        return []
    report.stats["spine_docs"] = len(spine_docs)
    return spine_docs


def check_nav(epub: EPUBZip, report: Report, opf_path: str, opf: ET.Element) -> str | None:
    """EPUB 3 requires a nav document (properties='nav'), ideally in the spine."""
    base = posixpath.dirname(opf_path)
    nav_item = None
    for item in _manifest_items(opf):
        if "nav" in (item.get("properties") or "").split():
            nav_item = item
            break
    if nav_item is None:
        report.add(
            "WARN",
            "nav",
            "No manifest item has properties='nav', so the book has no EPUB 3 table of contents.",
            "In your export settings include a TOC, or set properties=\"nav\" on the TOC item in the OPF.",
        )
        return None
    href = nav_item.get("href") or ""
    nav_path = _resolve(base, href)
    if nav_path not in epub.names():
        report.add(
            "ERROR",
            "nav",
            f"The nav document '{href}' is declared but missing from the archive.",
            f"Add '{nav_path}' back to the EPUB or repoint the nav entry.",
        )
        return None
    spine_ids = []
    spine = opf.find(_q("spine"))
    if spine is not None:
        for itemref in spine.iter():
            if _local(itemref.tag) == "itemref":
                spine_ids.append(itemref.get("idref"))
    if nav_item.get("id") not in spine_ids:
        report.add(
            "WARN",
            "nav",
            "The nav document exists but is not in the spine, so some readers will ignore the TOC.",
            f'Add <itemref idref="{nav_item.get("id")}"/> to the spine in \'{opf_path}\'.',
        )
    try:
        nav_root = ET.fromstring(epub.read_text(nav_path))
    except ET.ParseError as exc:
        report.add(
            "ERROR",
            "nav",
            f"The nav document '{nav_path}' is not valid XHTML: {exc}.",
            f"Fix the XML error in '{nav_path}'.",
        )
        return None
    entries = [el for el in nav_root.iter() if _local(el.tag) == "a" and (el.text or "").strip()]
    report.stats["nav_entries"] = len(entries)
    if not entries:
        report.add(
            "ERROR",
            "nav",
            f"The nav document '{nav_path}' contains no table-of-contents links.",
            "Add <nav><ol><li><a href='...'>Chapter name</a></li></ol></nav> entries.",
        )
    for el in entries:
        link = el.get("href") or ""
        target = link.split("#")[0]
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = _resolve_dir(nav_path, target)
        if resolved not in epub.names():
            report.add(
                "ERROR",
                "nav",
                f"A TOC entry in '{nav_path}' links to '{target}', which isn't in the EPUB.",
                f"Fix the link in '{nav_path}' or add '{resolved}' to the archive.",
            )
    return nav_path


# ---------------------------------------------------------------------------
# Images, cover, sizes
# ---------------------------------------------------------------------------

_IMG_SRC_RE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE | re.DOTALL)
_SVG_IMAGE_RE = re.compile(r"<\s*image\b[^>]*?\b(?:xlink:)?href\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE | re.DOTALL)
_LINK_HREF_RE = re.compile(r"<link\b[^>]*?\bhref\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE | re.DOTALL)
_DOC_EXTS = (".xhtml", ".html", ".htm")


def check_images(epub: EPUBZip, report: Report, opf: ET.Element, opf_path: str) -> dict[str, str]:
    """Cross-check image references inside content files against the archive.

    Returns manifest id -> media-type map.
    """
    media: dict[str, str] = {}
    for item in _manifest_items(opf):
        iid = item.get("id")
        if iid:
            media[iid] = item.get("media-type") or ""
    doc_files = [n for n in epub.names() if n.lower().endswith(_DOC_EXTS)]
    broken: set[tuple[str, str]] = set()
    for name in doc_files:
        try:
            text = epub.read_text(name)
        except UnicodeDecodeError:
            report.add(
                "WARN",
                "images",
                f"'{name}' is not valid UTF-8, so image references inside it couldn't be checked.",
                "Re-save the file as UTF-8 and re-package.",
            )
            continue
        refs = set(_IMG_SRC_RE.findall(text)) | set(_SVG_IMAGE_RE.findall(text)) | set(_LINK_HREF_RE.findall(text))
        for src in refs:
            if src.startswith(("http://", "https://", "data:", "#", "mailto:")):
                continue
            target = _resolve_dir(name, src.split("#")[0])
            if not target.lower().endswith(HTML_IMAGE_EXTS):
                continue
            if target not in epub.names():
                broken.add((name, src, target))
    for doc, src, target in sorted(broken):
        report.add(
            "ERROR",
            "images",
            f"'{doc}' references image '{src}', which is not in the EPUB.",
            f"Add '{target}' to the archive or fix the reference in '{doc}'.",
        )
    return media


def check_cover(epub: EPUBZip, report: Report, opf_path: str, opf: ET.Element) -> None:
    """Find a cover via properties='cover-image', meta[name=cover], or a
    cover-named manifest item."""
    props_cover = None
    cover_id = None
    for item in _manifest_items(opf):
        if "cover-image" in (item.get("properties") or "").split():
            props_cover = item
            break
    metadata = opf.find(_q("metadata"))
    if metadata is not None:
        for meta in metadata.iter():
            if meta.get("name") == "cover" and meta.get("content"):
                cover_id = meta.get("content")
                break
    named_cover = [item for item in _manifest_items(opf) if "cover" in (item.get("id") or "").lower()]
    if props_cover is None and not cover_id and not named_cover:
        report.add(
            "WARN",
            "cover",
            "No cover detected: no properties=\"cover-image\", no meta[name=cover], and no cover-named image.",
            "Add a cover image, mark it as the cover in your writing tool, and re-export.",
        )
        return
    if props_cover is not None:
        base = posixpath.dirname(opf_path)
        path = _resolve(base, props_cover.get("href") or "")
        if path not in epub.names():
            report.add(
                "ERROR",
                "cover",
                f"The cover image '{props_cover.get('href')}' is registered but missing from the archive.",
                f"Add '{path}' back to the EPUB.",
            )
        elif cover_id and cover_id != props_cover.get("id"):
            report.add(
                "INFO",
                "cover",
                "Cover is declared both modern (properties=\"cover-image\") and legacy (meta[name=cover]) ways.",
                "No action needed.",
            )
    elif cover_id:
        report.add(
            "INFO",
            "cover",
            "Cover declared the legacy way (meta[name=cover]). Most retailers still accept it.",
            'Optional: also set properties="cover-image" on the manifest item.',
        )


def check_sizes(epub: EPUBZip, report: Report, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> None:
    """Flag any single member larger than max_bytes, plus total unpacked size."""
    total = 0
    oversized = []
    for zi in epub.infolist():
        total += zi.file_size
        if zi.file_size > max_bytes:
            oversized.append((zi.filename, zi.file_size))
    report.stats["total_uncompressed_bytes"] = total
    for name, size in sorted(oversized, key=lambda t: -t[1]):
        report.add(
            "ERROR",
            "sizes",
            f"'{name}' is {_human(size)}, over the {_human(max_bytes)} per-file size limit.",
            f"Shrink '{name}' (resize images / lower bitrate) or split it out.",
        )
    if oversized:
        return
    if total > max_bytes:
        report.add(
            "WARN",
            "sizes",
            f"The whole EPUB unpacks to {_human(total)}, above the {_human(max_bytes)} guideline.",
            "Reduce image sizes first — they're almost always the bulk of an EPUB.",
        )
    else:
        report.add(
            "INFO",
            "sizes",
            f"Archive looks healthy: {_human(total)} unpacked across {len(epub.names())} files.",
            "No action needed.",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_all(path: Path, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> Report:
    """Run every check and return the aggregated Report."""
    report = Report(path=path)
    epub = EPUBZip(path)
    try:
        if not check_zip_readable(epub, report):
            return report
        report.stats["member_count"] = len(epub.names())
        check_mimetype(epub, report)
        opf_path = check_container(epub, report)
        if opf_path is None:
            return report
        opf = check_opf(epub, report, opf_path)
        if opf is None:
            return report
        check_spine(epub, report, opf_path, opf)
        check_nav(epub, report, opf_path, opf)
        check_images(epub, report, opf, opf_path)
        check_cover(epub, report, opf_path, opf)
        check_sizes(epub, report, max_bytes=max_bytes)
    finally:
        epub.close()
    return report
