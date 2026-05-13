"""Storage factory — pick the impl from settings.

``get_storage()`` is cached so the GCS client (which opens an HTTP
connection pool on init) isn't reconstructed per call. Tests that need
to swap impls call ``reset_storage_cache()`` between fixtures, mirroring
the ``_celery_app.cache_clear()`` pattern in
``apps/api/app/services/celery_client.py``.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.storage.base import Storage
from app.storage.gcs import GcsStorage
from app.storage.local import LocalStorage


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    """Return the singleton ``Storage`` implementation for this process.

    Read once at first call; flip ``STORAGE_BACKEND`` only via process
    restart. Tests that need to mutate settings should call
    ``reset_storage_cache()`` to invalidate the cache.
    """

    backend = settings.storage_backend
    if backend == "gcs":
        bucket = settings.storage_bucket
        if not bucket:
            # The config-level validator catches this at app startup;
            # defense in depth here for tests that monkeypatch settings.
            raise RuntimeError(
                "STORAGE_BACKEND=gcs requires STORAGE_BUCKET to be set",
            )
        return GcsStorage(bucket=bucket)
    if backend == "local":
        return LocalStorage(root=settings.data_dir)
    raise RuntimeError(f"unknown STORAGE_BACKEND: {backend!r}")


def reset_storage_cache() -> None:
    """Invalidate the cached ``get_storage()`` value.

    Tests that monkeypatch settings between fixtures call this so the
    factory re-reads the env. Production code should never need it.
    """

    get_storage.cache_clear()
