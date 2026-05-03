"""Numeric caps: file count, total uncompressed bytes, single-entry size."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from tests._zip_helpers import write_zip
from worker.files.safety import (
    EntryTooLarge,
    TooLargeUncompressed,
    TooManyEntries,
    inspect_archive,
)

# Tighten caps in tests so we don't need to materialize 20k entries on disk.
CAPS_BASE: dict[str, int] = {
    "max_files": 100,
    "max_dirs": 100,
    "max_total_uncompressed_bytes": 10 * 1024 * 1024,
    "max_entry_uncompressed_bytes": 5 * 1024 * 1024,
    "max_compression_ratio": 1_000_000,  # disable bomb check for these tests
}


def test_inspect_rejects_too_many_files(tmp_path: Path) -> None:
    path = tmp_path / "many.zip"
    entries: dict[str, bytes | str] = {f"file_{i:04d}.txt": f"x{i}\n" for i in range(150)}
    write_zip(path, entries)

    with pytest.raises(TooManyEntries):
        inspect_archive(path, **{**CAPS_BASE, "max_files": 100})


def test_inspect_rejects_too_large_total(tmp_path: Path) -> None:
    path = tmp_path / "fat.zip"
    # Two entries, each 600 KB of random-ish text → > 1 MB total.
    body = ("ab" * 300_000).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("a.txt", body)
        zf.writestr("b.txt", body)
    path.write_bytes(buf.getvalue())

    with pytest.raises(TooLargeUncompressed):
        inspect_archive(path, **{**CAPS_BASE, "max_total_uncompressed_bytes": 1_000_000})


def test_inspect_rejects_oversize_single_entry(tmp_path: Path) -> None:
    path = tmp_path / "huge.zip"
    body = ("x" * 200_000).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("huge.txt", body)
    path.write_bytes(buf.getvalue())

    with pytest.raises(EntryTooLarge):
        inspect_archive(path, **{**CAPS_BASE, "max_entry_uncompressed_bytes": 100_000})


def test_inspect_accepts_at_caps(tmp_path: Path) -> None:
    path = tmp_path / "ok.zip"
    entries: dict[str, bytes | str] = {f"f{i}.txt": "x\n" for i in range(10)}
    write_zip(path, entries)

    safe = inspect_archive(path, **CAPS_BASE)
    assert safe.file_count == 10
