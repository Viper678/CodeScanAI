"""Unit tests for ``app.storage.get_storage`` factory.

Covers the backend selector (default ``local``, opt-in ``gcs``), the
bucket-required validator, and the lru-cache invalidation pattern that
test fixtures rely on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.storage import (
    GcsStorage,
    LocalStorage,
    Storage,
    get_storage,
    reset_storage_cache,
)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    """Clear the cached factory between tests so each one starts fresh."""

    reset_storage_cache()


def test_default_backend_is_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    storage = get_storage()
    assert isinstance(storage, LocalStorage)


def test_local_backend_uses_configured_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    storage = get_storage()
    storage.put_bytes("test", b"x")
    assert (tmp_path / "test").read_bytes() == b"x"


def test_gcs_backend_raises_without_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "storage_backend", "gcs")
    monkeypatch.setattr(settings, "storage_bucket", None)
    with pytest.raises(RuntimeError, match="STORAGE_BUCKET"):
        get_storage()


def test_gcs_backend_constructs_with_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing a GcsStorage with a non-empty bucket succeeds.

    We pre-construct via the GcsStorage class directly with an injected
    fake to avoid creating a real GCS client (which would attempt to
    pick up ambient credentials and fail in CI).
    """

    monkeypatch.setattr(settings, "storage_backend", "gcs")
    monkeypatch.setattr(settings, "storage_bucket", "test-bucket")

    # Stub the SDK's Client so get_storage() can construct GcsStorage
    # without dialing GCS.
    class _StubClient:
        def bucket(self, name: str) -> object:
            return object()

    import google.cloud.storage as gcs_mod

    monkeypatch.setattr(gcs_mod, "Client", _StubClient)

    storage: Storage = get_storage()
    assert isinstance(storage, GcsStorage)


def test_get_storage_is_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    first = get_storage()
    second = get_storage()
    assert first is second


def test_reset_cache_invalidates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    first = get_storage()
    reset_storage_cache()
    second = get_storage()
    assert first is not second


def test_unknown_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bypass the pydantic Literal validator by mutating the attribute
    # directly — Settings was already constructed before this test.
    monkeypatch.setattr(settings, "storage_backend", "s3")
    with pytest.raises(RuntimeError, match="unknown STORAGE_BACKEND"):
        get_storage()
