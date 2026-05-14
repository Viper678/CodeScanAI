from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import InvalidUploadRequest
from app.services.upload_service import (
    _safe_basename,
    _wipe_legacy_extract_path,
    _wipe_legacy_storage_path,
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


def test_wipe_legacy_extract_path_propagates_real_removal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Permissions / I/O failures during ``shutil.rmtree`` MUST propagate.
    The previous ``ignore_errors=True`` shape silently masked these,
    letting ``delete_upload`` commit the DB delete while files remained
    on disk. Codex P2 on M2.
    """

    def boom(_path: str) -> None:
        raise PermissionError("simulated EACCES on rmtree")

    monkeypatch.setattr("app.services.upload_service.shutil.rmtree", boom)

    with pytest.raises(PermissionError):
        _wipe_legacy_extract_path("/data/extracts/legacy")

    # Sanity: the FileNotFoundError carve-out still applies (idempotent).
    def already_gone(_path: str) -> None:
        raise FileNotFoundError("simulated already-removed tree")

    monkeypatch.setattr("app.services.upload_service.shutil.rmtree", already_gone)
    _wipe_legacy_extract_path("/data/extracts/already-gone")  # no raise


# ---- _wipe_legacy_storage_path (Codex P2 round 3) --------------------------


def test_wipe_legacy_storage_path_unlinks_legacy_file(tmp_path: Path) -> None:
    """Pre-M2 zip uploads stored ``storage_path`` as a single file path
    (e.g. ``/data/uploads/<id>/repo.zip``). The legacy fallback must
    unlink the file."""

    legacy_dir = tmp_path / "uploads" / "abc"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "repo.zip"
    legacy_file.write_bytes(b"PK\x03\x04")

    _wipe_legacy_storage_path(str(legacy_file))

    assert not legacy_file.exists()
    # The parent dir is intentionally left alone — never walk to a
    # parent in the legacy helper.
    assert legacy_dir.exists()


def test_wipe_legacy_storage_path_rmtrees_legacy_dir(tmp_path: Path) -> None:
    """If a pre-M2 upload stored ``storage_path`` as a directory path
    (e.g. loose-upload layouts), the helper must rmtree it."""

    legacy = tmp_path / "uploads" / "abc"
    (legacy / "a").mkdir(parents=True)
    (legacy / "a" / "x.py").write_text("print(1)\n")

    _wipe_legacy_storage_path(str(legacy))

    assert not legacy.exists()


def test_wipe_legacy_storage_path_handles_none() -> None:
    _wipe_legacy_storage_path(None)


def test_wipe_legacy_storage_path_is_no_op_for_relative_keys(tmp_path: Path) -> None:
    """Post-M2 ``storage_path`` is a storage key prefix like
    ``uploads/<id>`` (no leading slash). Helper must NOT misinterpret
    these as filesystem paths."""

    del tmp_path  # not used; helper must be a no-op without touching disk
    _wipe_legacy_storage_path("uploads/abc")
