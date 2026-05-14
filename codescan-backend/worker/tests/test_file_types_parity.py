"""Guard: worker file_types must equal the api source of truth.

Per docs/FILE_HANDLING.md the api owns the whitelist. The worker keeps a
copy because the worker Docker image doesn't include ``apps/api`` in its
build context. This test reads both files at runtime and asserts the
allowed-extension and language-map data structures match exactly.

If you change one, change the other in the same PR.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

WORKER_ROOT = Path(__file__).resolve().parents[1]
API_FILE_TYPES = WORKER_ROOT.parent / "api" / "app" / "core" / "file_types.py"


def _load_api_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("api_file_types", API_FILE_TYPES)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_allowed_loose_extensions_match() -> None:
    api = _load_api_module()
    from worker.core import file_types as worker

    assert worker.ALLOWED_LOOSE_EXTENSIONS == api.ALLOWED_LOOSE_EXTENSIONS


def test_allowed_loose_filenames_match() -> None:
    api = _load_api_module()
    from worker.core import file_types as worker

    assert worker.ALLOWED_LOOSE_FILENAMES == api.ALLOWED_LOOSE_FILENAMES


def test_extension_to_language_match() -> None:
    api = _load_api_module()
    from worker.core import file_types as worker

    assert worker.EXTENSION_TO_LANGUAGE == api.EXTENSION_TO_LANGUAGE


def test_filename_to_language_match() -> None:
    api = _load_api_module()
    from worker.core import file_types as worker

    assert worker.FILENAME_TO_LANGUAGE == api.FILENAME_TO_LANGUAGE
