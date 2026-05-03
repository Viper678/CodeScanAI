from __future__ import annotations

import pytest

from app.core.file_types import (
    ALLOWED_LOOSE_EXTENSIONS,
    is_allowed_loose_extension,
)


@pytest.mark.parametrize(
    "name",
    [
        "main.py",
        "Component.tsx",
        "weird-name.with.dots.go",
        "Dockerfile",
        "MAKEFILE",
        "deep/path/ignored/main.py",  # caller is responsible for stripping path
    ],
)
def test_is_allowed_loose_extension_accepts_known_types(name: str) -> None:
    assert is_allowed_loose_extension(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "",
        "binary.exe",
        "image.png",
        "archive.zip",
        "secrets.pem",
        "no-extension",
        "..",
    ],
)
def test_is_allowed_loose_extension_rejects_unknown_types(name: str) -> None:
    assert is_allowed_loose_extension(name) is False


def test_extension_set_has_no_dots() -> None:
    # Trips a regression where an entry slips in with a leading dot — the
    # comparison code strips dots from inputs only.
    for ext in ALLOWED_LOOSE_EXTENSIONS:
        assert not ext.startswith(".")
        assert ext == ext.lower()
