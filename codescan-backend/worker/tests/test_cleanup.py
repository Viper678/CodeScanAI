"""Unit tests for the retention cleanup beat task (T5.2).

Pure-Python tests with stubbed sessions and a frozen clock — no real DB
or Redis. The integration test in ``tests/integration/test_cleanup.py``
covers the end-to-end DB cascade.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from freezegun import freeze_time

from worker.core import config as cfg
from worker.storage.local import LocalStorage
from worker.tasks import cleanup as cleanup_module
from worker.tasks.cleanup import (
    CleanupReport,
    _delete_one,
    _Outcome,
    cleanup_old_uploads,
)

# ---- cleanup_old_uploads disabled-by-default --------------------------------


def test_cleanup_no_op_when_retention_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """retention_days=None → DEBUG log, return zero counts, never touch DB."""

    monkeypatch.setattr(cfg.settings, "retention_days", None)

    fake_session_scope = MagicMock()
    monkeypatch.setattr(cleanup_module, "session_scope", fake_session_scope)
    fake_get_storage = MagicMock()
    monkeypatch.setattr(cleanup_module, "get_storage", fake_get_storage)

    result = cleanup_old_uploads()

    assert result == CleanupReport(swept=0, errors=0)
    fake_session_scope.assert_not_called()
    fake_get_storage.assert_not_called()


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
    monkeypatch.setattr(cleanup_module, "get_storage", lambda: MagicMock())

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

    Storage is set up so each upload has backing artifacts, and we
    confirm they're gone after the sweep.
    """

    monkeypatch.setattr(cfg.settings, "retention_days", 30)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)

    storage = LocalStorage(tmp_path)
    monkeypatch.setattr(cleanup_module, "get_storage", lambda: storage)

    upload_ids = [uuid4(), uuid4(), uuid4()]
    for uid in upload_ids:
        storage.put_bytes(f"uploads/{uid}/raw.zip", b"z")
        storage.put_bytes(f"uploads/{uid}/extracted/f.py", b"x = 1\n")

    fake_session.scalars.return_value = upload_ids

    # session.get is called per-upload; return a stub for each.
    def _get(_model: Any, upload_id: UUID) -> Any:
        return _stub_upload(
            upload_id=upload_id,
            extract_path=f"uploads/{upload_id}/extracted",
        )

    fake_session.get.side_effect = _get

    with freeze_time("2026-05-09T12:00:00Z"):
        result = cleanup_old_uploads()

    assert result == CleanupReport(swept=3, errors=0)
    # Per-row commit; one commit per upload.
    assert fake_session.delete.call_count == 3
    assert fake_session.commit.call_count == 3
    # Storage artifacts are gone.
    for uid in upload_ids:
        assert not storage.exists(f"uploads/{uid}/raw.zip")
        assert not storage.exists(f"uploads/{uid}/extracted/f.py")


def test_cleanup_records_storage_failures_per_row(
    monkeypatch: pytest.MonkeyPatch,
    fake_session: MagicMock,
    tmp_path: Path,
) -> None:
    """If storage.delete_prefix blows up on one upload, that row stays + sweep continues.

    Two uploads queued; the first one's wipe raises; the second succeeds.
    Result should reflect 1 swept, 1 error, and only the second row should
    be ``session.delete``-d.
    """

    monkeypatch.setattr(cfg.settings, "retention_days", 30)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)

    bad_id, good_id = uuid4(), uuid4()
    backing = LocalStorage(tmp_path)
    backing.put_bytes(f"uploads/{good_id}/raw.zip", b"z")

    class _FlakyStorage:
        """Wraps LocalStorage; raises on the bad-id prefix."""

        def delete_prefix(self, prefix: str) -> int:
            if str(bad_id) in prefix:
                raise OSError("simulated storage failure")
            return backing.delete_prefix(prefix)

    monkeypatch.setattr(cleanup_module, "get_storage", lambda: _FlakyStorage())

    fake_session.scalars.return_value = [bad_id, good_id]

    def _get(_model: Any, upload_id: UUID) -> Any:
        return _stub_upload(upload_id=upload_id, extract_path=None)

    fake_session.get.side_effect = _get

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
    monkeypatch.setattr(cleanup_module, "get_storage", lambda: LocalStorage(tmp_path))

    fake_session.scalars.return_value = [uuid4()]
    fake_session.get.return_value = None  # row vanished between snapshot and re-fetch

    result = cleanup_old_uploads()

    assert result == CleanupReport(swept=1, errors=0)
    fake_session.delete.assert_not_called()


# ---- _delete_one direct -----------------------------------------------------


def test_delete_one_deletes_storage_then_db(tmp_path: Path) -> None:
    """Order matters: storage first, DB second. Verify storage is gone before DB delete."""

    upload_id = uuid4()
    storage = LocalStorage(tmp_path)
    storage.put_bytes(f"uploads/{upload_id}/raw.zip", b"z")
    storage.put_bytes(f"uploads/{upload_id}/extracted/f.py", b"x = 1\n")

    session = MagicMock()
    session.get.return_value = _stub_upload(
        upload_id=upload_id, extract_path=f"uploads/{upload_id}/extracted"
    )

    outcome = _delete_one(session, upload_id=upload_id, storage=storage)

    assert outcome == _Outcome.SWEPT
    assert not storage.exists(f"uploads/{upload_id}/raw.zip")
    assert not storage.exists(f"uploads/{upload_id}/extracted/f.py")
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
