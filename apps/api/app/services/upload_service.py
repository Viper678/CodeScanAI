"""Business logic for the uploads endpoint.

Validates the inbound multipart payload, hands the bytes to the
configured ``Storage`` backend (local filesystem in dev /
docker-compose, GCS in prod), persists the row in status ``received``,
and enqueues ``prepare_upload`` on the Celery broker. Extraction itself
is handled by the worker (T2.2).

The storage abstraction (post-M2) means the api no longer touches
``settings.data_dir`` directly. Reads / writes / deletes flow through
``app.storage.Storage`` — see ``docs/GCP_MIGRATION.md`` §D2 and
``app/storage/base.py`` for the key conventions.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    InvalidUploadRequest,
    NotFound,
    PayloadTooLarge,
    QueueUnavailable,
    UnsupportedFileType,
)
from app.core.file_types import is_allowed_loose_extension
from app.core.uuid7 import uuid7
from app.models.upload import (
    UPLOAD_KIND_LOOSE,
    UPLOAD_KIND_ZIP,
    UPLOAD_STATUS_FAILED,
    UPLOAD_STATUS_READY,
    UPLOAD_STATUS_RECEIVED,
    Upload,
)
from app.repositories.file_repo import FileRepo
from app.repositories.upload_repo import UploadRepo
from app.schemas.upload import TreeFile, TreeResponse, UploadStatus
from app.services.celery_client import enqueue_prepare_upload
from app.storage import (
    Storage,
    get_storage,
    loose_key,
    raw_zip_key,
    upload_prefix,
)

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1 MiB stream window
ZIP_MAGIC = b"PK\x03\x04"
ZIP_EMPTY_MAGIC = b"PK\x05\x06"
# Threshold past which ``SpooledTemporaryFile`` spills the in-memory buffer
# to a real on-disk temp file. 4 MiB keeps small uploads (most config /
# loose-file payloads) entirely in RAM while bounding peak RSS for any
# upload up to ``max_upload_size_mb`` (default 100 MiB).
_UPLOAD_SPOOL_THRESHOLD = 4 * 1024 * 1024


class UploadFileLike(Protocol):
    """The subset of FastAPI's UploadFile we depend on.

    Declared as a Protocol so the service stays free of FastAPI imports
    (per docs/CONTRIBUTING.md §services).
    """

    filename: str | None
    content_type: str | None

    async def read(self, size: int = -1) -> bytes: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class _StoredFile:
    """Result of streaming one part to disk."""

    original_name: str
    size_bytes: int


class UploadEnqueuer(Protocol):
    """Indirection so tests can replace the broker call without monkey-patching."""

    def __call__(self, upload_id: UUID) -> None: ...


class UploadService:
    """Orchestrates validation, persistence, and enqueue."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        enqueuer: UploadEnqueuer | None = None,
        storage: Storage | None = None,
    ) -> None:
        self.session = session
        self.uploads = UploadRepo(session)
        self.files = FileRepo(session)
        self._enqueue = enqueuer or enqueue_prepare_upload
        # Resolve at construction so a swap of STORAGE_BACKEND via
        # process restart is honored, and so tests can inject a fake.
        self._storage = storage if storage is not None else get_storage()

    async def get_tree(self, *, upload_id: UUID, user_id: UUID) -> TreeResponse:
        """Return the materialized file tree for an upload.

        Raises ``NotFound`` when the upload doesn't exist or belongs to
        someone else (the API never distinguishes the two — see
        docs/SECURITY.md §3 and the AC for T2.3). When the upload is still
        being processed (``received`` / ``extracting``) or has failed,
        returns an empty ``files`` list with the current ``status`` echoed
        so the frontend can poll without a second call to ``GET /uploads/{id}``.
        """

        upload = await self.uploads.get_by_id(upload_id, user_id=user_id)
        if upload is None:
            raise NotFound("Upload not found")

        root_name = _derive_root_name(upload)
        status_literal = cast(UploadStatus, upload.status)
        if upload.status != UPLOAD_STATUS_READY:
            return TreeResponse(
                upload_id=upload.id,
                root_name=root_name,
                status=status_literal,
                files=[],
            )

        rows = await self.files.list_for_upload(upload_id=upload.id, user_id=user_id)
        return TreeResponse(
            upload_id=upload.id,
            root_name=root_name,
            status=status_literal,
            files=[TreeFile.model_validate(row) for row in rows],
        )

    async def create_zip_upload(
        self,
        *,
        user_id: UUID,
        upload_file: UploadFileLike,
    ) -> Upload:
        max_bytes = settings.max_upload_size_mb * 1024 * 1024
        if not _zip_content_type_ok(upload_file.content_type):
            raise UnsupportedFileType("Expected a .zip archive")
        original_name = _safe_basename(upload_file.filename)
        if not original_name.lower().endswith(".zip"):
            raise UnsupportedFileType("Expected a .zip archive")

        upload_id = uuid7()
        storage_path = raw_zip_key(upload_id)
        try:
            stored = await _stream_to_storage(
                upload_file,
                storage=self._storage,
                key=storage_path,
                max_bytes=max_bytes,
                original_name=original_name,
            )
        except PayloadTooLarge:
            self._storage.delete_prefix(upload_prefix(upload_id))
            raise

        if not _has_zip_magic_in_storage(self._storage, storage_path):
            self._storage.delete_prefix(upload_prefix(upload_id))
            raise UnsupportedFileType("File is not a valid .zip archive")

        upload = await self.uploads.create(
            upload_id=upload_id,
            user_id=user_id,
            original_name=original_name,
            kind=UPLOAD_KIND_ZIP,
            size_bytes=stored.size_bytes,
            storage_path=storage_path,
            status=UPLOAD_STATUS_RECEIVED,
        )
        await self.session.commit()
        await self.session.refresh(upload)
        await self._enqueue_or_mark_failed(upload)
        return upload

    async def create_loose_upload(
        self,
        *,
        user_id: UUID,
        upload_files: list[UploadFileLike],
    ) -> Upload:
        if not upload_files:
            raise InvalidUploadRequest("At least one file is required")
        if len(upload_files) > settings.max_loose_files:
            raise InvalidUploadRequest(
                f"Too many files (max {settings.max_loose_files} per upload)"
            )

        max_bytes_per_file = settings.max_loose_file_size_mb * 1024 * 1024
        upload_id = uuid7()

        # Validate every name first so we don't write any bytes for a doomed
        # request. The disk stream below still re-checks size.
        names: list[str] = []
        for part in upload_files:
            base = _safe_basename(part.filename)
            if not is_allowed_loose_extension(base):
                self._storage.delete_prefix(upload_prefix(upload_id))
                raise UnsupportedFileType(f"File type not allowed: {base}")
            names.append(base)

        if len({name.lower() for name in names}) != len(names):
            self._storage.delete_prefix(upload_prefix(upload_id))
            raise InvalidUploadRequest("Duplicate filenames are not allowed")

        total_bytes = 0
        try:
            for part, name in zip(upload_files, names, strict=True):
                stored = await _stream_to_storage(
                    part,
                    storage=self._storage,
                    key=loose_key(upload_id, name),
                    max_bytes=max_bytes_per_file,
                    original_name=name,
                )
                total_bytes += stored.size_bytes
        except PayloadTooLarge:
            self._storage.delete_prefix(upload_prefix(upload_id))
            raise

        # The "original_name" of a multi-file loose upload is the synthetic root
        # the worker will produce. For a single-file upload we keep its name so
        # the UI can display something meaningful.
        original_name = names[0] if len(names) == 1 else f"loose-{upload_id}"

        # The upload's storage_path is the upload-level prefix — the worker
        # walks it to locate every loose file. Stored as a key (forward
        # slashes, no leading slash) so it round-trips through Storage on
        # both local and GCS backends.
        upload = await self.uploads.create(
            upload_id=upload_id,
            user_id=user_id,
            original_name=original_name,
            kind=UPLOAD_KIND_LOOSE,
            size_bytes=total_bytes,
            storage_path=upload_prefix(upload_id).rstrip("/"),
            status=UPLOAD_STATUS_RECEIVED,
        )
        await self.session.commit()
        await self.session.refresh(upload)
        await self._enqueue_or_mark_failed(upload)
        return upload

    async def delete_upload(self, *, upload_id: UUID, user_id: UUID) -> None:
        """Permanently delete an upload + every byte of user code we hold.

        Wipes the storage artifacts (raw + extracted under
        ``uploads/<id>/`` in whatever backend is configured) before
        deleting the ``uploads`` row. The DB cascade then fans out
        through ``files`` → ``scans`` → ``scan_files`` → ``scan_findings``
        so a single call leaves no trace of the upload — that's the
        contract advertised in ``docs/API.md`` §Uploads and what
        data-retention-conscious customers rely on.

        Order matters: storage wipe first, DB delete second. If the wipe
        fails we surface a 500 with the row intact, so the caller can
        safely retry. The reverse order would orphan rows whose backing
        files are already gone (or vice-versa) — both are worse than a
        single visible failure.

        Raises:
            NotFound: when the upload doesn't exist or belongs to another
                user — same no-enumeration rule as ``GET /uploads/{id}``.
        """

        upload = await self.uploads.get_by_id(upload_id, user_id=user_id)
        if upload is None:
            raise NotFound("Upload not found")

        self._wipe_upload_artifacts(upload)
        await self.session.delete(upload)
        await self.session.commit()

    def _wipe_upload_artifacts(self, upload: Upload) -> None:
        """Remove all storage artifacts for ``upload``.

        A single ``delete_prefix`` over ``uploads/{id}/`` covers both the
        raw upload artifacts and the worker-produced extract tree (which
        also lives under that prefix per the M2 key convention). Idempotent
        — missing keys are a no-op on both backends.

        Pre-M2 rows persist absolute filesystem paths in ``storage_path``
        (the raw upload, e.g. ``/data/uploads/<id>/<filename>.zip``) and
        ``extract_path`` (the extract tree, e.g. ``/data/extracts/<id>``).
        Both legacy shapes get wiped here so deleting a pre-M2 row leaves
        no files behind even if the operator has flipped
        ``STORAGE_BACKEND`` to ``gcs``. Codex P2 on M2.
        """

        self._storage.delete_prefix(upload_prefix(upload.id))
        _wipe_legacy_storage_path(upload.storage_path)
        _wipe_legacy_extract_path(upload.extract_path)

    async def _enqueue_or_mark_failed(self, upload: Upload) -> None:
        # If the broker is down, _enqueue raises before the worker ever sees the
        # upload. Without this guard the row sits in `received` forever and
        # clients retry, producing orphans. Reflect reality in the DB and surface
        # a 503 the client can react to. (T5.2 cleanup is age-based and won't
        # rescue a stuck row in the meantime.)
        # justify: kombu/redis raise unrelated types; catch any broker failure.
        try:
            self._enqueue(upload.id)
        except Exception:
            logger.exception(
                "failed to enqueue prepare_upload for upload %s; marking failed",
                upload.id,
            )
            upload.status = UPLOAD_STATUS_FAILED
            upload.error = "queue_unavailable"
            await self.session.commit()
            raise QueueUnavailable() from None


def _derive_root_name(upload: Upload) -> str:
    """Pick a human label for the tree root.

    For zips we strip the trailing ``.zip`` so the UI shows "myrepo" instead
    of "myrepo.zip". For loose uploads we pass the original name through
    unchanged — single-file uploads keep their filename, multi-file uploads
    already carry the synthetic ``loose-<uuid>`` label produced at upload
    time. The frontend doesn't depend on either form being canonical.
    """

    name = upload.original_name
    if upload.kind == UPLOAD_KIND_ZIP and name.lower().endswith(".zip"):
        return name[: -len(".zip")]
    return name


def _zip_content_type_ok(content_type: str | None) -> bool:
    if content_type is None:
        return True  # some clients omit the header; we still magic-check on disk
    allowed = {
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
        "multipart/x-zip",
    }
    # Strip parameters like '; charset=...'
    primary = content_type.split(";", 1)[0].strip().lower()
    return primary in allowed


def _safe_basename(name: str | None) -> str:
    """Return a safe basename or raise InvalidUploadRequest.

    Rejects anything that smells like a path traversal attempt; the caller is
    responsible for whitelisting the *type*.
    """

    if not name:
        raise InvalidUploadRequest("Missing filename")
    if "\x00" in name or "/" in name or "\\" in name:
        raise InvalidUploadRequest("Filename contains forbidden characters")
    base = os.path.basename(name)
    if base in {"", ".", ".."}:
        raise InvalidUploadRequest("Invalid filename")
    if base != name:
        # Defense in depth — basename() differs from input means there was a
        # path component, even after the slash check above.
        raise InvalidUploadRequest("Filename must not contain a path")
    return base


async def _read_chunks(upload_file: UploadFileLike) -> AsyncIterator[bytes]:
    while True:
        chunk = await upload_file.read(CHUNK_SIZE)
        if not chunk:
            return
        yield chunk


async def _stream_to_storage(
    upload_file: UploadFileLike,
    *,
    storage: Storage,
    key: str,
    max_bytes: int,
    original_name: str,
) -> _StoredFile:
    """Stream ``upload_file`` to ``storage[key]`` aborting after ``max_bytes``.

    Bytes are spooled to a ``SpooledTemporaryFile`` (in-memory for small
    uploads, on-disk past ``_UPLOAD_SPOOL_THRESHOLD``) and shipped to
    storage via a single ``put_stream`` call. Pre-M2 the upload service
    streamed chunk-by-chunk straight to disk via ``os.open``; post-M2 we
    keep the bounded peak-RSS guarantee by spooling rather than building
    a Python list of chunks + ``b"".join`` (which would peak at ~2x
    payload size and risk OOM under concurrent 100 MiB uploads). The GCS
    impl reads the spool to ship the blob; LocalStorage just copies the
    bytes through. Codex P2 on M2.

    On size violation no bytes land in storage — we abort before the
    put_stream call.
    """

    written = 0
    with tempfile.SpooledTemporaryFile(max_size=_UPLOAD_SPOOL_THRESHOLD, mode="w+b") as spool:
        try:
            async for chunk in _read_chunks(upload_file):
                written += len(chunk)
                if written > max_bytes:
                    raise PayloadTooLarge(
                        f"{original_name} exceeds the maximum size of {max_bytes} bytes"
                    )
                spool.write(chunk)
        finally:
            await upload_file.close()
        spool.seek(0)
        storage.put_stream(key, cast(BinaryIO, spool))
    return _StoredFile(original_name=original_name, size_bytes=written)


def _wipe_legacy_storage_path(storage_path: str | None) -> None:
    """Remove a pre-M2 absolute-path raw-upload artifact if present.

    Pre-M2 the raw archive lived at ``/data/uploads/<id>/<filename>``
    (file shape) or, for some intermediate layouts, ``/data/uploads/<id>``
    (directory shape). Post-M2 ``storage_path`` carries the storage key
    prefix ``uploads/<id>`` instead. Detect legacy via absolute-path
    shape and unlink (file) or rmtree (dir). Codex P2 on M2.

    Caution: NEVER walk to a parent — Path("/data/uploads/<id>").parent
    is ``/data/uploads`` which contains every upload. Stay scoped to
    the value the row holds.
    """

    if not storage_path or not storage_path.startswith("/"):
        return
    path = Path(storage_path)
    with contextlib.suppress(FileNotFoundError):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _wipe_legacy_extract_path(extract_path: str | None) -> None:
    """Remove a pre-M2 absolute-path extract tree if present.

    Pre-M2 prepare_upload extracted into ``/data/extracts/<id>/`` (a
    separate tree from the upload's raw zip), and persisted that absolute
    path to ``upload.extract_path``. Post-M2 the column carries a storage
    key prefix (e.g. ``uploads/<id>/extracted``) and the new tree lives
    under ``uploads/<id>/`` — so the M2 ``delete_prefix`` doesn't reach
    the legacy tree. Detect legacy by absolute-path shape and wipe via
    filesystem ops so deleting a pre-M2 row doesn't leak files. Codex
    P1 on M2.

    Note on error handling: we used to pass ``ignore_errors=True`` here,
    but that masks permission / I/O failures and lets the caller commit
    the DB delete while files remain on disk. Surface real errors so
    the caller's transaction unwinds and the row sticks around for a
    retry; only no-op on FileNotFoundError (the tree was already gone).
    Codex P2 on M2.
    """

    if not extract_path or not extract_path.startswith("/"):
        return
    # Idempotent: a concurrent retention sweep may have already removed
    # the legacy tree. Any other rmtree failure (permissions, I/O) is
    # propagated so the caller's transaction unwinds.
    with contextlib.suppress(FileNotFoundError):
        shutil.rmtree(extract_path)


def _has_zip_magic_in_storage(storage: Storage, key: str) -> bool:
    """Return True iff the first bytes of ``storage[key]`` look like a zip."""

    # Read the full object — it's already bounded by the upload size cap,
    # and a 4-byte range request is more complex than warranted here.
    # Storage backends differ on partial-read support; reading the whole
    # blob keeps the abstraction thin. The cap above guarantees this is
    # safe.
    data = storage.get_bytes(key)
    header = data[:4]
    return header in {ZIP_MAGIC, ZIP_EMPTY_MAGIC}
