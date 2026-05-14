"""Versioned system-prompt loader for the Gemma scanners.

Prompts live as plain ``.txt`` files under ``worker/llm/prompts/<version>/``
so they can be reviewed, diffed, and bumped independently of code. The
``PROMPT_VERSION`` constant is what the orchestrator records on
``scans.model_settings`` for reproducibility (docs/SCAN_RULES.md
§"Determinism / reproducibility").

``load_prompt`` is ``lru_cache``-d so the file read happens once per worker
process per (scan_type, version) pair.
"""

from __future__ import annotations

import functools
from pathlib import Path

PROMPT_VERSION = "v1"
SCAN_TYPES_LLM: tuple[str, ...] = ("security", "bugs")

_PROMPTS_ROOT = Path(__file__).resolve().parent / "prompts"


@functools.lru_cache(maxsize=8)
def load_prompt(scan_type: str, *, version: str = PROMPT_VERSION) -> str:
    """Return the system prompt text for ``scan_type`` at ``version``.

    Raises:
        ValueError: ``scan_type`` is not an LLM scan type or ``version``
            does not correspond to a directory under ``prompts/``.
    """

    if scan_type not in SCAN_TYPES_LLM:
        raise ValueError(
            f"unknown scan_type for LLM prompts: {scan_type!r} "
            f"(expected one of {SCAN_TYPES_LLM})"
        )

    version_dir = _PROMPTS_ROOT / version
    if not version_dir.is_dir():
        raise ValueError(f"unknown prompt version: {version!r}")

    prompt_path = version_dir / f"{scan_type}.txt"
    if not prompt_path.is_file():
        raise ValueError(f"missing prompt file for scan_type={scan_type!r} version={version!r}")

    text = prompt_path.read_text(encoding="utf-8")
    return text.rstrip("\n") + "\n"
