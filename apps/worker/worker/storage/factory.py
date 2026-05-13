"""Storage factory — pick the impl from settings (worker mirror).

``get_storage()`` is cached so the GCS client (which opens an HTTP
connection pool on init) isn't reconstructed per call. Tests that need
to swap impls call ``reset_storage_cache()`` between fixtures.
"""

from __future__ import annotations

from functools import lru_cache

from worker.core.config import settings
from worker.storage.base import Storage
from worker.storage.gcs import GcsStorage
from worker.storage.local import LocalStorage


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    """Return the singleton ``Storage`` implementation for this process."""

    backend = settings.storage_backend
    if backend == "gcs":
        bucket = settings.storage_bucket
        if not bucket:
            raise RuntimeError(
                "STORAGE_BACKEND=gcs requires STORAGE_BUCKET to be set",
            )
        return GcsStorage(bucket=bucket)
    if backend == "local":
        return LocalStorage(root=settings.data_dir)
    raise RuntimeError(f"unknown STORAGE_BACKEND: {backend!r}")


def reset_storage_cache() -> None:
    """Invalidate the cached ``get_storage()`` value (tests only)."""

    get_storage.cache_clear()
