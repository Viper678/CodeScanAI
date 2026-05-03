"""Unit tests for the keyword scanner."""

from __future__ import annotations

import pytest

from worker.scanners.base import KeywordsConfig, ScanContext
from worker.scanners.keywords import InvalidPattern, KeywordScanner, scan_keywords


def test_substring_case_insensitive_default() -> None:
    content = "TODO: refactor\n# fixme: bug\n"
    findings = scan_keywords(content, items=["TODO", "fixme"], case_sensitive=False, regex=False)
    assert len(findings) == 2
    titles = sorted(f.title for f in findings)
    assert titles == ["Keyword match: TODO", "Keyword match: fixme"]
    by_title = {f.title: f for f in findings}
    assert by_title["Keyword match: TODO"].line_start == 1
    assert by_title["Keyword match: fixme"].line_start == 2
    assert all(f.severity == "info" for f in findings)
    assert by_title["Keyword match: TODO"].rule_id == "KW:TODO"


def test_case_sensitive_filters_mismatched_case() -> None:
    content = "TODO: refactor\n# fixme: bug\n"
    findings = scan_keywords(content, items=["todo"], case_sensitive=True, regex=False)
    assert findings == []


def test_regex_mode_word_boundary() -> None:
    content = "buggy code\nbug here\n"
    findings = scan_keywords(content, items=[r"\bbug\w*"], case_sensitive=False, regex=True)
    assert len(findings) == 2
    lines = sorted(f.line_start for f in findings)
    assert lines == [1, 2]


def test_invalid_regex_raises() -> None:
    with pytest.raises(InvalidPattern) as excinfo:
        scan_keywords("anything", items=["[unterminated"], case_sensitive=False, regex=True)
    assert excinfo.value.term == "[unterminated"


def test_multiple_matches_in_one_file_each_get_own_finding() -> None:
    content = "x TODO 1\nx TODO 2\nx TODO 3\n"
    findings = scan_keywords(content, items=["TODO"], case_sensitive=False, regex=False)
    assert [f.line_start for f in findings] == [1, 2, 3]


def test_keyword_scanner_protocol_returns_scan_call_result() -> None:
    scanner = KeywordScanner()
    ctx = ScanContext(
        relative_path="src/main.py",
        language="python",
        keywords=KeywordsConfig(items=["TODO"], case_sensitive=False, regex=False),
    )
    result = scanner.scan_file("# TODO\nprint(1)\n", ctx)
    assert len(result.findings) == 1
    assert result.tokens_in == 0
    assert result.tokens_out == 0
    assert result.latency_ms >= 0


def test_keyword_scanner_with_no_keywords_ctx_returns_empty() -> None:
    scanner = KeywordScanner()
    ctx = ScanContext(relative_path="x", language=None, keywords=None)
    result = scanner.scan_file("anything", ctx)
    assert result.findings == []
