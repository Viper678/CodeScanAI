"""Disk reads for the file viewer endpoint (T4.3).

``GET /uploads/{upload_id}/files/{file_id}/content`` is intentionally a
small endpoint, but it touches the filesystem and so deserves the same
service layer as the rest of the codebase — keeps the router thin and
gives us a clean unit of test surface for the path-safety + size +
binary checks.

Why a streaming response? Even with a 2 MiB cap, materializing the bytes
in memory before flushing through Starlette's response object means we
hold ~2x the file in memory per concurrent request (Python `bytes` plus
the encoded HTTP body). ``StreamingResponse`` wraps a generator that
reads in 64 KiB chunks; memory stays bounded.

Path-safety note: ``files.path`` is DB-controlled (worker-extracted from
the archive after the path-traversal guard in
``docs/FILE_HANDLING.md`` §"Zip extraction safety"), not user input. We
still resolve and assert containment under ``extract_path`` here as
defense-in-depth — a future ingestion bug shouldn't become a directory
traversal here.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound, PayloadTooLarge, UnsupportedFileType
from app.repositories.file_repo import FileRepo
from app.repositories.upload_repo import UploadRepo

logger = logging.getLogger(__name__)

# 64 KiB streaming window. Big enough to amortize syscall overhead, small
# enough that a few concurrent viewer requests don't balloon RSS.
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
    and uses ``size_bytes`` to populate ``Content-Length``. We expose
    ``resolved_path`` purely for logging / debug — never echo it to a
    client.
    """

    stream: AsyncIterator[bytes]
    size_bytes: int
    resolved_path: Path


class FileContentService:
    """Lookup + read for the file viewer endpoint."""

    def __init__(self, session: AsyncSession, *, max_size_bytes: int) -> None:
        self.session = session
        self.uploads = UploadRepo(session)
        self.files = FileRepo(session)
        self.max_size_bytes = max_size_bytes

    async def load_file_for_viewer(
        self,
        *,
        upload_id: UUID,
        file_id: UUID,
        user_id: UUID,
    ) -> FileContent:
        """Resolve + validate + open a file for streaming.

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

        resolved = _safe_resolve(extract_path=upload.extract_path, relative=file_row.path)
        if resolved is None:
            # Path-traversal attempt or DB row that doesn't land under
            # extract_path. We log it because it's the kind of thing a
            # security review wants to know about, then 404.
            logger.warning(
                "file viewer rejected unsafe path: file_id=%s upload_id=%s path=%r",
                file_id,
                upload_id,
                file_row.path,
            )
            raise NotFound("File not found")

        if not resolved.is_file():
            # Row exists but the artifact is gone (cleanup race, manual
            # rm, etc). Still a 404 — the user has nothing to view.
            raise NotFound("File not found")

        size = resolved.stat().st_size
        if size > self.max_size_bytes:
            raise PayloadTooLarge(
                f"File is {size} bytes; max viewable size is {self.max_size_bytes}",
            )

        if _looks_binary(resolved):
            raise UnsupportedFileType("binary_file_not_viewable")

        return FileContent(
            stream=_stream_file(resolved),
            size_bytes=size,
            resolved_path=resolved,
        )


def _safe_resolve(*, extract_path: str, relative: str) -> Path | None:
    """Resolve ``extract_path / relative`` and assert containment.

    Returns ``None`` if the resolved path escapes ``extract_path`` (so the
    caller can map it to 404). We accept the filesystem ``stat`` cost of
    ``resolve(strict=False)`` because the file is about to be opened
    anyway — the second syscall in :meth:`load_file_for_viewer` is the
    actual existence check.
    """

    root = Path(extract_path).resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _looks_binary(path: Path) -> bool:
    """Quick NUL-byte sniff on the first ``BINARY_SNIFF_BYTES``.

    The worker classifies files more carefully (NUL + non-text ratio)
    during extraction — ``files.is_binary`` already reflects that. The
    viewer adds a fresh runtime check anyway because:
    - Source-code files mis-classified as text by the worker (e.g. a
      ``.py`` containing pickled bytes) shouldn't be served as garbage.
    - We don't trust the DB column to never drift from disk reality.
    """

    with path.open("rb") as handle:
        chunk = handle.read(BINARY_SNIFF_BYTES)
    return b"\x00" in chunk


async def _stream_file(path: Path) -> AsyncIterator[bytes]:
    """Async generator that yields ``CHUNK_SIZE`` chunks from disk.

    We open a sync file handle but yield from an async generator — the
    reads are blocking, but each chunk is only 64 KiB so they don't
    starve the event loop in practice. Keeps the implementation tiny;
    if profiling ever flags this, swap to ``aiofiles``.
    """

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
