"""``prepare_upload`` Celery task.

Pulls an upload row by id, extracts its archive (or walks its loose files),
classifies every regular file per docs/FILE_HANDLING.md, bulk-inserts ``files``
rows, and transitions the upload from ``received`` → ``extracting`` →
``ready`` (or ``failed`` with a clear ``error`` message).

The API enqueues this task by name (``worker.tasks.prepare_upload.prepare_upload``);
keep the ``name=`` kwarg below in lock-step with
``apps/api/app/services/celery_client.py``.

Post-M2 the task reads / writes / deletes through the ``Storage``
abstraction. The raw upload zip lives at ``uploads/<id>/raw.zip``; the
worker downloads it to a process-local temp file before handing it to
``zipfile`` (Python's zipfile insists on a seekable file or a real
path), runs the safety pre-flight, then ``safe_extract`` writes each
entry into ``uploads/<id>/extracted/<rel>``. Loose uploads are walked
in-place at ``uploads/<id>/loose/...``.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
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
from worker.files.classify import FileMeta, classify_bytes
from worker.files.safety import (
    SafetyError,
    inspect_archive,
    safe_extract,
)
from worker.storage import (
    Storage,
    extracted_prefix,
    get_storage,
    loose_prefix,
)
from worker.storage.local import LocalStorage

logger = logging.getLogger(__name__)


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
    storage = get_storage()

    with worker_db.SessionMaker() as session:
        upload = session.scalar(select(Upload).where(Upload.id == parsed_id))
        if upload is None:
            logger.error("prepare_upload: upload %s not found", upload_id)
            raise LookupError(f"upload not found: {upload_id}")

        upload.status = UPLOAD_STATUS_EXTRACTING
        upload.error = None
        session.commit()

        extract_root_key = _extract_root_for(parsed_id)
        # The whole pipeline (materialize → persist → commit) is wrapped so a
        # commit-time error (FK violation, deadlock, retry collision) cannot
        # leave the upload stuck in ``extracting``.
        try:
            materialized_path, metas = _materialize(upload, storage)
            _persist(session, upload, materialized_path, metas)
            session.commit()
        except SafetyError as exc:
            return _fail(session, upload, storage, extract_root_key, str(exc))
        except Exception as exc:
            # justify: any unexpected error must still mark the upload failed
            # rather than leaving it stuck in ``extracting`` forever.
            logger.exception("prepare_upload: unexpected error for %s", upload_id)
            return _fail(
                session,
                upload,
                storage,
                extract_root_key,
                f"unexpected error: {exc}",
            )

        return {
            "status": upload.status,
            "file_count": upload.file_count,
            "scannable_count": upload.scannable_count,
        }


# ---- Pipeline steps ---------------------------------------------------------


def _materialize(upload: Upload, storage: Storage) -> tuple[str, list[FileMeta]]:
    """Run extraction (zip) or walk (loose) and classify the resulting files.

    Args:
        upload: The Upload row, already moved to ``extracting``.
        storage: The configured Storage backend. Raw zip is read from
            ``upload.storage_path``; extracted files land under
            ``uploads/<id>/extracted/``; loose files are walked
            in-place under ``uploads/<id>/loose/``.

    Returns:
        A tuple of ``(extract_prefix, metas)`` where ``extract_prefix``
        is the storage prefix (forward-slash, no trailing slash) the meta
        paths are relative to — ``uploads/<id>/extracted`` for zip,
        ``uploads/<id>/loose`` for loose. Persisting the wrong prefix
        would break any downstream reader that joins
        ``upload.extract_path / file.path``.
    """

    upload_id = str(upload.id)
    if upload.kind == UPLOAD_KIND_ZIP:
        # Make sure no stale extracted artifacts from a previous failed
        # attempt linger before re-running.
        storage.delete_prefix(extracted_prefix(upload_id))
        with _local_zip_path(storage, upload.storage_path) as zip_path:
            inspect_archive(
                zip_path,
                max_files=settings.max_files_in_archive,
                max_dirs=settings.max_dirs_in_archive,
                max_total_uncompressed_bytes=settings.max_uncompressed_total_mb * 1024 * 1024,
                max_entry_uncompressed_bytes=settings.max_entry_uncompressed_mb * 1024 * 1024,
                max_compression_ratio=settings.max_compression_ratio,
                max_nesting_depth=settings.max_nesting_depth,
            )
            safe_extract(zip_path, storage=storage, upload_id=upload_id)
        prefix = extracted_prefix(upload_id).rstrip("/")
        return prefix, _walk_storage_and_classify(storage, prefix)

    if upload.kind == UPLOAD_KIND_LOOSE:
        loose_pref = loose_prefix(upload_id).rstrip("/")
        # Check there's at least one entry — historical contract was
        # "loose upload missing 'loose' directory" if the api never
        # wrote anything; keep the same shape so error messages don't
        # drift.
        keys = list(storage.iter_prefix(loose_pref + "/"))
        if not keys:
            raise SafetyError("loose upload has no files in storage")
        return loose_pref, _walk_storage_and_classify(storage, loose_pref)

    raise SafetyError(f"unknown upload kind: {upload.kind!r}")


def _walk_storage_and_classify(storage: Storage, prefix: str) -> list[FileMeta]:
    """Iterate every key under ``prefix`` and classify it.

    ``classify_bytes`` reads the bytes once into memory; the entry-size
    cap (``MAX_ENTRY_UNCOMPRESSED_MB``) bounds the per-file memory cost.
    Keys are sorted so the persisted ``files`` rows are deterministic
    across runs.
    """

    metas: list[FileMeta] = []
    prefix_with_slash = prefix.rstrip("/") + "/"
    for key in sorted(storage.iter_prefix(prefix_with_slash)):
        if not key.startswith(prefix_with_slash):
            # Defensive — list_blobs shouldn't return a key without the
            # prefix, but we guard so a renamed prefix doesn't smuggle
            # in unrelated files.
            logger.warning("skipping key outside extract prefix: %s", key)
            continue
        rel_path = key[len(prefix_with_slash) :]
        if not rel_path:
            continue
        data = storage.get_bytes(key)
        metas.append(classify_bytes(rel_path, data))
    return metas


def _persist(
    session: Session,
    upload: Upload,
    extract_prefix: str,
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

    upload.extract_path = extract_prefix
    upload.file_count = len(metas)
    upload.scannable_count = sum(1 for m in metas if not m.is_excluded_by_default)
    upload.status = UPLOAD_STATUS_READY
    upload.error = None


def _fail(
    session: Session,
    upload: Upload,
    storage: Storage,
    extract_prefix: str,
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
        # Best-effort: remove any partial extracted artifacts so the next
        # retry starts clean and so a half-written zip doesn't leave
        # bytes lingering past the upload's lifecycle.
        try:
            storage.delete_prefix(extract_prefix.rstrip("/") + "/")
        except Exception:
            logger.exception("failed to clean up extract prefix %s", extract_prefix)

    raise SafetyError(message)


# ---- Storage helpers --------------------------------------------------------


def _extract_root_for(upload_id: UUID) -> str:
    """Return the storage prefix for an upload's extracted tree.

    Post-M2 this is a storage key (no leading slash), not a Path. Kept
    as a named helper so tests can patch the location without
    string-formatting inline.
    """

    return extracted_prefix(upload_id).rstrip("/")


@contextmanager
def _local_zip_path(storage: Storage, storage_key: str) -> Iterator[Path]:
    """Yield a local filesystem path to the raw zip at ``storage_key``.

    For ``LocalStorage`` we hand back the existing on-disk path
    (``root / key``) — no copy, zero overhead. For any other backend
    (e.g. GcsStorage) we download to a process-local NamedTemporaryFile
    and yield that. The file is cleaned up on context exit either way.

    Why this matters: Python's ``zipfile`` insists on a seekable file
    handle. The GCS SDK returns bytes; wrapping them in a BytesIO works
    in-memory but ``zipfile`` then keeps the entire archive resident
    for the duration of extraction. A temp file lets the OS page-cache
    handle locality and matches the behavior the codebase had on
    LocalStorage.
    """

    if isinstance(storage, LocalStorage):
        # LocalStorage is the only backend where we can sidestep the
        # download. The Path is just ``root / key`` — no abstraction
        # break (we already imported LocalStorage explicitly to do this
        # narrowing).
        yield storage.root / storage_key
        return

    # Stream the blob into the temp file via ``shutil.copyfileobj`` so
    # the GCS SDK's chunked download keeps RSS bounded; pre-fix this
    # materialized the whole archive (up to 100 MiB) in Python heap
    # before flushing to disk, which doesn't compose with concurrent
    # prepare tasks. Codex P2 on M2.
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=True) as tmp:
        with storage.open_stream(storage_key) as src:
            shutil.copyfileobj(src, tmp, length=1024 * 1024)
        tmp.flush()
        yield Path(tmp.name)
