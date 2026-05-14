"""Google Cloud Storage-backed ``Storage`` implementation (worker mirror).

Mirror of ``codescan-backend/api/app/storage/gcs.py``. Credentials are picked up
from the environment (Workload Identity, ``GOOGLE_APPLICATION_CREDENTIALS``,
ambient gcloud) — no app-level secret handling.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, BinaryIO, cast

from worker.storage.base import StorageKeyError

logger = logging.getLogger(__name__)


class GcsStorage:
    """GCS-backed Storage.

    Args:
        bucket: GCS bucket name (no ``gs://`` prefix, no trailing slash).
        client: Optional pre-built ``google.cloud.storage.Client``. Tests
            inject a fake here; production callers pass ``None``.
    """

    def __init__(self, bucket: str, *, client: Any | None = None) -> None:
        if not bucket:
            raise ValueError("GcsStorage requires a non-empty bucket name")
        self._bucket_name = bucket
        if client is None:
            from google.cloud import storage as gcs_module

            self._client: Any = gcs_module.Client()
        else:
            self._client = client
        self._bucket = self._client.bucket(bucket)

    # ---- writes ----

    def put_bytes(self, key: str, data: bytes) -> None:
        blob = self._bucket.blob(key)
        blob.upload_from_string(data)

    def put_stream(self, key: str, stream: BinaryIO) -> None:
        blob = self._bucket.blob(key)
        blob.upload_from_file(stream, rewind=False)

    # ---- reads ----

    def get_bytes(self, key: str) -> bytes:
        blob = self._bucket.blob(key)
        try:
            return bytes(blob.download_as_bytes())
        except Exception as exc:
            if _is_not_found(exc):
                raise StorageKeyError(key) from exc
            raise

    def open_stream(self, key: str) -> AbstractContextManager[BinaryIO]:
        # True streaming via ``blob.open("rb")``: the GCS SDK fetches in
        # chunks under the hood instead of materializing the full object
        # in memory the way ``download_as_bytes`` would. Callers that
        # pipe through ``shutil.copyfileobj`` get bounded RSS even on
        # 100 MiB archives. Codex P2 on M2.
        blob = self._bucket.blob(key)
        return _gcs_stream_context(blob, key)

    # ---- metadata ----

    def exists(self, key: str) -> bool:
        return bool(self._bucket.blob(key).exists())

    def size(self, key: str) -> int:
        blob = self._bucket.get_blob(key)
        if blob is None:
            raise StorageKeyError(key)
        size = getattr(blob, "size", None)
        if size is None:
            blob.reload()
            size = getattr(blob, "size", None)
        if size is None:
            raise StorageKeyError(key)
        return int(size)

    # ---- deletes / listing ----

    def delete(self, key: str) -> None:
        blob = self._bucket.blob(key)
        try:
            blob.delete()
        except Exception as exc:
            if _is_not_found(exc):
                return
            raise

    def delete_prefix(self, prefix: str) -> int:
        count = 0
        blobs = list(self._client.list_blobs(self._bucket_name, prefix=prefix))
        for blob in blobs:
            try:
                blob.delete()
                count += 1
            except Exception as exc:
                # justify: classify "not found" as success (idempotent
                # delete); propagate transport/permission errors.
                if _is_not_found(exc):
                    continue
                raise
        return count

    def iter_prefix(self, prefix: str) -> Iterable[str]:
        for blob in self._client.list_blobs(self._bucket_name, prefix=prefix):
            yield str(blob.name)


def _is_not_found(exc: BaseException) -> bool:
    try:
        from google.api_core.exceptions import NotFound
    except ImportError:
        return False
    return isinstance(exc, NotFound)


@contextmanager
def _gcs_stream_context(blob: Any, key: str) -> Iterator[BinaryIO]:
    """Open a GCS blob for true streaming reads.

    ``blob.open("rb")`` returns a file-like object that fetches in
    chunks; this lets callers pipe through ``shutil.copyfileobj``
    without materializing the whole object in memory.

    NotFound is normalized to ``StorageKeyError`` to match the
    abstraction's contract. Other SDK exceptions (auth, transport)
    propagate unchanged — callers see a typed GCS error and decide
    whether to retry.
    """
    try:
        fh = blob.open(mode="rb")
    except Exception as exc:
        if _is_not_found(exc):
            raise StorageKeyError(key) from exc
        raise
    try:
        yield cast(BinaryIO, fh)
    except Exception as exc:
        # Reads can lazily 404 — normalize that path too.
        if _is_not_found(exc):
            raise StorageKeyError(key) from exc
        raise
    finally:
        fh.close()
