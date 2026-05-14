"""Path nesting depth: archives whose entries exceed ``max_nesting_depth`` reject."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._zip_helpers import write_zip
from worker.files.safety import PathTooDeep, inspect_archive

CAPS = {
    "max_files": 100,
    "max_dirs": 100,
    "max_total_uncompressed_bytes": 10 * 1024 * 1024,
    "max_entry_uncompressed_bytes": 5 * 1024 * 1024,
    "max_compression_ratio": 1_000_000,
}


def _deep_path(depth: int, basename: str = "leaf.txt") -> str:
    return "/".join([f"d{i}" for i in range(depth - 1)] + [basename])


def test_inspect_rejects_overly_deep_entry(tmp_path: Path) -> None:
    path = tmp_path / "deep.zip"
    write_zip(path, {_deep_path(25): "hi\n"})

    with pytest.raises(PathTooDeep):
        inspect_archive(path, **CAPS, max_nesting_depth=20)


def test_inspect_accepts_entry_at_depth_cap(tmp_path: Path) -> None:
    path = tmp_path / "ok.zip"
    write_zip(path, {_deep_path(20): "ok\n"})

    safe = inspect_archive(path, **CAPS, max_nesting_depth=20)
    assert safe.file_count == 1


def test_inspect_rejects_deep_directory_entry(tmp_path: Path) -> None:
    """Directory-only entries also count toward nesting depth."""

    # zipfile treats trailing "/" as a directory entry.
    path = tmp_path / "deepdir.zip"
    write_zip(path, {_deep_path(25, basename="") + "/": ""})

    with pytest.raises(PathTooDeep):
        inspect_archive(path, **CAPS, max_nesting_depth=20)
