"""Zip-bomb heuristic: any entry over the compression-ratio cap is rejected."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from tests._zip_helpers import write_zip
from worker.files.safety import ZipBombError, inspect_archive

CAPS = {
    "max_files": 100,
    "max_dirs": 100,
    "max_total_uncompressed_bytes": 10 * 1024 * 1024,
    "max_entry_uncompressed_bytes": 5 * 1024 * 1024,
    "max_compression_ratio": 100,
    "max_nesting_depth": 1_000,
}


def test_inspect_rejects_high_compression_ratio_entry(tmp_path: Path) -> None:
    # 1 MiB of zeros compresses to roughly a few KB → ratio well over 100:1.
    path = tmp_path / "bomb.zip"
    write_zip(path, {"zeros.bin": b"\x00" * (1024 * 1024)})

    with pytest.raises(ZipBombError):
        inspect_archive(path, **CAPS)


def test_inspect_accepts_normal_compression_ratio(tmp_path: Path) -> None:
    path = tmp_path / "normal.zip"
    # Random-ish text doesn't compress well — ratio stays well under cap.
    body = ("Hello, world!\n" * 100).encode("utf-8")
    write_zip(path, {"hello.txt": body})

    safe = inspect_archive(path, **CAPS)
    assert safe.file_count == 1


def test_inspect_handles_stored_uncompressed_entries(tmp_path: Path) -> None:
    # ZIP_STORED entries have compress_size == file_size → ratio 1:1.
    path = tmp_path / "stored.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("stored.bin", b"\x00" * 1024)
    path.write_bytes(buf.getvalue())

    safe = inspect_archive(path, **CAPS)
    assert safe.file_count == 1
