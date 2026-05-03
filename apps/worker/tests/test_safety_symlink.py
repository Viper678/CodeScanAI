"""Symlink entries are skipped (with a warning), never extracted."""

from __future__ import annotations

import io
import logging
import stat
import zipfile
from pathlib import Path

import pytest

from worker.files.safety import is_symlink_entry, safe_extract


def _write_symlink_zip(path: Path, link_name: str, target: str) -> None:
    """Construct a zip with a single Unix symlink entry pointing at ``target``."""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
        info = zipfile.ZipInfo(link_name)
        info.create_system = 3  # Unix
        # Mode = 0o120777 marks the entry as a symlink in the zip metadata.
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, target)
    path.write_bytes(buf.getvalue())


def test_is_symlink_entry_detects_symlink_mode(tmp_path: Path) -> None:
    zip_path = tmp_path / "link.zip"
    _write_symlink_zip(zip_path, "evil-link", "../../../../etc/passwd")

    with zipfile.ZipFile(zip_path) as zf:
        info = zf.infolist()[0]
        assert is_symlink_entry(info) is True


def test_safe_extract_skips_symlink_entry(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    zip_path = tmp_path / "link.zip"
    _write_symlink_zip(zip_path, "passwd-link", "/etc/passwd")

    extract_root = tmp_path / "out"
    caplog.set_level(logging.WARNING)
    written = safe_extract(zip_path, extract_root)

    assert written == 0
    # No file was created — nothing pollutes the index, and certainly nothing
    # follows the link.
    assert not (extract_root / "passwd-link").exists()
    assert any("symlink" in record.message.lower() for record in caplog.records)
