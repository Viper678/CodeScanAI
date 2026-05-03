from __future__ import annotations

import pytest

from app.core.exceptions import InvalidUploadRequest
from app.services.upload_service import _safe_basename, _zip_content_type_ok


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
