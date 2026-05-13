"""Daily cleanup beat task — purges old uploads (T5.2).

Mirrors the per-upload tear-down shape from
``app.services.upload_service.UploadService.delete_upload``: wipe storage
artifacts (raw + extracted under ``uploads/<id>/``), then DB-delete the
row so the ``ON DELETE CASCADE`` FKs (PR #47) fan out through ``files``
→ ``scans`` → ``scan_files`` / ``scan_findings`` in one transaction.

Post-M2: the wipe goes through ``worker.storage.Storage.delete_prefix``
instead of ``shutil.rmtree`` so the same code path works against the
LocalStorage (dev / docker-compose) and GcsStorage (prod) backends.

The task is **disabled by default**: ``settings.retention_days is None`` →
no-op DEBUG log, return zero counts. Operators set ``RETENTION_DAYS=<N>`` to
enable. Beat ticks daily at 03:00 UTC regardless; a disabled tick is cheap.

Per-row resilience: if the storage wipe fails for one upload (transient
backend error, permissions, etc), we log a warning and **leave that row
in place** — better to keep DB and storage consistent for that one
upload than orphan a row whose backing files are still present. The
sweep continues with the next row.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.celery_app import celery_app
from worker.core.config import settings
from worker.core.db import session_scope
from worker.core.models import Upload
from worker.storage import Storage, get_storage, upload_prefix

logger = logging.getLogger(__name__)


class CleanupReport(TypedDict):
    """Summary returned to the Celery result backend.

    ``swept`` counts uploads whose row + storage artifacts were both removed.
    ``errors`` counts uploads we attempted but couldn't fully tear down
    (typically a storage wipe failure); those rows stay in place.
    """

    swept: int
    errors: int


# justify: celery's @task decorator has no mypy stubs; matches the pattern in
# worker/tasks/{ping,prepare_upload,run_scan}.py — local ignore, not project-wide.
@celery_app.task(name="worker.tasks.cleanup.cleanup_old_uploads")  # type: ignore[misc]
def cleanup_old_uploads() -> CleanupReport:
    """Sweep uploads whose ``created_at`` is older than ``retention_days``.

    Not bound (``bind=False`` is the decorator default) — Celery invokes us
    with no positional args, and unit tests call ``cleanup_old_uploads()``
    directly.
    """

    retention_days = settings.retention_days
    if retention_days is None:
        logger.debug("cleanup_old_uploads: retention disabled, skipping")
        return CleanupReport(swept=0, errors=0)

    cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
    logger.info(
        "cleanup_old_uploads: sweeping uploads older than %s (retention=%d days)",
        cutoff.isoformat(),
        retention_days,
    )

    storage = get_storage()
    swept = 0
    errors = 0
    with session_scope() as session:
        # Snapshot the ids first so we don't iterate a result set we're
        # mutating. ``Upload.id`` is the only column we need to drive the
        # subsequent per-row delete; the row itself is re-loaded inside the
        # per-upload helper.
        old_ids: list[UUID] = list(
            session.scalars(select(Upload.id).where(Upload.created_at < cutoff))
        )

        if not old_ids:
            logger.info("cleanup_old_uploads: 0 uploads matched the cutoff")
            return CleanupReport(swept=0, errors=0)

        for upload_id in old_ids:
            outcome = _delete_one(session, upload_id=upload_id, storage=storage)
            if outcome is _Outcome.SWEPT:
                swept += 1
            else:
                errors += 1

    logger.info(
        "cleanup_old_uploads: completed — swept=%d errors=%d (of %d candidates)",
        swept,
        errors,
        len(old_ids),
    )
    return CleanupReport(swept=swept, errors=errors)


# ---- Per-row tear-down ------------------------------------------------------


# Sentinel-style outcome enum so the caller can branch on a single value
# without unpacking tuples or importing a separate enum class.
class _Outcome:
    SWEPT = "swept"
    ERROR = "error"


def _delete_one(session: Session, *, upload_id: UUID, storage: Storage) -> str:
    """Tear down one upload (storage + DB). Returns SWEPT or ERROR.

    Order: storage first, then DB. The reverse would orphan rows whose
    backing files are gone (or vice-versa). On storage failure we leave
    the row alone and surface ERROR so the operator sees a non-zero
    error count.
    """

    # Re-fetch in case the row was deleted concurrently (e.g. user-driven
    # ``DELETE /uploads/{id}`` raced with the sweep). Treat a vanished row
    # as "swept by someone else" — counting it as an error would be noise.
    upload = session.get(Upload, upload_id)
    if upload is None:
        return _Outcome.SWEPT

    try:
        # A single ``delete_prefix`` over ``uploads/{id}/`` covers both
        # the raw upload artifacts and the worker-produced extract tree
        # (which also lives under that prefix per the M2 key
        # convention). Idempotent on both backends.
        storage.delete_prefix(upload_prefix(upload.id))
        # Pre-M2 rows persisted ``extract_path`` as an absolute filesystem
        # path under ``/data/extracts/<id>`` — outside the new
        # ``uploads/<id>/`` prefix, so the prefix-delete above misses it.
        # Wipe via filesystem so retention sweeps don't leak legacy data.
        # Codex P1 on M2.
        _wipe_legacy_extract_path(upload.extract_path)
    except Exception:
        # justify: storage failures are transient + opaque (transport
        # issues, IAM permission gaps); we don't want a single bad
        # upload to stop the sweep, so we catch any exception, record
        # an error, and continue to the next row.
        logger.warning(
            "cleanup_old_uploads: storage wipe failed for upload %s; leaving row intact",
            upload.id,
            exc_info=True,
        )
        # justify: SQLAlchemy's session may have a pending state for the row
        # we just touched; expunge so the next iteration starts clean.
        session.expunge(upload)
        return _Outcome.ERROR

    session.delete(upload)
    # Commit per-row so a later failure doesn't roll the whole sweep back.
    # The session_scope's outer commit is a no-op after this; the rollback-
    # on-exception still applies for any post-loop bookkeeping we add later.
    session.commit()
    return _Outcome.SWEPT


def _wipe_legacy_extract_path(extract_path: str | None) -> None:
    """Remove a pre-M2 absolute-path extract tree if present.

    Mirrors the api-side helper in ``apps/api/app/services/upload_service.py``.
    Pre-M2 ``prepare_upload`` extracted into ``/data/extracts/<id>/`` (a
    separate tree from the upload's raw zip), and persisted that absolute
    path to ``upload.extract_path``. Post-M2 ``delete_prefix("uploads/<id>/")``
    doesn't reach that legacy tree.
    """

    if not extract_path or not extract_path.startswith("/"):
        return
    shutil.rmtree(extract_path, ignore_errors=True)
