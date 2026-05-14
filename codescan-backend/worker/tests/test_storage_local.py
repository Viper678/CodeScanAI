"""Unit tests for ``worker.storage.LocalStorage`` (worker mirror).

Identical surface to the api-side test (``codescan-backend/api/tests/unit/test_storage_local.py``).
The two storage modules MUST stay in lock-step; if these tests diverge,
producers and consumers will disagree on key shape and the pipeline
ghosts files.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from worker.storage import LocalStorage, StorageKeyError


def test_put_bytes_and_get_bytes_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put_bytes("uploads/abc/raw.zip", b"PK\x03\x04hello")

    assert storage.get_bytes("uploads/abc/raw.zip") == b"PK\x03\x04hello"
    assert (tmp_path / "uploads" / "abc" / "raw.zip").read_bytes() == b"PK\x03\x04hello"


def test_put_stream_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put_stream("uploads/abc/extracted/x.py", io.BytesIO(b"streamed payload"))
    assert storage.get_bytes("uploads/abc/extracted/x.py") == b"streamed payload"


def test_put_bytes_overwrites_existing_object(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put_bytes("k", b"first")
    storage.put_bytes("k", b"second")
    assert storage.get_bytes("k") == b"second"


def test_open_stream_yields_binary_io(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put_bytes("blob", b"abc\x00def")
    with storage.open_stream("blob") as fh:
        assert fh.read() == b"abc\x00def"


def test_exists_returns_true_for_present_key(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put_bytes("a/b/c", b"x")
    assert storage.exists("a/b/c") is True
    assert storage.exists("a/b/missing") is False


def test_size_returns_bytes_len(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put_bytes("k", b"hello world")
    assert storage.size("k") == 11


def test_size_raises_on_missing_key(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(StorageKeyError):
        storage.size("nope")


def test_get_bytes_raises_on_missing_key(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(StorageKeyError):
        storage.get_bytes("nope")


def test_open_stream_raises_on_missing_key(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(StorageKeyError):
        storage.open_stream("nope").__enter__()


def test_delete_is_idempotent_on_missing_key(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.delete("never-existed")


def test_delete_removes_key(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put_bytes("k", b"x")
    assert storage.exists("k") is True
    storage.delete("k")
    assert storage.exists("k") is False


def test_delete_prefix_removes_all_under_prefix(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put_bytes("uploads/abc/raw.zip", b"r")
    storage.put_bytes("uploads/abc/extracted/a.py", b"a")
    storage.put_bytes("uploads/abc/extracted/sub/b.py", b"b")
    storage.put_bytes("uploads/other/raw.zip", b"keep")

    count = storage.delete_prefix("uploads/abc/")

    assert count == 3
    assert not storage.exists("uploads/abc/raw.zip")
    assert not storage.exists("uploads/abc/extracted/a.py")
    assert not storage.exists("uploads/abc/extracted/sub/b.py")
    assert storage.get_bytes("uploads/other/raw.zip") == b"keep"


def test_delete_prefix_idempotent_on_missing(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    assert storage.delete_prefix("uploads/never/") == 0


def test_iter_prefix_yields_sorted_keys(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put_bytes("uploads/abc/extracted/z.py", b"z")
    storage.put_bytes("uploads/abc/extracted/a.py", b"a")
    storage.put_bytes("uploads/abc/extracted/sub/m.py", b"m")

    keys = list(storage.iter_prefix("uploads/abc/extracted/"))
    assert keys == [
        "uploads/abc/extracted/a.py",
        "uploads/abc/extracted/sub/m.py",
        "uploads/abc/extracted/z.py",
    ]


def test_iter_prefix_on_missing_prefix_yields_nothing(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    assert list(storage.iter_prefix("uploads/never/")) == []


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "/leading-slash",
        "with\x00null",
        "evil/../traversal",
        "..",
        "../../etc",
    ],
)
def test_validate_key_rejects_unsafe(tmp_path: Path, bad_key: str) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.put_bytes(bad_key, b"x")


def test_put_bytes_doesnt_collide_with_existing_tmp_suffixed_sibling(
    tmp_path: Path,
) -> None:
    """Regression: pre-fix, ``put_bytes("foo")`` staged through ``foo.tmp``
    which would silently destroy a legitimately-stored ``foo.tmp`` written
    moments earlier in the same dir (e.g. a zip containing both ``foo.tmp``
    and ``foo``). Codex P2 on M2.
    """

    storage = LocalStorage(tmp_path)
    storage.put_bytes("uploads/abc/extracted/foo.tmp", b"keep-tmp")
    storage.put_bytes("uploads/abc/extracted/foo", b"keep-foo")

    assert storage.get_bytes("uploads/abc/extracted/foo.tmp") == b"keep-tmp"
    assert storage.get_bytes("uploads/abc/extracted/foo") == b"keep-foo"


def test_put_stream_doesnt_collide_with_existing_tmp_suffixed_sibling(
    tmp_path: Path,
) -> None:
    """Same as the put_bytes variant but exercising the streaming write
    path that ``safe_extract`` actually uses for zip entries.
    """

    storage = LocalStorage(tmp_path)
    storage.put_stream("uploads/abc/extracted/a.py.tmp", io.BytesIO(b"tmp-content"))
    storage.put_stream("uploads/abc/extracted/a.py", io.BytesIO(b"real-content"))

    assert storage.get_bytes("uploads/abc/extracted/a.py.tmp") == b"tmp-content"
    assert storage.get_bytes("uploads/abc/extracted/a.py") == b"real-content"


def test_put_bytes_writes_file_with_0600_perms(tmp_path: Path) -> None:
    """0o600 mirror of the api-side test — shared-filesystem privacy
    invariant. Codex P2 on M2.
    """

    import stat

    storage = LocalStorage(tmp_path)
    storage.put_bytes("uploads/abc/raw.zip", b"PK\x03\x04hello")

    mode = (tmp_path / "uploads" / "abc" / "raw.zip").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_put_stream_writes_file_with_0600_perms(tmp_path: Path) -> None:
    """Same 0600 guarantee for the streaming write path (zip extraction)."""

    import stat

    storage = LocalStorage(tmp_path)
    storage.put_stream("uploads/abc/extracted/x.py", io.BytesIO(b"print('hi')\n"))

    mode = (tmp_path / "uploads" / "abc" / "extracted" / "x.py").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600
