"""Copy of ``apps/api/app/core/file_types.py``.

The api package is the canonical source of truth (see docs/FILE_HANDLING.md
"one source of truth, also imported by worker"). The worker keeps a copy
because:

- the worker Docker image only includes ``apps/worker`` in its build context,
  so a ``path = "../api"`` editable dep would break the docker build;
- the worker runs synchronously and shouldn't pull in api's async
  SQLAlchemy / FastAPI machinery just to read a frozen set.

Drift is prevented by ``apps/worker/tests/test_file_types_parity.py`` which
reads both files at runtime and asserts ``frozenset`` equality. If you change
one, change the other in the same PR.
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
        # Config / data
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

ALLOWED_LOOSE_FILENAMES: frozenset[str] = frozenset(
    {
        "dockerfile",
        "makefile",
    }
)

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

FILENAME_TO_LANGUAGE: dict[str, str] = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
}


def _split_basename(name: str) -> tuple[str, str]:
    base = os.path.basename(name).lower()
    _, ext = os.path.splitext(base)
    if ext.startswith("."):
        ext = ext[1:]
    return base, ext


def is_allowed_loose_extension(name: str) -> bool:
    """Return True iff ``name`` is acceptable for a ``kind=loose`` upload."""

    if not name:
        return False
    base, ext = _split_basename(name)
    if ext and ext in ALLOWED_LOOSE_EXTENSIONS:
        return True
    return base in ALLOWED_LOOSE_FILENAMES


def detect_language(name: str) -> str | None:
    """Return the language slug for ``name`` or ``None`` if unknown."""

    if not name:
        return None
    base, ext = _split_basename(name)
    if base in FILENAME_TO_LANGUAGE:
        return FILENAME_TO_LANGUAGE[base]
    if ext and ext in EXTENSION_TO_LANGUAGE:
        return EXTENSION_TO_LANGUAGE[ext]
    return None
