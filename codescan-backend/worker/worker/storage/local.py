"""Filesystem-backed ``Storage`` implementation (worker mirror).

Mirror of ``apps/api/app/storage/local.py``. Maps keys to ``root / key``
on disk. Preserves the pre-M2 on-disk layout so dev / docker-compose /
existing worker tests keep working byte-for-byte.
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import uuid
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import BinaryIO, cast

from worker.storage.base import StorageKeyError


def _tmp_path_for(target: Path) -> Path:
    """Build a unique sibling path used for atomic-rename staging.

    Leading dot + uuid suffix keeps the temp name out of conflict with
    any legitimate object that might share the target's stem. Must live
    in the target's parent directory so ``os.replace`` is atomic (same
    filesystem).
    """

    return target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"


# Mirror of api-side ``_open_private_excl``. ``Path.open("wb")`` honors
# the process umask so files end up at 0o644 (world-readable on most
# systems) — bad for uploaded source on a shared filesystem. Codex P2 on M2.
_FILE_MODE: int = 0o600


def _open_private_excl(path: Path) -> BinaryIO:
    """Open ``path`` for binary write with ``0o600`` perms (excl create)."""

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    return cast(BinaryIO, os.fdopen(fd, "wb", closefd=True))


logger = logging.getLogger(__name__)

_STREAM_CHUNK = 1024 * 1024


def _validate_key(key: str) -> str:
    """Reject leading slash / null bytes / parent traversal."""

    if not key:
        raise ValueError("storage key must not be empty")
    if key.startswith("/"):
        raise ValueError(f"storage key must not start with '/': {key!r}")
    if "\x00" in key:
        raise ValueError(f"storage key contains NUL byte: {key!r}")
    parts = key.split("/")
    if any(part == ".." for part in parts):
        raise ValueError(f"storage key contains '..' segment: {key!r}")
    return key


class LocalStorage:
    """Filesystem-backed Storage."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        """Expose the on-disk root for legacy call sites that join paths.

        The worker scanner orchestrator still needs ``Path.read_text`` for
        per-file scanning (the LLM client wants ``str``), and joining a
        key to the root via the property is the cleanest local-only
        shortcut. The GCS backend has no analog — callers that read this
        property are explicitly filesystem-only.
        """

        return self._root

    def _resolve(self, key: str) -> Path:
        return self._root / _validate_key(key)

    # ---- writes ----

    def put_bytes(self, key: str, data: bytes) -> None:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_path_for(target)
        with _open_private_excl(tmp) as out:
            out.write(data)
        os.replace(tmp, target)

    def put_stream(self, key: str, stream: BinaryIO) -> None:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_path_for(target)
        with _open_private_excl(tmp) as out:
            while True:
                chunk = stream.read(_STREAM_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(tmp, target)

    # ---- reads ----

    def get_bytes(self, key: str) -> bytes:
        target = self._resolve(key)
        try:
            return target.read_bytes()
        except FileNotFoundError as exc:
            raise StorageKeyError(key) from exc

    def open_stream(self, key: str) -> AbstractContextManager[BinaryIO]:
        target = self._resolve(key)
        if not target.is_file():
            raise StorageKeyError(key)
        return _open_binary(target)

    # ---- metadata ----

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def size(self, key: str) -> int:
        target = self._resolve(key)
        try:
            return target.stat().st_size
        except FileNotFoundError as exc:
            raise StorageKeyError(key) from exc

    # ---- deletes / listing ----

    def delete(self, key: str) -> None:
        target = self._resolve(key)
        if target.is_file():
            target.unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> int:
        _validate_key(prefix)
        target = self._root / prefix
        if not target.exists():
            return 0
        count = 0
        if target.is_file():
            target.unlink()
            return 1
        for dirpath, _dirnames, filenames in os.walk(target, topdown=False):
            for filename in filenames:
                file_path = Path(dirpath) / filename
                try:
                    file_path.unlink()
                    count += 1
                except FileNotFoundError:
                    continue
            with contextlib.suppress(OSError):
                Path(dirpath).rmdir()
        with contextlib.suppress(OSError):
            target.rmdir()
        return count

    def iter_prefix(self, prefix: str) -> Iterable[str]:
        _validate_key(prefix)
        target = self._root / prefix
        if not target.exists() or not target.is_dir():
            return
        for path in sorted(target.rglob("*")):
            if not path.is_file():
                continue
            yield str(path.relative_to(self._root)).replace(os.sep, "/")


@contextmanager
def _open_binary(path: Path) -> Iterator[BinaryIO]:
    fh = path.open("rb")
    try:
        yield _ensure_binary(fh)
    finally:
        fh.close()


def _ensure_binary(fh: io.IOBase) -> BinaryIO:
    return fh  # type: ignore[return-value]
