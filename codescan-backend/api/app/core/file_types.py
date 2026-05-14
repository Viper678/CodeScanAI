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


# Extension → language label used by the worker's classifier and surfaced to
# the UI / scanner prompts. Lowercase ext (no dot) → canonical language slug.
# Keep in sync with ALLOWED_LOOSE_EXTENSIONS — extensions not in the whitelist
# can still be detected (e.g. inside a zip) but only the ones the user can
# upload loose are guaranteed coverage.
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    # Python
    "py": "python",
    "pyi": "python",
    "ipynb": "jupyter",
    # JS / TS
    "js": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    # JVM family
    "java": "java",
    "kt": "kotlin",
    "scala": "scala",
    "groovy": "groovy",
    # Systems
    "go": "go",
    "rs": "rust",
    # Scripting
    "rb": "ruby",
    "php": "php",
    # C / C++
    "c": "c",
    "h": "c",
    "cpp": "cpp",
    "hpp": "cpp",
    "cc": "cpp",
    "hh": "cpp",
    "cxx": "cpp",
    # .NET
    "cs": "csharp",
    "fs": "fsharp",
    "vb": "vbnet",
    # Apple
    "swift": "swift",
    "m": "objc",
    "mm": "objcpp",
    # Shell
    "sh": "shell",
    "bash": "shell",
    "zsh": "shell",
    "fish": "shell",
    "ps1": "powershell",
    # Database
    "sql": "sql",
    # Web
    "html": "html",
    "htm": "html",
    "css": "css",
    "scss": "scss",
    "less": "less",
    "vue": "vue",
    "svelte": "svelte",
    # Config / data
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "toml": "toml",
    "ini": "ini",
    "env": "env",
    # Docs
    "md": "markdown",
    "rst": "restructuredtext",
    "txt": "text",
    # Infra / IaC
    "dockerfile": "dockerfile",
    "tf": "terraform",
    "hcl": "hcl",
}

# Filenames (no extension) → language label.
FILENAME_TO_LANGUAGE: dict[str, str] = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
}


def detect_language(name: str) -> str | None:
    """Return the language slug for ``name`` or ``None`` if unknown.

    Resolution order:
    1. Filename match (``Dockerfile``, ``Makefile``).
    2. Extension match.
    """

    if not name:
        return None
    base, ext = _split_basename(name)
    if base in FILENAME_TO_LANGUAGE:
        return FILENAME_TO_LANGUAGE[base]
    if ext and ext in EXTENSION_TO_LANGUAGE:
        return EXTENSION_TO_LANGUAGE[ext]
    return None
