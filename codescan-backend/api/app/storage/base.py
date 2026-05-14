"""Storage abstraction — protocol + key conventions.

Hides whether artifacts live on the local filesystem (dev / docker-compose)
or in Google Cloud Storage (prod). All call sites pass forward-slash keys;
the impl maps them to filesystem paths or GCS objects.

Key conventions (MUST stay in sync with ``apps/worker/worker/storage/base.py``;
the api package can't import from the worker package, per the rationale in
``apps/api/app/services/celery_client.py``, so the convention is duplicated):

- ``uploads/{upload_id}/raw.zip`` — the raw uploaded zip
  (api writes; worker reads). Zip uploads only.
- ``uploads/{upload_id}/loose/{filename}`` — files uploaded loose-by-loose
  (api writes; worker reads + walks).
- ``uploads/{upload_id}/extracted/{relative_path_in_zip}`` — the
  worker-extracted contents of a zip upload (worker writes; api reads
  via the file viewer; worker reads during scan).
- Cleanup deletes everything under the ``uploads/{upload_id}/`` prefix.

Keys are forward-slash separated, no leading slash, no trailing slash, and
ASCII-clean — the existing upload pipeline already normalizes / rejects
exotic filenames (see ``app.services.upload_service._safe_basename`` and
``worker.files.safety.normalize_entry_path``). A bare ``uploads`` segment
without a trailing ``/`` is *not* a prefix (``delete_prefix("uploads/")``
is the right call; ``delete_prefix("uploads")`` would also match
``uploadsX`` if such a key existed, which it never should).
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import BinaryIO, Protocol, runtime_checkable
from uuid import UUID


class StorageKeyError(KeyError):
    """Raised when a get/size/open call hits a missing key.

    Subclassing ``KeyError`` so existing ``try/except KeyError`` blocks
    behave sanely, while letting tests / callers distinguish "missing
    storage object" from a dict ``KeyError`` if needed.
    """


@runtime_checkable
class Storage(Protocol):
    """Minimal byte/blob store the codescan pipeline depends on.

    Sync — every consumer is sync today (Celery tasks + sync routes). Don't
    add async overloads until there's a real async consumer.
    """

    def put_bytes(self, key: str, data: bytes) -> None:
        """Write ``data`` at ``key``, overwriting any prior object."""

    def put_stream(self, key: str, stream: BinaryIO) -> None:
        """Write ``stream``'s contents at ``key``, overwriting any prior object.

        Used for zip-entry extraction where the source is already a
        ``BinaryIO`` from ``zipfile.ZipFile.open(entry)`` — avoids
        materializing large entries into memory.
        """

    def get_bytes(self, key: str) -> bytes:
        """Return the full content of ``key`` as bytes.

        Callers are expected to keep reads bounded (file-viewer 2 MiB cap,
        scan-files 1 MiB cap). Raises ``StorageKeyError`` if ``key`` is
        absent.
        """

    def open_stream(self, key: str) -> AbstractContextManager[BinaryIO]:
        """Open ``key`` for streaming reads.

        Returns a context manager yielding a ``BinaryIO``. Used by the
        zip ingestion path, which feeds the handle to
        ``zipfile.ZipFile(..., mode='r')``. Raises ``StorageKeyError``
        if ``key`` is absent.
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

        Cheap metadata read — should never download the object. Raises
        ``StorageKeyError`` if ``key`` is absent.
        """


# ---- Key helpers ----
#
# Centralized so call sites don't string-format paths inline and so the
# api/worker copies stay byte-identical. ``upload_id`` is accepted as
# ``UUID`` (the natural shape from ORM rows) or ``str`` (test convenience)
# — uses ``str()`` either way.


def upload_prefix(upload_id: UUID | str) -> str:
    """Return the ``uploads/{upload_id}/`` prefix (trailing slash included).

    The trailing slash matters for prefix matching — ``uploads/abc/`` vs.
    ``uploads/abc`` would otherwise also match a hypothetical
    ``uploads/abcd`` (which would only exist if the convention drifted,
    but defense in depth).
    """

    return f"uploads/{upload_id}/"


def raw_zip_key(upload_id: UUID | str) -> str:
    """Return the key for the raw uploaded zip."""

    return f"uploads/{upload_id}/raw.zip"


def extracted_prefix(upload_id: UUID | str) -> str:
    """Return the ``uploads/{upload_id}/extracted/`` prefix for zip extracts."""

    return f"uploads/{upload_id}/extracted/"


def extracted_key(upload_id: UUID | str, relative_path: str) -> str:
    """Return the key for one extracted file within an upload.

    ``relative_path`` must already be the forward-slash, no-leading-slash
    form produced by ``worker.files.safety.normalize_entry_path`` (the
    pre-flight pass that rejects path traversal). This helper does not
    re-validate — keep the validation at the boundary.
    """

    return f"uploads/{upload_id}/extracted/{relative_path}"


def loose_prefix(upload_id: UUID | str) -> str:
    """Return the ``uploads/{upload_id}/loose/`` prefix for loose uploads."""

    return f"uploads/{upload_id}/loose/"


def loose_key(upload_id: UUID | str, filename: str) -> str:
    """Return the key for one file in a loose upload."""

    return f"uploads/{upload_id}/loose/{filename}"
