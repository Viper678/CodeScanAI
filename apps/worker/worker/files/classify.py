"""Per-file classification: language, binary, default-exclusion reason.

Implements docs/FILE_HANDLING.md §"Tree building" and §"Default exclusion
rules". The output ``FileMeta`` becomes a row in the ``files`` table.

Rules are applied in priority order — the first match wins for
``excluded_reason``. ``oversize`` and ``binary`` are dynamic (require I/O);
all other reasons are derived from path / extension.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from worker.core.config import settings
from worker.core.file_types import (
    ALLOWED_LOOSE_EXTENSIONS,
    ALLOWED_LOOSE_FILENAMES,
    detect_language,
)
from worker.core.models import (
    EXCLUDED_REASON_ARCHIVE,
    EXCLUDED_REASON_BINARY,
    EXCLUDED_REASON_BUILD_ARTIFACT,
    EXCLUDED_REASON_DOTFILE,
    EXCLUDED_REASON_FONT,
    EXCLUDED_REASON_IDE_DIR,
    EXCLUDED_REASON_IMAGE,
    EXCLUDED_REASON_LOCKFILE,
    EXCLUDED_REASON_MEDIA,
    EXCLUDED_REASON_OVERSIZE,
    EXCLUDED_REASON_UNKNOWN_EXT,
    EXCLUDED_REASON_VCS_DIR,
    EXCLUDED_REASON_VENDOR_DIR,
)

# ---- Static path/extension sets (case-insensitive comparisons) --------------

VENDOR_DIR_NAMES: frozenset[str] = frozenset(
    {
        "node_modules",
        "vendor",
        "third_party",
        ".venv",
        "venv",
        "env",
        "virtualenv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "target",
        "build",
        "dist",
        "out",
        ".next",
        ".nuxt",
        ".gradle",
        ".cargo",
        "deps",
        "_deps",
        "bower_components",
    }
)

VCS_DIR_NAMES: frozenset[str] = frozenset({".git", ".svn", ".hg", ".bzr"})

IDE_DIR_NAMES: frozenset[str] = frozenset({".idea", ".vscode", ".vs", ".fleet", ".ds_store"})

LOCKFILE_NAMES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "poetry.lock",
        "pipfile.lock",
        "composer.lock",
        "cargo.lock",
        "gemfile.lock",
        "go.sum",
        "mix.lock",
        "gradle.lockfile",
    }
)

BUILD_ARTIFACT_EXTS: frozenset[str] = frozenset(
    {
        "pyc",
        "pyo",
        "class",
        "jar",
        "war",
        "o",
        "a",
        "so",
        "dylib",
        "dll",
        "exe",
        "obj",
        "lib",
        "map",
    }
)

# Compound suffixes (basename ends with these literally).
BUILD_ARTIFACT_SUFFIXES: tuple[str, ...] = (".min.js", ".min.css")

IMAGE_EXTS: frozenset[str] = frozenset(
    {"png", "jpg", "jpeg", "gif", "ico", "bmp", "tif", "tiff", "webp", "heic", "avif"}
)

FONT_EXTS: frozenset[str] = frozenset({"ttf", "otf", "woff", "woff2", "eot"})

MEDIA_EXTS: frozenset[str] = frozenset({"mp3", "mp4", "mov", "avi", "mkv", "wav", "flac", "ogg"})

ARCHIVE_EXTS: frozenset[str] = frozenset({"zip", "tar", "gz", "bz2", "xz", "7z", "rar"})

# Allowlisted dotfiles — basename starts with '.' but we still scan them.
DOTFILE_ALLOWLIST: frozenset[str] = frozenset(
    {".env", ".env.example", ".gitignore", ".dockerignore"}
)


# ---- Result type ------------------------------------------------------------


@dataclass(frozen=True)
class FileMeta:
    """Materialized metadata for one regular file inside an upload."""

    path: str
    parent_path: str
    name: str
    size_bytes: int
    sha256: str
    language: str | None
    is_binary: bool
    is_excluded_by_default: bool
    excluded_reason: str | None


# ---- Helpers ----------------------------------------------------------------


def _split_basename(name: str) -> tuple[str, str]:
    base = os.path.basename(name).lower()
    _, ext = os.path.splitext(base)
    if ext.startswith("."):
        ext = ext[1:]
    return base, ext


def _path_segments_lower(rel_path: str) -> list[str]:
    return [seg.lower() for seg in rel_path.split("/") if seg]


def is_binary(file_path: Path, *, sample_size: int = 8192) -> bool:
    """Return True iff ``file_path`` looks like a binary file.

    Heuristic from docs/FILE_HANDLING.md §"Binary detection":
    1. NUL byte in the first ``sample_size`` bytes → binary.
    2. Otherwise: ratio of non-text bytes to total > 30% → binary.

    Text bytes: ``\t``, ``\n``, ``\r``, ``0x20-0x7E``, and ``0x80-0xFF``
    (we let the scanner's ``errors='replace'`` deal with bad UTF-8 later).
    """

    with file_path.open("rb") as fh:
        sample = fh.read(sample_size)
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    text_bytes = {0x09, 0x0A, 0x0D, *range(0x20, 0x7F), *range(0x80, 0x100)}
    non_text = sum(1 for b in sample if b not in text_bytes)
    return (non_text / len(sample)) > 0.30


def sha256_of(file_path: Path, *, chunk_size: int = 1 << 16) -> str:
    """Return the SHA-256 hex digest of ``file_path``."""

    digest = hashlib.sha256()
    with file_path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


# ---- Default-exclusion rule pipeline ----------------------------------------


def _exclusion_from_path(rel_path: str, base: str, ext: str) -> str | None:
    """Return the first matching exclusion reason from path/name/ext rules.

    Order mirrors docs/FILE_HANDLING.md table after dynamic checks
    (oversize, binary) which the caller applies first.
    """

    segments = _path_segments_lower(rel_path)
    # All segments except the basename are directories the file lives under.
    parent_segments = segments[:-1]

    if any(seg in VENDOR_DIR_NAMES for seg in parent_segments):
        return EXCLUDED_REASON_VENDOR_DIR
    if any(seg in VCS_DIR_NAMES for seg in parent_segments):
        return EXCLUDED_REASON_VCS_DIR
    if any(seg in IDE_DIR_NAMES for seg in parent_segments):
        return EXCLUDED_REASON_IDE_DIR
    # Also catch IDE/vendor/vcs dirs declared as the file itself (rare for
    # files but possible for files literally named '.DS_Store').
    if base in VCS_DIR_NAMES:
        return EXCLUDED_REASON_VCS_DIR
    if base in IDE_DIR_NAMES:
        return EXCLUDED_REASON_IDE_DIR

    if base in LOCKFILE_NAMES:
        return EXCLUDED_REASON_LOCKFILE
    if ext in BUILD_ARTIFACT_EXTS or any(base.endswith(s) for s in BUILD_ARTIFACT_SUFFIXES):
        return EXCLUDED_REASON_BUILD_ARTIFACT
    if ext in IMAGE_EXTS:
        return EXCLUDED_REASON_IMAGE
    if ext in FONT_EXTS:
        return EXCLUDED_REASON_FONT
    if ext in MEDIA_EXTS:
        return EXCLUDED_REASON_MEDIA
    if ext in ARCHIVE_EXTS:
        return EXCLUDED_REASON_ARCHIVE

    # Allowlisted dotfiles (``.env``, ``.gitignore``, ...) are intentionally
    # scanned. Bail out before any "unknown_ext" trip.
    if base in DOTFILE_ALLOWLIST:
        return None
    if base.startswith("."):
        return EXCLUDED_REASON_DOTFILE

    # Unknown extension AND not text-like (no extension is allowed via
    # ALLOWED_LOOSE_FILENAMES e.g. Dockerfile). Anything outside both
    # sets is "unknown_ext".
    if ext:
        if ext not in ALLOWED_LOOSE_EXTENSIONS:
            return EXCLUDED_REASON_UNKNOWN_EXT
    elif base not in ALLOWED_LOOSE_FILENAMES:
        return EXCLUDED_REASON_UNKNOWN_EXT
    return None


def classify(file_path: Path, extract_root: Path) -> FileMeta:
    """Build a ``FileMeta`` for ``file_path`` relative to ``extract_root``.

    ``file_path`` must already be inside ``extract_root`` (the caller is
    responsible — typically because it came from a ``Path.rglob`` over the
    extracted tree).

    Args:
        file_path: Absolute path to the on-disk file.
        extract_root: Root directory of the upload's extracted tree.

    Returns:
        A populated ``FileMeta`` ready to be persisted.
    """

    rel_path = file_path.relative_to(extract_root).as_posix()
    parent_path = os.path.dirname(rel_path)
    name = os.path.basename(rel_path)
    base, ext = _split_basename(name)

    size_bytes = file_path.stat().st_size
    digest = sha256_of(file_path)
    binary = is_binary(file_path)
    language = None if binary else detect_language(name)

    # Dynamic reasons take priority per FILE_HANDLING.md table.
    max_scan = settings.max_scan_file_size_mb * 1024 * 1024
    reason: str | None
    if size_bytes > max_scan:
        reason = EXCLUDED_REASON_OVERSIZE
    elif binary:
        reason = EXCLUDED_REASON_BINARY
    else:
        reason = _exclusion_from_path(rel_path, base, ext)

    return FileMeta(
        path=rel_path,
        parent_path=parent_path,
        name=name,
        size_bytes=size_bytes,
        sha256=digest,
        language=language,
        is_binary=binary,
        is_excluded_by_default=reason is not None,
        excluded_reason=reason,
    )
