"""``prepare_upload`` Celery task.

Pulls an upload row by id, extracts its archive (or walks its loose files),
classifies every regular file per docs/FILE_HANDLING.md, bulk-inserts ``files``
rows, and transitions the upload from ``received`` → ``extracting`` →
``ready`` (or ``failed`` with a clear ``error`` message).

The API enqueues this task by name (``worker.tasks.prepare_upload.prepare_upload``);
keep the ``name=`` kwarg below in lock-step with
``apps/api/app/services/celery_client.py``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from uuid import UUID

from celery import Task
from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.celery_app import celery_app
from worker.core import db as worker_db
from worker.core.config import settings
from worker.core.models import (
    UPLOAD_KIND_LOOSE,
    UPLOAD_KIND_ZIP,
    UPLOAD_STATUS_EXTRACTING,
    UPLOAD_STATUS_FAILED,
    UPLOAD_STATUS_READY,
    File,
    Upload,
)
from worker.core.uuid7 import uuid7
from worker.files.classify import FileMeta, classify
from worker.files.safety import (
    SafetyError,
    inspect_archive,
    safe_extract,
)

logger = logging.getLogger(__name__)

LOOSE_SUBDIR = "loose"


# ---- Public task ------------------------------------------------------------


@celery_app.task(  # type: ignore[misc]
    bind=True,
    name="worker.tasks.prepare_upload.prepare_upload",
)
def prepare_upload(self: Task, upload_id: str) -> dict[str, int | str]:
    """Extract / walk / classify / persist for one upload.

    Args:
        upload_id: String form of the upload's UUID.

    Returns:
        A small dict (``status``, ``file_count``, ``scannable_count``)
        suitable for the celery result backend.

    Raises:
        Re-raises any exception that occurred so the broker records the
        failure. The DB row will already be set to ``failed`` with a
        human-readable ``error`` message before the raise.
    """

    del self  # unused; bound only for explicit naming in error traces
    parsed_id = UUID(upload_id)

    with worker_db.SessionMaker() as session:
        upload = session.scalar(select(Upload).where(Upload.id == parsed_id))
        if upload is None:
            logger.error("prepare_upload: upload %s not found", upload_id)
            raise LookupError(f"upload not found: {upload_id}")

        upload.status = UPLOAD_STATUS_EXTRACTING
        upload.error = None
        session.commit()

        extract_root = _extract_root_for(parsed_id)
        try:
            metas = _materialize(upload, extract_root)
        except SafetyError as exc:
            return _fail(session, upload, extract_root, str(exc))
        except Exception as exc:
            # justify: any unexpected error must still mark the upload failed
            # rather than leaving it stuck in ``extracting`` forever.
            logger.exception("prepare_upload: unexpected error for %s", upload_id)
            return _fail(session, upload, extract_root, f"unexpected error: {exc}")

        _persist(session, upload, extract_root, metas)
        session.commit()

        return {
            "status": upload.status,
            "file_count": upload.file_count,
            "scannable_count": upload.scannable_count,
        }


# ---- Pipeline steps ---------------------------------------------------------


def _materialize(upload: Upload, extract_root: Path) -> list[FileMeta]:
    """Run extraction (zip) or walk (loose) and classify the resulting files.

    Args:
        upload: The Upload row, already moved to ``extracting``.
        extract_root: Where extracted files should land for kind=zip; for
            kind=loose the existing ``loose/`` subdir is walked in place.

    Returns:
        A list of ``FileMeta`` for every regular file in the tree.
    """

    if upload.kind == UPLOAD_KIND_ZIP:
        _prepare_extract_dir(extract_root)
        inspect_archive(
            Path(upload.storage_path),
            max_files=settings.max_files_in_archive,
            max_dirs=settings.max_dirs_in_archive,
            max_total_uncompressed_bytes=settings.max_uncompressed_total_mb * 1024 * 1024,
            max_entry_uncompressed_bytes=settings.max_entry_uncompressed_mb * 1024 * 1024,
            max_compression_ratio=settings.max_compression_ratio,
        )
        safe_extract(Path(upload.storage_path), extract_root)
        return _walk_and_classify(extract_root)

    if upload.kind == UPLOAD_KIND_LOOSE:
        loose_dir = Path(upload.storage_path) / LOOSE_SUBDIR
        if not loose_dir.is_dir():
            raise SafetyError(f"loose upload missing {LOOSE_SUBDIR!r} directory")
        return _walk_and_classify(loose_dir)

    raise SafetyError(f"unknown upload kind: {upload.kind!r}")


def _walk_and_classify(root: Path) -> list[FileMeta]:
    """Walk ``root`` and classify every regular file.

    Symlinks are not followed and are not included in the materialized tree.
    """

    metas: list[FileMeta] = []
    resolved_root = root.resolve()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            logger.warning("skipping symlink under extract root: %s", path)
            continue
        if not path.is_file():
            continue
        # Re-resolve and guard — defense in depth even after extraction.
        if not path.resolve().is_relative_to(resolved_root):
            logger.warning("skipping path outside extract root: %s", path)
            continue
        metas.append(classify(path, resolved_root))
    return metas


def _persist(
    session: Session,
    upload: Upload,
    extract_root: Path,
    metas: list[FileMeta],
) -> None:
    """Insert one ``files`` row per meta and finalize the upload row."""

    for meta in metas:
        session.add(
            File(
                id=uuid7(),
                upload_id=upload.id,
                path=meta.path,
                name=meta.name,
                parent_path=meta.parent_path,
                size_bytes=meta.size_bytes,
                language=meta.language,
                is_binary=meta.is_binary,
                is_excluded_by_default=meta.is_excluded_by_default,
                excluded_reason=meta.excluded_reason,
                sha256=meta.sha256,
            )
        )

    upload.extract_path = str(extract_root)
    upload.file_count = len(metas)
    upload.scannable_count = sum(1 for m in metas if not m.is_excluded_by_default)
    upload.status = UPLOAD_STATUS_READY
    upload.error = None


def _fail(
    session: Session,
    upload: Upload,
    extract_root: Path,
    message: str,
) -> dict[str, int | str]:
    """Mark ``upload`` failed, clean up partials, commit, and re-raise."""

    logger.warning("prepare_upload failed for %s: %s", upload.id, message)
    session.rollback()
    # Reload after rollback so we update the persisted row, not the stale one.
    fresh = session.scalar(select(Upload).where(Upload.id == upload.id))
    if fresh is not None:
        fresh.status = UPLOAD_STATUS_FAILED
        fresh.error = message
        fresh.file_count = 0
        fresh.scannable_count = 0
        session.commit()

    if upload.kind == UPLOAD_KIND_ZIP:
        _cleanup_extract_dir(extract_root)

    raise SafetyError(message)


# ---- Filesystem helpers -----------------------------------------------------


def _extract_root_for(upload_id: UUID) -> Path:
    return settings.data_dir / "extracts" / str(upload_id)


def _prepare_extract_dir(path: Path) -> None:
    """Create a fresh, empty extract dir. Wipes any prior partial."""

    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _cleanup_extract_dir(path: Path) -> None:
    """Best-effort removal of partial extraction artifacts."""

    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError:
        # justify: cleanup is best-effort; logged so ops can sweep manually.
        logger.exception("failed to cleanup extract dir %s", path)
