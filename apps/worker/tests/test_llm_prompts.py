"""Prompt loader tests — files exist, contain the canonical sentinels, and cache."""

from __future__ import annotations

import pytest

from worker.llm.prompts import load_prompt


def test_security_prompt_loads_and_contains_contract() -> None:
    text = load_prompt("security")
    assert text
    assert "Respond ONLY with JSON" in text
    assert '"findings"' in text
    assert '"severity"' in text


def test_bugs_prompt_loads_and_contains_severity_rubric() -> None:
    text = load_prompt("bugs")
    assert text
    assert "Respond ONLY with JSON" in text
    assert '"findings"' in text
    # The bug-report rubric is distinct from security and worth pinning.
    assert "off-by-one" in text
    assert "race condition" in text


def test_keywords_scan_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown scan_type"):
        load_prompt("keywords")


def test_unknown_version_raises() -> None:
    with pytest.raises(ValueError, match="unknown prompt version"):
        load_prompt("security", version="v999")


def test_lru_cache_returns_same_object() -> None:
    a = load_prompt("security")
    b = load_prompt("security")
    assert a is b
