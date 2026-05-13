"""Storage abstraction for the API process.

Hides whether artifacts live on the local filesystem or in GCS. See
``base.py`` for the protocol + key conventions. The api/worker copies of
this module must keep their public surface identical — the worker
mirrors live at ``apps/worker/worker/storage/``.
"""

from app.storage.base import (
    Storage,
    StorageKeyError,
    extracted_key,
    extracted_prefix,
    loose_key,
    loose_prefix,
    raw_zip_key,
    upload_prefix,
)
from app.storage.factory import get_storage, reset_storage_cache
from app.storage.gcs import GcsStorage
from app.storage.local import LocalStorage

__all__ = [
    "GcsStorage",
    "LocalStorage",
    "Storage",
    "StorageKeyError",
    "extracted_key",
    "extracted_prefix",
    "get_storage",
    "loose_key",
    "loose_prefix",
    "raw_zip_key",
    "reset_storage_cache",
    "upload_prefix",
]
