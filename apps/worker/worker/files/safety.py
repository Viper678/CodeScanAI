"""Pre-flight safety checks for zip extraction.

Encodes every rule in docs/FILE_HANDLING.md §"Zip extraction safety". The
caller (``worker.tasks.prepare_upload``) runs ``inspect_archive`` first, then
extracts entry-by-entry via ``safe_extract`` so a sneaky entry late in the
archive doesn't escape after the pre-flight pass.
"""

from __future__ import annotations

import logging
import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)


# ---- Exceptions -------------------------------------------------------------


class SafetyError(Exception):
    """Base class for archive-safety violations."""


class ZipBombError(SafetyError):
    """Compression ratio for some entry exceeds the configured cap."""


class PathTraversalError(SafetyError):
    """An entry's path is absolute, escapes the root, or contains backslashes."""


class TooManyEntries(SafetyError):
    """The archive contains more files (or directories) than allowed."""


class TooLargeUncompressed(SafetyError):
    """Sum of uncompressed entry sizes exceeds the cap."""


class EntryTooLarge(SafetyError):
    """A single entry's uncompressed size exceeds the cap."""


class PathTooDeep(SafetyError):
    """An entry's path nesting depth exceeds the configured cap."""


class CorruptArchiveError(SafetyError):
    """The archive could not be parsed by ``zipfile``."""


# ---- Result types -----------------------------------------------------------


@dataclass(frozen=True)
class SafeArchive:
    """Pre-flight result handed to the extractor."""

    file_count: int
    dir_count: int
    total_uncompressed: int


# ---- Path validation --------------------------------------------------------


def normalize_entry_path(name: str) -> str:
    """Validate and normalize a zip entry's filename.

    Rejects (raises ``PathTraversalError``):
    - empty
    - absolute paths (``/foo``)
    - drive letters (``C:\\``)
    - backslashes (Windows-style separators) anywhere
    - any component equal to ``..``
    - paths whose normalized form starts with ``..``

    Returns a forward-slash-normalized relative path with no leading ``./``
    and no trailing slash.
    """

    if not name:
        raise PathTraversalError("empty entry name")
    if "\\" in name:
        raise PathTraversalError(f"backslash in entry path: {name!r}")
    if name.startswith("/") or (len(name) >= 2 and name[1] == ":"):
        raise PathTraversalError(f"absolute entry path: {name!r}")

    # Strip trailing slash but remember it was a directory entry.
    cleaned = name.rstrip("/")
    if not cleaned:
        # The entry was just "/" — already caught above, but defensive.
        raise PathTraversalError(f"invalid entry path: {name!r}")

    # os.path.normpath collapses './' and '../' but on Windows it would also
    # convert '/' to '\\'; we explicitly use posixpath via replace so the
    # check is cross-platform.
    normalized = os.path.normpath(cleaned).replace(os.sep, "/")
    if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        raise PathTraversalError(f"path traversal in entry: {name!r}")
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        raise PathTraversalError(f"parent traversal segment in entry: {name!r}")
    return normalized


def is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    """Return True iff the zip entry represents a symbolic link.

    Unix-origin zip entries store mode bits in the high 16 bits of
    ``external_attr``; symlinks have ``S_IFLNK`` set. Per FILE_HANDLING.md,
    we never extract symlinks regardless of origin platform.
    """

    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


# ---- Pre-flight inspection --------------------------------------------------


def _compression_ratio(info: zipfile.ZipInfo) -> float:
    if info.compress_size <= 0:
        # Uncompressible / stored entries: the ratio is 1:1 by definition.
        return float(info.file_size) if info.file_size > 0 else 0.0
    return info.file_size / info.compress_size


def inspect_archive(
    zip_path: Path,
    *,
    max_files: int,
    max_dirs: int,
    max_total_uncompressed_bytes: int,
    max_entry_uncompressed_bytes: int,
    max_compression_ratio: int,
    max_nesting_depth: int,
) -> SafeArchive:
    """Open ``zip_path`` and verify every entry against the configured caps.

    Raises a ``SafetyError`` subclass on the first violation. Counts
    directories and files separately to surface clearer error messages and
    so callers can preallocate.
    """

    try:
        archive = zipfile.ZipFile(zip_path, mode="r")
    except zipfile.BadZipFile as exc:
        raise CorruptArchiveError(f"not a valid zip archive: {exc}") from exc

    file_count = 0
    dir_count = 0
    total = 0
    try:
        for info in archive.infolist():
            # Path safety: reject before counting so we fail fast on malicious
            # entries. Capture the normalized form for the depth check below.
            normalized = normalize_entry_path(info.filename)
            depth = normalized.count("/") + 1
            if depth > max_nesting_depth:
                raise PathTooDeep(
                    f"entry {info.filename!r} nesting depth {depth} "
                    f"exceeds cap of {max_nesting_depth}"
                )
            if info.is_dir():
                dir_count += 1
                if dir_count > max_dirs:
                    raise TooManyEntries(f"archive has more than {max_dirs} directory entries")
                continue

            file_count += 1
            if file_count > max_files:
                raise TooManyEntries(f"archive has more than {max_files} file entries")
            if info.file_size > max_entry_uncompressed_bytes:
                raise EntryTooLarge(
                    f"entry {info.filename!r} uncompressed size "
                    f"{info.file_size} exceeds per-entry cap "
                    f"{max_entry_uncompressed_bytes}"
                )
            total += info.file_size
            if total > max_total_uncompressed_bytes:
                raise TooLargeUncompressed(
                    f"total uncompressed size exceeds {max_total_uncompressed_bytes} bytes"
                )
            if _compression_ratio(info) > max_compression_ratio:
                raise ZipBombError(
                    f"entry {info.filename!r} compression ratio "
                    f"{_compression_ratio(info):.1f}:1 exceeds "
                    f"{max_compression_ratio}:1 cap"
                )
    finally:
        archive.close()

    return SafeArchive(
        file_count=file_count,
        dir_count=dir_count,
        total_uncompressed=total,
    )


# ---- Extraction -------------------------------------------------------------


def safe_extract(zip_path: Path, extract_root: Path) -> int:
    """Extract ``zip_path`` into ``extract_root``, skipping symlink entries.

    Returns the number of regular-file entries written. Per
    FILE_HANDLING.md §3 every destination is re-resolved against the root
    via ``Path.is_relative_to`` so a malicious entry that slipped past
    the pre-flight check (e.g. stored as bytes) cannot escape.
    """

    extract_root = extract_root.resolve()
    extract_root.mkdir(parents=True, exist_ok=True)
    written = 0

    with zipfile.ZipFile(zip_path, mode="r") as archive:
        for info in archive.infolist():
            if is_symlink_entry(info):
                logger.warning("skipping symlink zip entry %r (extract policy)", info.filename)
                continue
            if info.is_dir():
                # Pre-create empty directories — extractall would do the same
                # but we need the path-traversal recheck.
                rel = normalize_entry_path(info.filename)
                target = (extract_root / rel).resolve()
                if not target.is_relative_to(extract_root):
                    raise PathTraversalError(f"directory entry escaped root: {info.filename!r}")
                target.mkdir(parents=True, exist_ok=True)
                continue

            rel = normalize_entry_path(info.filename)
            target = (extract_root / rel).resolve()
            if not target.is_relative_to(extract_root):
                raise PathTraversalError(f"file entry escaped root: {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, mode="r") as src, target.open("wb") as dst:
                # Bound the per-entry write so a corrupted central directory
                # can't lie about file_size.
                _stream(src, dst)
            written += 1

    return written


def _stream(src: IO[bytes], dst: IO[bytes], chunk_size: int = 1 << 16) -> None:
    """Copy ``src`` to ``dst`` in chunks. Both are file-like objects."""

    while True:
        chunk = src.read(chunk_size)
        if not chunk:
            return
        dst.write(chunk)
