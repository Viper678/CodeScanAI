"""Storage abstraction for the worker process.

Mirror of ``apps/api/app/storage/``. See ``base.py`` for the protocol +
key conventions. The api/worker copies of this module MUST keep their
public surface identical.
"""

from worker.storage.base import (
    Storage,
    StorageKeyError,
    extracted_key,
    extracted_prefix,
    loose_key,
    loose_prefix,
    raw_zip_key,
    upload_prefix,
)
from worker.storage.factory import get_storage, reset_storage_cache
from worker.storage.gcs import GcsStorage
from worker.storage.local import LocalStorage

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
