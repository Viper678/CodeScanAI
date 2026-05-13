"""Google Cloud Storage-backed ``Storage`` implementation.

Wraps the ``google-cloud-storage`` SDK. Credentials are picked up
automatically from the environment — Workload Identity inside GKE,
``GOOGLE_APPLICATION_CREDENTIALS`` JSON for service accounts, or
ambient gcloud credentials in dev. No app-level secret handling.

The bucket name is supplied at construction time (resolved from
``settings.storage_bucket`` in the factory). All keys live in the
``uploads/...`` prefix — the bucket is otherwise empty for codescan.

Test injection: the ``client`` arg lets tests pass a dict-backed fake
that quacks like ``google.cloud.storage.Client``. See
``tests/unit/test_storage_gcs.py`` for the fake.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, BinaryIO, cast

from app.storage.base import StorageKeyError

logger = logging.getLogger(__name__)


class GcsStorage:
    """GCS-backed Storage.

    Args:
        bucket: GCS bucket name (no ``gs://`` prefix, no trailing slash).
        client: Optional pre-built ``google.cloud.storage.Client``. Tests
            inject a fake here; production callers pass ``None`` and let
            the constructor build a real client using the ambient
            credentials.
    """

    def __init__(self, bucket: str, *, client: Any | None = None) -> None:
        if not bucket:
            raise ValueError("GcsStorage requires a non-empty bucket name")
        self._bucket_name = bucket
        if client is None:
            # Defer the SDK import to construction so unit tests that
            # never touch GCS don't have to install the dep into their
            # venv (though the dep is declared in pyproject regardless).
            from google.cloud import storage as gcs_module

            self._client: Any = gcs_module.Client()
        else:
            self._client = client
        # Cache the bucket handle — every operation walks
        # client.bucket(name) which is cheap but not zero-cost.
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
        # in memory. Callers that pipe through ``shutil.copyfileobj``
        # get bounded RSS even on 100 MiB archives. Codex P2 on M2.
        blob = self._bucket.blob(key)
        return _gcs_stream_context(blob, key)

    # ---- metadata ----

    def exists(self, key: str) -> bool:
        return bool(self._bucket.blob(key).exists())

    def size(self, key: str) -> int:
        # ``Blob.size`` is None until the blob is reloaded; fetch metadata.
        blob = self._bucket.get_blob(key)
        if blob is None:
            raise StorageKeyError(key)
        size = getattr(blob, "size", None)
        if size is None:
            # justify: a freshly-created blob may report size=None until
            # metadata is reloaded; force a reload as a fallback.
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
        # Snapshot the blob list first — iterating the list_blobs cursor
        # while deleting can produce duplicate visits on some backends.
        blobs = list(self._client.list_blobs(self._bucket_name, prefix=prefix))
        for blob in blobs:
            try:
                blob.delete()
                count += 1
            except Exception as exc:
                # justify: real SDK can raise transport-layer exceptions
                # we can't enumerate; classify "not found" as success
                # (idempotent delete) and propagate everything else.
                if _is_not_found(exc):
                    continue
                raise
        return count

    def iter_prefix(self, prefix: str) -> Iterable[str]:
        for blob in self._client.list_blobs(self._bucket_name, prefix=prefix):
            yield str(blob.name)


# ---- helpers ----


def _is_not_found(exc: BaseException) -> bool:
    """Return True for the SDK's "object missing" exception class.

    google.api_core.exceptions.NotFound carries a 404. We import lazily so
    unit tests that never touch the SDK don't have to install
    google-api-core just to mypy --strict the module.
    """

    try:
        from google.api_core.exceptions import NotFound
    except ImportError:
        return False
    return isinstance(exc, NotFound)


@contextmanager
def _gcs_stream_context(blob: Any, key: str) -> Iterator[BinaryIO]:
    """Open a GCS blob for true streaming reads (mirror of worker side).

    NotFound is normalized to ``StorageKeyError`` to match the
    abstraction's contract — at open AND during read (GCS can lazily
    raise on the first byte fetched). Other SDK exceptions propagate.
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
        if _is_not_found(exc):
            raise StorageKeyError(key) from exc
        raise
    finally:
        fh.close()


@contextmanager
def _bytes_context(data: bytes) -> Iterator[BinaryIO]:
    """Wrap ``data`` in a context-managed BytesIO."""

    buf = io.BytesIO(data)
    try:
        yield buf
    finally:
        buf.close()
