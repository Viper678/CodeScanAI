"""Storage reads for the file viewer endpoint (T4.3).

``GET /uploads/{upload_id}/files/{file_id}/content`` is intentionally a
small endpoint, but it touches the storage backend and so deserves the
same service layer as the rest of the codebase — keeps the router thin
and gives us a clean unit of test surface for the size + binary checks.

Post-M2 the reads flow through ``app.storage.Storage`` instead of the
filesystem directly. The 2 MiB per-file cap is small enough that we
load the bytes into memory in one go rather than stream — the GCS impl
has no real streaming surface, and a bounded in-memory buffer is fine
for the 2 MiB ceiling. ``StreamingResponse`` is kept on the router side
because the response body still benefits from chunked transfer to the
browser (Content-Length set, body yielded in 64 KiB windows).

Path-safety note: ``files.path`` is DB-controlled (worker-extracted from
the archive after the path-traversal guard in
``docs/FILE_HANDLING.md`` §"Zip extraction safety"), not user input. We
still re-run the entry-name normalization here as defense-in-depth — a
future ingestion bug shouldn't become a directory traversal here.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound, PayloadTooLarge, UnsupportedFileType
from app.repositories.file_repo import FileRepo
from app.repositories.upload_repo import UploadRepo
from app.storage import Storage, StorageKeyError, extracted_key, get_storage

logger = logging.getLogger(__name__)

# 64 KiB streaming window for the response body. Big enough to amortize
# the per-chunk overhead, small enough that a few concurrent viewer
# requests don't balloon RSS.
CHUNK_SIZE = 64 * 1024
# First-N bytes we sniff for the binary heuristic. Mirrors the worker's
# binary-detection window in ``docs/FILE_HANDLING.md`` §"Binary detection"
# (NUL byte + non-text-byte ratio). The viewer only checks NUL bytes —
# we don't need to be as nuanced as classification because we just need
# to refuse files that would render as garbage in CodeMirror.
BINARY_SNIFF_BYTES = 8 * 1024


@dataclass(frozen=True)
class FileContent:
    """Result of a successful content lookup.

    The router consumes ``stream`` as the body of a ``StreamingResponse``
    and uses ``size_bytes`` to populate ``Content-Length``. ``key`` is
    exposed for logging / debug — never echo it to a client.
    """

    stream: AsyncIterator[bytes]
    size_bytes: int
    key: str


class FileContentService:
    """Lookup + read for the file viewer endpoint."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        max_size_bytes: int,
        storage: Storage | None = None,
    ) -> None:
        self.session = session
        self.uploads = UploadRepo(session)
        self.files = FileRepo(session)
        self.max_size_bytes = max_size_bytes
        self._storage = storage if storage is not None else get_storage()

    async def load_file_for_viewer(
        self,
        *,
        upload_id: UUID,
        file_id: UUID,
        user_id: UUID,
    ) -> FileContent:
        """Resolve + validate + load a file for streaming.

        Returns a :class:`FileContent` whose ``stream`` is an async
        generator the router yields straight into a ``StreamingResponse``.
        Raises :class:`NotFound` for any ownership / existence failure
        (no enumeration — see docs/SECURITY.md §3),
        :class:`PayloadTooLarge` for size cap, and
        :class:`UnsupportedFileType` for binary content.
        """

        upload = await self.uploads.get_by_id(upload_id, user_id=user_id)
        if upload is None:
            raise NotFound("File not found")
        if upload.extract_path is None:
            # Upload exists but worker hasn't extracted yet (or extraction
            # failed). 404 because there is no file to serve, and we'd
            # rather not leak that state to a client probing for paths.
            raise NotFound("File not found")

        file_row = await self.files.get_by_id(file_id, user_id=user_id)
        if file_row is None or file_row.upload_id != upload_id:
            # Cross-upload file_id is the same shape of "not part of the
            # resource you asked about" as a missing id — return 404.
            raise NotFound("File not found")

        safe_relative = _safe_relative_path(file_row.path)
        if safe_relative is None:
            # Path-traversal attempt or DB row whose path would escape
            # the upload's prefix. We log it because it's the kind of
            # thing a security review wants to know about, then 404.
            logger.warning(
                "file viewer rejected unsafe path: file_id=%s upload_id=%s path=%r",
                file_id,
                upload_id,
                file_row.path,
            )
            raise NotFound("File not found")

        key = extracted_key(upload.id, safe_relative)
        try:
            size = self._storage.size(key)
        except StorageKeyError:
            # Row exists but the artifact is gone (cleanup race, manual
            # rm, etc). Still a 404 — the user has nothing to view.
            raise NotFound("File not found") from None

        if size > self.max_size_bytes:
            raise PayloadTooLarge(
                f"File is {size} bytes; max viewable size is {self.max_size_bytes}",
            )

        # Read into memory. The 2 MiB cap (settings.max_viewable_file_size_mb)
        # is well below the threshold where streaming would matter; this
        # keeps the abstraction free of partial-read concerns.
        try:
            data = self._storage.get_bytes(key)
        except StorageKeyError:
            # Window between size() and get_bytes() — race with cleanup.
            raise NotFound("File not found") from None

        if _looks_binary(data):
            raise UnsupportedFileType("binary_file_not_viewable")

        return FileContent(
            stream=_stream_bytes(data),
            size_bytes=size,
            key=key,
        )


def _safe_relative_path(relative: str) -> str | None:
    """Reject relative paths that would escape the extract prefix.

    The worker's zip-safety pre-flight (``normalize_entry_path``) already
    rejects path traversal at extraction time, but we re-check here so
    a future ingestion bug doesn't become a viewer-side traversal. Allows
    forward-slash-only relative paths with no ``..`` components.
    """

    if not relative:
        return None
    if relative.startswith("/") or "\\" in relative or "\x00" in relative:
        return None
    normalized = os.path.normpath(relative).replace(os.sep, "/")
    if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        return None
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        return None
    return normalized


def _looks_binary(data: bytes) -> bool:
    """Quick NUL-byte sniff on the first ``BINARY_SNIFF_BYTES`` of data.

    The worker classifies files more carefully (NUL + non-text ratio)
    during extraction — ``files.is_binary`` already reflects that. The
    viewer adds a fresh runtime check anyway because:
    - Source-code files mis-classified as text by the worker (e.g. a
      ``.py`` containing pickled bytes) shouldn't be served as garbage.
    - We don't trust the DB column to never drift from disk reality.
    """

    return b"\x00" in data[:BINARY_SNIFF_BYTES]


async def _stream_bytes(data: bytes) -> AsyncIterator[bytes]:
    """Yield ``data`` in ``CHUNK_SIZE`` windows.

    Bounded in-memory buffer (2 MiB cap upstream) sliced into chunks so
    the response writer doesn't have to flush the whole thing in one
    syscall. Same response shape as the pre-M2 file-handle streamer.
    """

    for offset in range(0, len(data), CHUNK_SIZE):
        yield data[offset : offset + CHUNK_SIZE]
