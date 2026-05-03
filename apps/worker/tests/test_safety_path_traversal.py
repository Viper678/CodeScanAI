"""Path-traversal guard: reject ``..``, absolute, and Windows-style entries."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._zip_helpers import write_zip
from worker.files.safety import (
    PathTraversalError,
    inspect_archive,
    normalize_entry_path,
)

CAPS = {
    "max_files": 100,
    "max_dirs": 100,
    "max_total_uncompressed_bytes": 10 * 1024 * 1024,
    "max_entry_uncompressed_bytes": 5 * 1024 * 1024,
    "max_compression_ratio": 100,
    "max_nesting_depth": 1_000,
}


@pytest.mark.parametrize(
    "name",
    [
        "../etc/passwd",
        "subdir/../../etc/passwd",
        "/etc/passwd",
        "C:\\Windows\\System32\\drivers",
        "evil\\nested.txt",
        "..",
        "",
    ],
)
def test_normalize_rejects_unsafe_paths(name: str) -> None:
    with pytest.raises(PathTraversalError):
        normalize_entry_path(name)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("foo.py", "foo.py"),
        ("src/main.py", "src/main.py"),
        ("./README.md", "README.md"),
        ("a/b/./c/../c/file", "a/b/c/file"),  # collapses but stays inside
    ],
)
def test_normalize_accepts_safe_paths(name: str, expected: str) -> None:
    assert normalize_entry_path(name) == expected


def test_inspect_rejects_traversal_entry(tmp_path: Path) -> None:
    path = tmp_path / "evil.zip"
    write_zip(path, {"../etc/passwd": "root::0:0::/:/bin/sh\n"})

    with pytest.raises(PathTraversalError):
        inspect_archive(path, **CAPS)


def test_inspect_rejects_absolute_entry(tmp_path: Path) -> None:
    path = tmp_path / "absolute.zip"
    write_zip(path, {"/etc/passwd": "x"})

    with pytest.raises(PathTraversalError):
        inspect_archive(path, **CAPS)


def test_inspect_rejects_backslash_entry(tmp_path: Path) -> None:
    path = tmp_path / "windows.zip"
    write_zip(path, {"src\\main.py": "print(1)\n"})

    with pytest.raises(PathTraversalError):
        inspect_archive(path, **CAPS)
