"""Filesystem-backed ``Storage`` implementation.

Maps keys to ``root / key`` on disk. Preserves the on-disk layout the
codebase used pre-M2 (e.g. ``/data/uploads/<id>/raw.zip``), so dev /
docker-compose / existing tests keep working byte-for-byte after the
abstraction.

Note on the layout shift: previously the api wrote the raw zip as
``/data/uploads/<id>/<original-name>.zip`` (where the basename came from
the upload's original filename). With the storage abstraction we drop
the user-controlled name and pin a canonical ``raw.zip``. The original
name is still preserved in the ``uploads.original_name`` DB column for
display; nothing downstream consumes the on-disk filename.
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

from app.storage.base import StorageKeyError


def _tmp_path_for(target: Path) -> Path:
    """Build a unique sibling path used for atomic-rename staging.

    Leading dot + uuid suffix keeps the temp name out of conflict with
    any legitimate object that might share the target's stem. Must live
    in the target's parent directory so ``os.replace`` is atomic (same
    filesystem).
    """

    return target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"


# justify: ``Path.open("wb")`` honors the process umask (commonly 022) so
# files end up world-readable (0o644). Pre-M2 the upload service used
# ``os.open(..., 0o600)`` explicitly for raw zips. Preserve that: anything
# we write through LocalStorage (raw zips, loose files, extracted source)
# is private to the api/worker user on a shared filesystem (single-VM
# deployments, docker-compose volumes mounted host-side). Codex P2 on M2.
_FILE_MODE: int = 0o600


def _open_private_excl(path: Path) -> BinaryIO:
    """Open ``path`` for binary write with ``0o600`` perms, refusing to
    clobber an existing file.

    ``os.open`` respects the mode argument directly (modulo umask, which
    only masks bits *not* set in the requested mode — so 0o600 stays 0o600
    under any standard umask). ``O_EXCL`` paired with ``O_CREAT`` makes the
    create atomic against another process racing on the same temp name —
    the uuid suffix already makes that essentially impossible, but
    O_EXCL costs nothing.
    """

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    # closefd=True transfers ownership to the file object; the caller's
    # ``with`` block closes the underlying descriptor.
    return cast(BinaryIO, os.fdopen(fd, "wb", closefd=True))


logger = logging.getLogger(__name__)

# justify: open + write loops use 1 MiB windows so a 100 MiB zip doesn't
# block the event loop or balloon RSS on a single put_stream call.
_STREAM_CHUNK = 1024 * 1024


def _validate_key(key: str) -> str:
    """Reject leading slash / null bytes / parent traversal.

    Keys come from internal callers; this is defense in depth, not user
    input validation (which already happens in
    ``upload_service._safe_basename`` and ``safety.normalize_entry_path``).
    """

    if not key:
        raise ValueError("storage key must not be empty")
    if key.startswith("/"):
        raise ValueError(f"storage key must not start with '/': {key!r}")
    if "\x00" in key:
        raise ValueError(f"storage key contains NUL byte: {key!r}")
    # parts == ['', ...] when key starts with '/'; covered above
    parts = key.split("/")
    if any(part == ".." for part in parts):
        raise ValueError(f"storage key contains '..' segment: {key!r}")
    return key


class LocalStorage:
    """Filesystem-backed Storage.

    ``root`` is the directory keys are resolved against — equal to
    ``settings.data_dir`` in normal operation. Tests pass a ``tmp_path``.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def _resolve(self, key: str) -> Path:
        return self._root / _validate_key(key)

    # ---- writes ----

    def put_bytes(self, key: str, data: bytes) -> None:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write via tmp + rename so a crashed write doesn't leave a
        # half-formed object. UUID-suffixed temp name (not
        # ``target.suffix + ".tmp"``) — otherwise a key like ``foo``
        # would stage through ``foo.tmp``, which collides with a
        # legitimately-extracted ``foo.tmp`` elsewhere in the same zip
        # and silently overwrites it before rename. Codex P2 on M2.
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
        # Idempotent — missing key is a no-op (matches the GCS impl).
        if target.is_file():
            target.unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> int:
        """Delete every file (and emptied directories) under ``prefix``.

        Returns the number of files removed. Directories are pruned when
        empty so the on-disk shape after a sweep matches "no trace of
        this upload" (the GCS impl naturally yields the same shape —
        directories don't exist there).
        """

        _validate_key(prefix)
        target = self._root / prefix
        if not target.exists():
            return 0
        count = 0
        if target.is_file():
            # Treat a file-prefix as a single delete — matches GCS where
            # a "prefix" that happens to equal one object key still
            # deletes that object.
            target.unlink()
            return 1
        # target is a directory; walk it bottom-up so rmdir of intermediate
        # dirs is safe after their files are gone.
        for dirpath, _dirnames, filenames in os.walk(target, topdown=False):
            for filename in filenames:
                file_path = Path(dirpath) / filename
                try:
                    file_path.unlink()
                    count += 1
                except FileNotFoundError:
                    # Race with another sweep; treat as already-counted.
                    continue
            # Best-effort dir cleanup — if not empty (e.g. concurrent
            # write landed mid-sweep) we leave it.
            with contextlib.suppress(OSError):
                Path(dirpath).rmdir()
        # And the top-level prefix dir if it's now empty.
        with contextlib.suppress(OSError):
            target.rmdir()
        return count

    def iter_prefix(self, prefix: str) -> Iterable[str]:
        """Yield keys under ``prefix`` in lexical order.

        ``os.walk`` doesn't sort by default; tests rely on stable order
        for delete_prefix counts and listing assertions. ``rglob`` is
        deterministic enough for our scale.
        """

        _validate_key(prefix)
        target = self._root / prefix
        if not target.exists() or not target.is_dir():
            return
        # ``rglob('*')`` yields both files and directories — we only emit
        # file keys to match the GCS object model.
        for path in sorted(target.rglob("*")):
            if not path.is_file():
                continue
            yield str(path.relative_to(self._root)).replace(os.sep, "/")


@contextmanager
def _open_binary(path: Path) -> Iterator[BinaryIO]:
    """Wrap ``path.open('rb')`` so its return type is ``BinaryIO``.

    Type-narrowing helper: ``Path.open`` returns ``IO[Any]`` which doesn't
    satisfy the protocol's ``BinaryIO`` annotation under mypy --strict.
    """

    fh = path.open("rb")
    try:
        yield _ensure_binary(fh)
    finally:
        fh.close()


def _ensure_binary(fh: io.IOBase) -> BinaryIO:
    """Cast a binary file handle to ``BinaryIO`` for typing.

    ``Path.open('rb')`` returns ``io.BufferedReader`` which is a
    ``BinaryIO`` at runtime but mypy infers ``IO[Any]``. Cast via the
    runtime check so we keep typing honest without an isinstance scan
    of the entire pathlib stub.
    """

    # io.BufferedReader is a concrete BinaryIO; the cast is safe given the
    # caller always opens in binary mode.
    return fh  # type: ignore[return-value]
