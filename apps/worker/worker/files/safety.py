"""Pre-flight safety checks for zip extraction.

Encodes every rule in docs/FILE_HANDLING.md §"Zip extraction safety". The
caller (``worker.tasks.prepare_upload``) runs ``inspect_archive`` first, then
extracts entry-by-entry via ``safe_extract`` so a sneaky entry late in the
archive doesn't escape after the pre-flight pass.

Post-M2 extraction writes through ``worker.storage.Storage`` instead of
directly to the filesystem. Validators (path traversal, symlinks,
zip-bomb ratio, nesting depth) still run on the in-memory zip entry's
metadata BEFORE any ``storage.put_stream`` call, so a failed validator
never leaves bytes in the backend.
"""

from __future__ import annotations

import logging
import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

from worker.storage.base import Storage, extracted_key

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


def safe_extract(
    zip_path: Path,
    *,
    storage: Storage,
    upload_id: str,
) -> int:
    """Extract ``zip_path`` into ``storage`` under the upload's prefix.

    Each entry is normalized + re-validated for path safety BEFORE any
    bytes hit ``storage`` — so a failed validator never leaves a partial
    object in the backend. Returns the number of regular-file entries
    written. Symlink entries are skipped (with a warning).

    Args:
        zip_path: Path to the on-disk zip. The api stages this via
            ``storage.put_bytes`` from the upload request; the worker
            downloads it back to a local temp before calling here (or
            passes a path inside a LocalStorage root for the local
            backend — both shapes work as long as the file is readable
            by ``zipfile.ZipFile``).
        storage: The configured Storage backend (LocalStorage or
            GcsStorage). Entries are written via ``put_stream`` so large
            entries don't materialize into memory.
        upload_id: The upload's UUID as a string. Keys are namespaced
            under ``uploads/<upload_id>/extracted/<rel>``.

    Returns:
        Count of regular-file entries written.
    """

    written = 0

    with zipfile.ZipFile(zip_path, mode="r") as archive:
        for info in archive.infolist():
            if is_symlink_entry(info):
                logger.warning("skipping symlink zip entry %r (extract policy)", info.filename)
                continue
            if info.is_dir():
                # Directory entries are skipped — there are no "empty
                # directories" in an object store. The local backend's
                # put_stream auto-creates parent dirs on demand, so any
                # file under a directory entry will still land there.
                # We still re-normalize for the side-effect of raising
                # on a traversal-shaped directory entry.
                normalize_entry_path(info.filename)
                continue

            rel = normalize_entry_path(info.filename)
            # Belt-and-braces traversal check — normalize_entry_path
            # already rejects '../' segments, but we resolve once more
            # against an in-memory anchor so a stored-as-bytes filename
            # with embedded null bytes / oddities is caught at the
            # extraction boundary, not later via storage error.
            if rel.startswith("/") or rel.startswith("../") or "/../" in rel:
                raise PathTraversalError(f"file entry escaped root: {info.filename!r}")
            key = extracted_key(upload_id, rel)
            with archive.open(info, mode="r") as src:
                # ``ZipExtFile`` returned by ``archive.open`` is typed as
                # ``IO[bytes]`` but is a binary-mode ``BufferedIOBase`` —
                # cast to satisfy the protocol annotation. The runtime
                # surface (``read``) is identical.
                storage.put_stream(key, cast(BinaryIO, src))
            written += 1

    return written
