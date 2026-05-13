from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import InvalidUploadRequest
from app.services.upload_service import (
    _safe_basename,
    _wipe_legacy_extract_path,
    _zip_content_type_ok,
)


@pytest.mark.parametrize(
    "value",
    [
        "report.zip",
        "main.py",
        "Dockerfile",
        "weird name with spaces.txt",
    ],
)
def test_safe_basename_accepts_clean_names(value: str) -> None:
    assert _safe_basename(value) == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "..",
        ".",
        "/etc/passwd",
        "..\\Windows\\evil.dll",
        "subdir/script.py",
        "with\x00null.py",
    ],
)
def test_safe_basename_rejects_dangerous_names(value: str | None) -> None:
    with pytest.raises(InvalidUploadRequest):
        _safe_basename(value)


@pytest.mark.parametrize(
    "header",
    [
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
        "application/zip; charset=binary",
        None,
    ],
)
def test_zip_content_type_accepts_known_values(header: str | None) -> None:
    assert _zip_content_type_ok(header) is True


@pytest.mark.parametrize(
    "header",
    [
        "text/plain",
        "image/png",
        "application/x-tar",
    ],
)
def test_zip_content_type_rejects_other_values(header: str) -> None:
    assert _zip_content_type_ok(header) is False


# ---- _wipe_legacy_extract_path (Codex P1 on M2) ----------------------------


def test_wipe_legacy_extract_path_removes_absolute_dir(tmp_path: Path) -> None:
    """Pre-M2 ``extract_path`` was an absolute filesystem path. Wiping it
    via the legacy-shape fallback must remove the on-disk tree so a
    deleted upload doesn't leak files."""

    legacy = tmp_path / "extracts" / "abc-123"
    (legacy / "src").mkdir(parents=True)
    (legacy / "src" / "x.py").write_text("print(1)\n")

    _wipe_legacy_extract_path(str(legacy))

    assert not legacy.exists()


def test_wipe_legacy_extract_path_is_no_op_for_relative_keys(tmp_path: Path) -> None:
    """Post-M2 ``extract_path`` values are storage key prefixes like
    ``uploads/<id>/extracted`` — relative, no leading slash. The wipe
    fallback must NOT misinterpret these as filesystem paths and start
    deleting random subtrees."""

    del tmp_path  # not used; helper must be a no-op without touching disk
    _wipe_legacy_extract_path("uploads/abc/extracted")


def test_wipe_legacy_extract_path_handles_none() -> None:
    """No extract_path on the upload row — early return, no crash."""

    _wipe_legacy_extract_path(None)


def test_wipe_legacy_extract_path_is_idempotent_when_dir_missing(tmp_path: Path) -> None:
    """If the legacy tree was already removed (e.g. retention sweep ran
    once already), a second call must not raise."""

    _wipe_legacy_extract_path(str(tmp_path / "does-not-exist"))
