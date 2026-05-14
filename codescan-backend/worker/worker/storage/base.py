"""Storage abstraction — protocol + key conventions.

Mirror of ``codescan-backend/api/app/storage/base.py``. The api package cannot import
from the worker package (and vice versa), so the storage abstraction is
duplicated. The two files MUST stay byte-identical at the public surface
— if the producer (api) and consumer (worker) disagree on key shape,
files silently land in different places and the scan pipeline ghosts.

Key conventions (kept in lock-step with the api copy):

- ``uploads/{upload_id}/raw.zip`` — the raw uploaded zip
  (api writes; worker reads). Zip uploads only.
- ``uploads/{upload_id}/loose/{filename}`` — files uploaded loose-by-loose
  (api writes; worker reads + walks).
- ``uploads/{upload_id}/extracted/{relative_path_in_zip}`` — the
  worker-extracted contents of a zip upload (worker writes; api reads
  via the file viewer; worker reads during scan).
- Cleanup deletes everything under the ``uploads/{upload_id}/`` prefix.

Keys are forward-slash separated, no leading slash, no trailing slash,
ASCII-clean.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import BinaryIO, Protocol, runtime_checkable
from uuid import UUID


class StorageKeyError(KeyError):
    """Raised when a get/size/open call hits a missing key."""


@runtime_checkable
class Storage(Protocol):
    """Minimal byte/blob store the codescan pipeline depends on."""

    def put_bytes(self, key: str, data: bytes) -> None:
        """Write ``data`` at ``key``, overwriting any prior object."""

    def put_stream(self, key: str, stream: BinaryIO) -> None:
        """Write ``stream``'s contents at ``key``, overwriting any prior object."""

    def get_bytes(self, key: str) -> bytes:
        """Return the full content of ``key`` as bytes.

        Raises ``StorageKeyError`` if ``key`` is absent.
        """

    def open_stream(self, key: str) -> AbstractContextManager[BinaryIO]:
        """Open ``key`` for streaming reads.

        Raises ``StorageKeyError`` if ``key`` is absent.
        """

    def exists(self, key: str) -> bool:
        """Return True iff ``key`` resolves to a stored object."""

    def delete(self, key: str) -> None:
        """Delete ``key``. Idempotent — missing keys are a no-op."""

    def delete_prefix(self, prefix: str) -> int:
        """Delete every key starting with ``prefix``. Returns count deleted."""

    def iter_prefix(self, prefix: str) -> Iterable[str]:
        """Yield every key starting with ``prefix``, in arbitrary order."""

    def size(self, key: str) -> int:
        """Return the size in bytes of ``key``.

        Raises ``StorageKeyError`` if ``key`` is absent.
        """


# ---- Key helpers (mirror of api side) ----


def upload_prefix(upload_id: UUID | str) -> str:
    """Return the ``uploads/{upload_id}/`` prefix (trailing slash included)."""

    return f"uploads/{upload_id}/"


def raw_zip_key(upload_id: UUID | str) -> str:
    """Return the key for the raw uploaded zip."""

    return f"uploads/{upload_id}/raw.zip"


def extracted_prefix(upload_id: UUID | str) -> str:
    """Return the ``uploads/{upload_id}/extracted/`` prefix for zip extracts."""

    return f"uploads/{upload_id}/extracted/"


def extracted_key(upload_id: UUID | str, relative_path: str) -> str:
    """Return the key for one extracted file within an upload."""

    return f"uploads/{upload_id}/extracted/{relative_path}"


def loose_prefix(upload_id: UUID | str) -> str:
    """Return the ``uploads/{upload_id}/loose/`` prefix for loose uploads."""

    return f"uploads/{upload_id}/loose/"


def loose_key(upload_id: UUID | str, filename: str) -> str:
    """Return the key for one file in a loose upload."""

    return f"uploads/{upload_id}/loose/{filename}"
