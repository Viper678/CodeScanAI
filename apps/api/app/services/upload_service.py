"""Business logic for the uploads endpoint.

Validates the inbound multipart payload, streams to disk under
``settings.data_dir / "uploads" / <upload_id>``, persists the row in
status ``received``, and enqueues ``prepare_upload`` on the Celery broker.
Extraction itself is handled by the worker (T2.2).
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    InvalidUploadRequest,
    PayloadTooLarge,
    UnsupportedFileType,
)
from app.core.file_types import is_allowed_loose_extension
from app.core.uuid7 import uuid7
from app.models.upload import (
    UPLOAD_KIND_LOOSE,
    UPLOAD_KIND_ZIP,
    UPLOAD_STATUS_RECEIVED,
    Upload,
)
from app.repositories.upload_repo import UploadRepo
from app.services.celery_client import enqueue_prepare_upload

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1 MiB stream window
ZIP_MAGIC = b"PK\x03\x04"
ZIP_EMPTY_MAGIC = b"PK\x05\x06"
LOOSE_SUBDIR = "loose"


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
        data_dir: Path | None = None,
    ) -> None:
        self.session = session
        self.uploads = UploadRepo(session)
        self._enqueue = enqueuer or enqueue_prepare_upload
        self._data_dir = data_dir or settings.data_dir

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
        upload_dir = self._upload_dir(upload_id)
        target_path = upload_dir / original_name
        try:
            stored = await _stream_to_disk(
                upload_file,
                target_path,
                max_bytes=max_bytes,
                original_name=original_name,
            )
        except PayloadTooLarge:
            _safe_cleanup(upload_dir)
            raise

        if not _has_zip_magic(target_path):
            _safe_cleanup(upload_dir)
            raise UnsupportedFileType("File is not a valid .zip archive")

        upload = await self.uploads.create(
            upload_id=upload_id,
            user_id=user_id,
            original_name=original_name,
            kind=UPLOAD_KIND_ZIP,
            size_bytes=stored.size_bytes,
            storage_path=str(target_path),
            status=UPLOAD_STATUS_RECEIVED,
        )
        await self.session.commit()
        await self.session.refresh(upload)
        self._enqueue(upload.id)
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
        upload_dir = self._upload_dir(upload_id)
        loose_dir = upload_dir / LOOSE_SUBDIR

        # Validate every name first so we don't write any bytes for a doomed
        # request. The disk stream below still re-checks size.
        names: list[str] = []
        for part in upload_files:
            base = _safe_basename(part.filename)
            if not is_allowed_loose_extension(base):
                _safe_cleanup(upload_dir)
                raise UnsupportedFileType(f"File type not allowed: {base}")
            names.append(base)

        if len({name.lower() for name in names}) != len(names):
            _safe_cleanup(upload_dir)
            raise InvalidUploadRequest("Duplicate filenames are not allowed")

        total_bytes = 0
        try:
            for part, name in zip(upload_files, names, strict=True):
                stored = await _stream_to_disk(
                    part,
                    loose_dir / name,
                    max_bytes=max_bytes_per_file,
                    original_name=name,
                )
                total_bytes += stored.size_bytes
        except PayloadTooLarge:
            _safe_cleanup(upload_dir)
            raise

        # The "original_name" of a multi-file loose upload is the synthetic root
        # the worker will produce. For a single-file upload we keep its name so
        # the UI can display something meaningful.
        original_name = names[0] if len(names) == 1 else f"loose-{upload_id}"

        upload = await self.uploads.create(
            upload_id=upload_id,
            user_id=user_id,
            original_name=original_name,
            kind=UPLOAD_KIND_LOOSE,
            size_bytes=total_bytes,
            storage_path=str(upload_dir),
            status=UPLOAD_STATUS_RECEIVED,
        )
        await self.session.commit()
        await self.session.refresh(upload)
        self._enqueue(upload.id)
        return upload

    def _upload_dir(self, upload_id: UUID) -> Path:
        return self._data_dir / "uploads" / str(upload_id)


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


async def _stream_to_disk(
    upload_file: UploadFileLike,
    target: Path,
    *,
    max_bytes: int,
    original_name: str,
) -> _StoredFile:
    """Stream ``upload_file`` to ``target`` aborting after ``max_bytes``.

    The directory is created on demand. On size violation the partial file is
    removed before raising.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    # Open in exclusive mode so we never silently overwrite a previous stream;
    # a UUIDv7 collision would be the only way to hit this branch.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in _read_chunks(upload_file):
                written += len(chunk)
                if written > max_bytes:
                    fh.close()
                    target.unlink(missing_ok=True)
                    raise PayloadTooLarge(
                        f"{original_name} exceeds the maximum size of {max_bytes} bytes"
                    )
                fh.write(chunk)
    finally:
        await upload_file.close()
    return _StoredFile(original_name=original_name, size_bytes=written)


def _has_zip_magic(path: Path) -> bool:
    """Return True iff the first bytes look like a zip file."""

    with path.open("rb") as fh:
        header = fh.read(4)
    return header in {ZIP_MAGIC, ZIP_EMPTY_MAGIC}


def _safe_cleanup(path: Path) -> None:
    """Remove a directory tree, ignoring errors. Used on validation failure."""

    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError:
        # Cleanup is best-effort — the alternative is leaking partials on disk.
        logger.exception("failed to clean up upload directory %s", path)
