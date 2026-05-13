"""Path-traversal guard: reject ``..``, absolute, and Windows-style entries."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._zip_helpers import write_zip
from worker.files.safety import (
    FileDirectoryCollision,
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
        # ``.`` and patterns that normalize to ``.`` produce a degenerate
        # storage key (``uploads/<id>/extracted/.``) which LocalStorage
        # collapses to the prefix itself — silently corrupting the
        # extracted tree. Codex P2 on M2.
        ".",
        "./",
        "dir/..",
        "a/b/../..",
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


# ---- File-vs-directory collision (Codex P2 on M2, round 5) -----------------


def test_inspect_rejects_file_then_directory_at_same_path(tmp_path: Path) -> None:
    """``a`` as a file and ``a/b.py`` as a file means ``a`` is both a file
    AND a required parent directory. LocalStorage rejects implicitly;
    GCS would store both, and the frontend would render ``a`` as a dir
    marker, hiding the file. Pre-flight must reject."""

    path = tmp_path / "collide_file_then_dir.zip"
    write_zip(path, {"a": "first\n", "a/b.py": "print(1)\n"})

    with pytest.raises(FileDirectoryCollision):
        inspect_archive(path, **CAPS)


def test_inspect_rejects_directory_then_file_at_same_path(tmp_path: Path) -> None:
    """Inverse ordering — ``a/b.py`` first puts ``a`` in the directory set,
    then ``a`` as a file entry must be rejected."""

    path = tmp_path / "collide_dir_then_file.zip"
    write_zip(path, {"a/b.py": "print(1)\n", "a": "second\n"})

    with pytest.raises(FileDirectoryCollision):
        inspect_archive(path, **CAPS)


def test_inspect_rejects_explicit_dir_entry_at_existing_file_path(
    tmp_path: Path,
) -> None:
    """An explicit ``a/`` directory entry after ``a`` as a file is a
    collision too."""

    path = tmp_path / "collide_explicit_dir.zip"
    write_zip(path, {"a": "file\n", "a/": ""})

    with pytest.raises(FileDirectoryCollision):
        inspect_archive(path, **CAPS)


def test_inspect_accepts_normal_nested_tree(tmp_path: Path) -> None:
    """Sanity: a well-formed tree (``src/main.py``, ``src/utils/helper.py``)
    must NOT trip the collision check — only conflicts where a path is
    both a file and a directory should fail."""

    path = tmp_path / "normal.zip"
    write_zip(
        path,
        {
            "src/main.py": "print(1)\n",
            "src/utils/helper.py": "def f(): pass\n",
            "README.md": "hello\n",
        },
    )

    result = inspect_archive(path, **CAPS)
    assert result.file_count == 3
