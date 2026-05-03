"""Allowed source-code-like extensions for ``kind=loose`` uploads.

This is the single source of truth for which loose-file uploads we accept.
The worker imports the same module in T2.2 to derive ``is_excluded_by_default``
when classifying files inside an extracted archive (see docs/FILE_HANDLING.md).

Extensions are stored lowercase **without** the leading dot. Special filenames
without an extension (e.g. ``Dockerfile``) are matched against
``ALLOWED_LOOSE_FILENAMES``.
"""

from __future__ import annotations

import os

ALLOWED_LOOSE_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Python
        "py",
        "pyi",
        "ipynb",
        # JS / TS
        "js",
        "jsx",
        "ts",
        "tsx",
        "mjs",
        "cjs",
        # JVM family
        "java",
        "kt",
        "scala",
        "groovy",
        # Systems
        "go",
        "rs",
        # Scripting
        "rb",
        "php",
        # C / C++
        "c",
        "h",
        "cpp",
        "hpp",
        "cc",
        "hh",
        "cxx",
        # .NET
        "cs",
        "fs",
        "vb",
        # Apple
        "swift",
        "m",
        "mm",
        # Shell
        "sh",
        "bash",
        "zsh",
        "fish",
        "ps1",
        # Database
        "sql",
        # Web
        "html",
        "htm",
        "css",
        "scss",
        "less",
        "vue",
        "svelte",
        # Config / data (env intentionally allowed; security scanner inspects it)
        "json",
        "yaml",
        "yml",
        "toml",
        "ini",
        "env",
        # Docs
        "md",
        "rst",
        "txt",
        # Infra / IaC
        "dockerfile",
        "tf",
        "hcl",
    }
)

# Filenames without a recognized extension that we still accept.
ALLOWED_LOOSE_FILENAMES: frozenset[str] = frozenset(
    {
        "dockerfile",
        "makefile",
    }
)


def _split_basename(name: str) -> tuple[str, str]:
    """Return (lowercased basename, lowercased extension w/o leading dot)."""

    base = os.path.basename(name).lower()
    _, ext = os.path.splitext(base)
    if ext.startswith("."):
        ext = ext[1:]
    return base, ext


def is_allowed_loose_extension(name: str) -> bool:
    """Return True iff ``name`` is acceptable for a ``kind=loose`` upload.

    Decision is made purely from the basename. Path components are intentionally
    ignored so the caller is responsible for sanitizing path traversal first.
    """

    if not name:
        return False
    base, ext = _split_basename(name)
    if ext and ext in ALLOWED_LOOSE_EXTENSIONS:
        return True
    return base in ALLOWED_LOOSE_FILENAMES
