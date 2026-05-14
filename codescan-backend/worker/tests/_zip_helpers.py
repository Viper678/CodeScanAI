"""Tiny helpers for constructing zip files in worker tests."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path


def write_zip(path: Path, entries: dict[str, bytes | str]) -> Path:
    """Write a real (deflated) zip with the given entries to ``path``."""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in entries.items():
            data = body.encode("utf-8") if isinstance(body, str) else body
            zf.writestr(name, data)
    path.write_bytes(buf.getvalue())
    return path
