"""Unit tests for ``app.storage.GcsStorage``.

Backed by an in-process dict-backed fake ``google.cloud.storage.Client``
so tests don't need GCS credentials, network access, or a fake-gcs-server
container. The fake quacks like the real Client at the surface the
GcsStorage impl touches (``bucket``, ``blob``, ``list_blobs``, ``get_blob``).

Why in-process instead of fake-gcs-server: docker-compose overhead in CI
isn't worth the marginal additional coverage. The Storage protocol is
small enough that a Python fake matches the real SDK's contract for
the surface we depend on.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.storage import GcsStorage, StorageKeyError

# ---- Dict-backed fake -------------------------------------------------------


class _FakeNotFound(Exception):
    """Stand-in for ``google.api_core.exceptions.NotFound``.

    The real SDK raises ``google.api_core.exceptions.NotFound`` on a 404;
    the GcsStorage impl catches it via ``_is_not_found`` which imports
    that class at call time. We don't want unit tests to drag in the
    SDK module, so we install our own class into the SDK's exception
    module via monkeypatch (see ``patch_not_found`` fixture).
    """


@dataclass
class _FakeBucket:
    """Forward declaration — populated below; needed by _FakeBlob."""

    name: str
    _blobs: dict[str, _FakeBlob] = field(default_factory=dict)

    # ``blob`` defined as a stub here; the real one below operates on
    # ``_FakeBlob`` which is defined after this class. Python's name
    # resolution at call time lets us reference _FakeBlob by name even
    # though it's defined after _FakeBucket.

    def blob(self, key: str) -> _FakeBlob:
        existing = self._blobs.get(key)
        if existing is not None:
            return existing
        return _FakeBlob(name=key, bucket=self)


@dataclass
class _FakeBlob:
    """In-memory blob with the minimal surface GcsStorage uses."""

    name: str
    bucket: _FakeBucket
    _payload: bytes | None = None
    _size: int | None = None
    _exists: bool = False

    def upload_from_string(self, data: bytes) -> None:
        self._payload = bytes(data)
        self._size = len(self._payload)
        self._exists = True
        self.bucket._blobs[self.name] = self

    def upload_from_file(self, stream: Any, *, rewind: bool = False) -> None:
        del rewind
        data = stream.read()
        self.upload_from_string(data)

    def download_as_bytes(self) -> bytes:
        if not self._exists:
            raise _FakeNotFound(f"blob {self.name!r} not found")
        return self._payload or b""

    def exists(self) -> bool:
        return self._exists

    def delete(self) -> None:
        if not self._exists:
            raise _FakeNotFound(f"blob {self.name!r} not found")
        self._exists = False
        self.bucket._blobs.pop(self.name, None)

    def reload(self) -> None:
        if not self._exists:
            raise _FakeNotFound(f"blob {self.name!r} not found")

    @property
    def size(self) -> int | None:
        return self._size


@dataclass
class _FakeClient:
    """Stand-in for ``google.cloud.storage.Client``."""

    buckets: dict[str, _FakeBucket] = field(default_factory=dict)

    def bucket(self, name: str) -> _FakeBucket:
        return self.buckets.setdefault(name, _FakeBucket(name=name))

    def get_bucket(self, name: str) -> _FakeBucket:
        return self.bucket(name)

    def list_blobs(self, bucket_name: str, *, prefix: str = "") -> list[_FakeBlob]:
        bucket = self.bucket(bucket_name)
        return sorted(
            (b for b in bucket._blobs.values() if b.name.startswith(prefix)),
            key=lambda b: b.name,
        )


# get_blob is on bucket in newer SDK versions but on client in older; the
# GcsStorage impl uses ``bucket.get_blob(key)``. Expose that.
def _bucket_get_blob(self: _FakeBucket, key: str) -> _FakeBlob | None:
    blob = self._blobs.get(key)
    return blob if blob is not None and blob._exists else None


_FakeBucket.get_blob = _bucket_get_blob  # type: ignore[attr-defined]


# ---- Fixtures ---------------------------------------------------------------


@pytest.fixture
def patch_not_found(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Patch ``google.api_core.exceptions.NotFound`` to our fake class.

    ``GcsStorage._is_not_found`` imports the SDK's NotFound at call time
    and ``isinstance``-checks against it. Pointing the import at our
    ``_FakeNotFound`` keeps the impl agnostic to whether the test runs
    against the real SDK or the fake.
    """

    import google.api_core.exceptions as exc_mod

    monkeypatch.setattr(exc_mod, "NotFound", _FakeNotFound)
    yield


@pytest.fixture
def storage(patch_not_found: None) -> GcsStorage:
    del patch_not_found  # fixture is autouse-via-arg; consume to silence unused
    client = _FakeClient()
    return GcsStorage(bucket="test-bucket", client=client)


# ---- Tests ------------------------------------------------------------------


def test_put_bytes_and_get_bytes_round_trip(storage: GcsStorage) -> None:
    storage.put_bytes("uploads/abc/raw.zip", b"PK\x03\x04hello")
    assert storage.get_bytes("uploads/abc/raw.zip") == b"PK\x03\x04hello"


def test_put_stream_round_trip(storage: GcsStorage) -> None:
    storage.put_stream("uploads/abc/x.py", io.BytesIO(b"stream"))
    assert storage.get_bytes("uploads/abc/x.py") == b"stream"


def test_put_bytes_overwrites(storage: GcsStorage) -> None:
    storage.put_bytes("k", b"first")
    storage.put_bytes("k", b"second")
    assert storage.get_bytes("k") == b"second"


def test_open_stream_yields_bytesio(storage: GcsStorage) -> None:
    storage.put_bytes("blob", b"abc\x00def")
    with storage.open_stream("blob") as fh:
        assert fh.read() == b"abc\x00def"


def test_exists(storage: GcsStorage) -> None:
    storage.put_bytes("a/b/c", b"x")
    assert storage.exists("a/b/c") is True
    assert storage.exists("a/b/missing") is False


def test_size_returns_byte_len(storage: GcsStorage) -> None:
    storage.put_bytes("k", b"hello world")
    assert storage.size("k") == 11


def test_size_raises_on_missing(storage: GcsStorage) -> None:
    with pytest.raises(StorageKeyError):
        storage.size("missing")


def test_get_bytes_raises_on_missing(storage: GcsStorage) -> None:
    with pytest.raises(StorageKeyError):
        storage.get_bytes("missing")


def test_open_stream_raises_on_missing(storage: GcsStorage) -> None:
    with pytest.raises(StorageKeyError):
        storage.open_stream("missing").__enter__()


def test_delete_idempotent(storage: GcsStorage) -> None:
    storage.delete("never-existed")  # no raise


def test_delete_removes_key(storage: GcsStorage) -> None:
    storage.put_bytes("k", b"x")
    assert storage.exists("k") is True
    storage.delete("k")
    assert storage.exists("k") is False


def test_delete_prefix_returns_count(storage: GcsStorage) -> None:
    storage.put_bytes("uploads/abc/raw.zip", b"r")
    storage.put_bytes("uploads/abc/extracted/a.py", b"a")
    storage.put_bytes("uploads/abc/extracted/sub/b.py", b"b")
    storage.put_bytes("uploads/other/raw.zip", b"keep")

    count = storage.delete_prefix("uploads/abc/")

    assert count == 3
    assert not storage.exists("uploads/abc/raw.zip")
    assert storage.exists("uploads/other/raw.zip")  # adjacent untouched


def test_delete_prefix_zero_when_empty(storage: GcsStorage) -> None:
    assert storage.delete_prefix("uploads/never/") == 0


def test_iter_prefix_yields_sorted_keys(storage: GcsStorage) -> None:
    storage.put_bytes("uploads/abc/extracted/z.py", b"z")
    storage.put_bytes("uploads/abc/extracted/a.py", b"a")

    keys = list(storage.iter_prefix("uploads/abc/extracted/"))

    assert keys == [
        "uploads/abc/extracted/a.py",
        "uploads/abc/extracted/z.py",
    ]


def test_gcs_storage_rejects_empty_bucket() -> None:
    with pytest.raises(ValueError):
        GcsStorage(bucket="", client=_FakeClient())
