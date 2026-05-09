"""Daily cleanup beat task — purges old uploads (T5.2).

Mirrors the per-upload tear-down shape from
``app.services.upload_service.UploadService.delete_upload``: wipe disk
artifacts (raw upload tree + extract tree), then DB-delete the row so the
``ON DELETE CASCADE`` FKs (PR #47) fan out through ``files`` → ``scans`` →
``scan_files`` / ``scan_findings`` in one transaction.

The task is **disabled by default**: ``settings.retention_days is None`` →
no-op DEBUG log, return zero counts. Operators set ``RETENTION_DAYS=<N>`` to
enable. Beat ticks daily at 03:00 UTC regardless; a disabled tick is cheap.

Per-row resilience: if the disk wipe fails for one upload (permission error,
filesystem outage, etc), we log a warning and **leave that row in place** —
better to keep DB and disk consistent for that one upload than orphan a row
whose backing files are still on disk. The sweep continues with the next row.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.celery_app import celery_app
from worker.core.config import settings
from worker.core.db import session_scope
from worker.core.models import Upload

logger = logging.getLogger(__name__)


class CleanupReport(TypedDict):
    """Summary returned to the Celery result backend.

    ``swept`` counts uploads whose row + disk artifacts were both removed.
    ``errors`` counts uploads we attempted but couldn't fully tear down
    (typically a disk wipe failure); those rows stay in place.
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
            outcome = _delete_one(session, upload_id=upload_id, data_dir=settings.data_dir)
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


def _delete_one(session: Session, *, upload_id: UUID, data_dir: Path) -> str:
    """Tear down one upload (disk + DB). Returns SWEPT or ERROR.

    Order: disk first, then DB. The reverse would orphan rows whose backing
    files are gone (or vice-versa). On disk failure we leave the row alone
    and surface ERROR so the operator sees a non-zero error count.
    """

    # Re-fetch in case the row was deleted concurrently (e.g. user-driven
    # ``DELETE /uploads/{id}`` raced with the sweep). Treat a vanished row
    # as "swept by someone else" — counting it as an error would be noise.
    upload = session.get(Upload, upload_id)
    if upload is None:
        return _Outcome.SWEPT

    raw_dir = data_dir / "uploads" / str(upload.id)
    extract_dir = Path(upload.extract_path) if upload.extract_path else None

    try:
        _wipe_path(raw_dir)
        if extract_dir is not None:
            _wipe_path(extract_dir)
    except OSError:
        logger.warning(
            "cleanup_old_uploads: disk wipe failed for upload %s; leaving row intact",
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


def _wipe_path(path: Path) -> None:
    """Recursively remove ``path``; idempotent on missing entries.

    Mirrors ``app.services.upload_service._wipe_path`` deliberately — same
    semantics so disk artifacts produced by the api delete flow and the
    worker cleanup flow look identical to anyone reading either path. A
    missing directory is a no-op (concurrent cleanup or never-extracted
    upload), but a permission/IO error escapes to the caller.
    """

    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        # Race with another cleanup pass — treat as success.
        return
