"""Unit tests for the retention cleanup beat task (T5.2).

Pure-Python tests with stubbed sessions and a frozen clock — no real DB
or Redis. The integration test in ``tests/integration/test_cleanup.py``
covers the end-to-end DB cascade.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from freezegun import freeze_time

from worker.core import config as cfg
from worker.tasks import cleanup as cleanup_module
from worker.tasks.cleanup import (
    CleanupReport,
    _delete_one,
    _Outcome,
    _wipe_path,
    cleanup_old_uploads,
)

# ---- _wipe_path -------------------------------------------------------------


def test_wipe_path_removes_existing_directory(tmp_path: Path) -> None:
    target = tmp_path / "extracts" / "abc"
    (target / "src").mkdir(parents=True)
    (target / "src" / "f.py").write_text("x = 1\n")

    _wipe_path(target)

    assert not target.exists()


def test_wipe_path_is_idempotent_on_missing_directory(tmp_path: Path) -> None:
    """Concurrent / never-extracted upload — missing path must be a no-op."""

    missing = tmp_path / "uploads" / "never-existed"

    _wipe_path(missing)  # should not raise


def test_wipe_path_propagates_oserror_on_permission_failure(tmp_path: Path) -> None:
    """A real IO failure must escape so the caller can record an error.

    We simulate by patching shutil.rmtree — actually chmod-ing in a tmp_path
    is racy under different OSes (mac vs linux ACL semantics).
    """

    target = tmp_path / "uploads" / "exists"
    target.mkdir(parents=True)

    with (
        patch("worker.tasks.cleanup.shutil.rmtree", side_effect=PermissionError("nope")),
        pytest.raises(PermissionError),
    ):
        _wipe_path(target)


# ---- cleanup_old_uploads disabled-by-default --------------------------------


def test_cleanup_no_op_when_retention_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """retention_days=None → DEBUG log, return zero counts, never touch DB."""

    monkeypatch.setattr(cfg.settings, "retention_days", None)

    fake_session_scope = MagicMock()
    monkeypatch.setattr(cleanup_module, "session_scope", fake_session_scope)

    result = cleanup_old_uploads()

    assert result == CleanupReport(swept=0, errors=0)
    fake_session_scope.assert_not_called()


# ---- cleanup_old_uploads with stubbed session -------------------------------


def _stub_upload(*, upload_id: UUID, extract_path: str | None = None) -> Any:
    """Build a stand-in for the Upload ORM row.

    We don't need real ORM behaviour — only the attributes the cleanup
    task reads (id, extract_path) and a sentinel identity for ``session.delete``.
    """

    upload = MagicMock()
    upload.id = upload_id
    upload.extract_path = extract_path
    return upload


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """Patch ``session_scope`` to yield a MagicMock session.

    The mock's ``__enter__`` returns the same session instance the test can
    introspect; ``commit``, ``delete``, ``get``, ``scalars`` are all
    individual MagicMocks so the test can drive them.
    """

    session = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = None
    monkeypatch.setattr(cleanup_module, "session_scope", lambda: cm)
    yield session


def test_cleanup_returns_zero_when_no_old_uploads(
    monkeypatch: pytest.MonkeyPatch,
    fake_session: MagicMock,
) -> None:
    monkeypatch.setattr(cfg.settings, "retention_days", 30)

    fake_session.scalars.return_value = []

    result = cleanup_old_uploads()

    assert result == CleanupReport(swept=0, errors=0)
    fake_session.delete.assert_not_called()
    fake_session.commit.assert_not_called()


def test_cleanup_sweeps_old_uploads_with_frozen_clock(
    monkeypatch: pytest.MonkeyPatch,
    fake_session: MagicMock,
    tmp_path: Path,
) -> None:
    """3 old upload ids are returned; cleanup iterates them and deletes each.

    Disk is set up so each upload has a backing dir, and we confirm the dirs
    are gone after the sweep.
    """

    monkeypatch.setattr(cfg.settings, "retention_days", 30)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)

    upload_ids = [uuid4(), uuid4(), uuid4()]
    extract_root = tmp_path / "extracts"
    for uid in upload_ids:
        (tmp_path / "uploads" / str(uid)).mkdir(parents=True)
        (tmp_path / "uploads" / str(uid) / "repo.zip").write_text("z")
        (extract_root / str(uid)).mkdir(parents=True)
        (extract_root / str(uid) / "f.py").write_text("x = 1\n")

    fake_session.scalars.return_value = upload_ids

    # session.get is called per-upload; return a stub for each.
    def _get(_model: Any, upload_id: UUID) -> Any:
        return _stub_upload(
            upload_id=upload_id,
            extract_path=str(extract_root / str(upload_id)),
        )

    fake_session.get.side_effect = _get

    with freeze_time("2026-05-09T12:00:00Z"):
        result = cleanup_old_uploads()

    assert result == CleanupReport(swept=3, errors=0)
    # Per-row commit; one commit per upload.
    assert fake_session.delete.call_count == 3
    assert fake_session.commit.call_count == 3
    # Disk artifacts are gone.
    for uid in upload_ids:
        assert not (tmp_path / "uploads" / str(uid)).exists()
        assert not (extract_root / str(uid)).exists()


def test_cleanup_records_disk_failures_per_row(
    monkeypatch: pytest.MonkeyPatch,
    fake_session: MagicMock,
    tmp_path: Path,
) -> None:
    """If ``_wipe_path`` blows up on one upload, that row stays + sweep continues.

    Two uploads queued; the first one's disk wipe raises; the second
    succeeds. Result should reflect 1 swept, 1 error, and only the second
    row should be ``session.delete``-d.
    """

    monkeypatch.setattr(cfg.settings, "retention_days", 30)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)

    bad_id, good_id = uuid4(), uuid4()
    (tmp_path / "uploads" / str(good_id)).mkdir(parents=True)
    fake_session.scalars.return_value = [bad_id, good_id]

    def _get(_model: Any, upload_id: UUID) -> Any:
        return _stub_upload(upload_id=upload_id, extract_path=None)

    fake_session.get.side_effect = _get

    real_wipe = cleanup_module._wipe_path

    def _flaky_wipe(path: Path) -> None:
        if str(bad_id) in str(path):
            raise OSError("simulated disk failure")
        real_wipe(path)

    monkeypatch.setattr(cleanup_module, "_wipe_path", _flaky_wipe)

    result = cleanup_old_uploads()

    assert result == CleanupReport(swept=1, errors=1)
    # Only the good upload was deleted from the DB; the bad one stays put.
    assert fake_session.delete.call_count == 1
    assert fake_session.commit.call_count == 1


def test_cleanup_treats_missing_row_as_already_swept(
    monkeypatch: pytest.MonkeyPatch,
    fake_session: MagicMock,
    tmp_path: Path,
) -> None:
    """Race with user-driven DELETE: ``session.get`` returns None → count as swept.

    Counting a vanished row as an error would inflate the error count with
    pure noise (concurrent deletion is the normal case, not a bug).
    """

    monkeypatch.setattr(cfg.settings, "retention_days", 30)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)

    fake_session.scalars.return_value = [uuid4()]
    fake_session.get.return_value = None  # row vanished between snapshot and re-fetch

    result = cleanup_old_uploads()

    assert result == CleanupReport(swept=1, errors=0)
    fake_session.delete.assert_not_called()


# ---- _delete_one direct -----------------------------------------------------


def test_delete_one_deletes_disk_then_db(tmp_path: Path) -> None:
    """Order matters: disk first, DB second. Verify disk is gone before delete."""

    upload_id = uuid4()
    raw = tmp_path / "uploads" / str(upload_id)
    raw.mkdir(parents=True)
    extract = tmp_path / "extracts" / str(upload_id)
    extract.mkdir(parents=True)

    session = MagicMock()
    session.get.return_value = _stub_upload(upload_id=upload_id, extract_path=str(extract))

    outcome = _delete_one(session, upload_id=upload_id, data_dir=tmp_path)

    assert outcome == _Outcome.SWEPT
    assert not raw.exists()
    assert not extract.exists()
    session.delete.assert_called_once()
    session.commit.assert_called_once()


# ---- Beat schedule registration ---------------------------------------------


def test_beat_schedule_registers_cleanup_task() -> None:
    """The Celery app must wire the cleanup task into ``beat_schedule`` so
    docker compose's embedded beat scheduler ticks it daily."""

    from worker.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "cleanup-old-uploads" in schedule
    entry = schedule["cleanup-old-uploads"]
    assert entry["task"] == "worker.tasks.cleanup.cleanup_old_uploads"
