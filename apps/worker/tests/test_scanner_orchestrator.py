"""Unit tests for orchestrator components that don't need a real DB.

The end-to-end test (DB + thread pool + Celery task body) lives under
``tests/integration/test_run_scan.py``. Here we verify pure logic: pre-flight
skip rules, keyword config parsing, per-file scanner dispatch, error
aggregation, and the per-file outcome math.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from worker.core.config import settings
from worker.scanners.base import (
    Finding,
    KeywordsConfig,
    ScanCallResult,
    ScanContext,
    Scanner,
)
from worker.tasks.run_scan import (
    _aggregate_usage_from_rows,
    _FilePlan,
    _parse_keywords,
    _preflight_skip,
    _process_file_no_db,
)

# ---- Pre-flight skip --------------------------------------------------------


def _plan(tmp_path: Path, *, content: str = "x", is_binary: bool = False) -> _FilePlan:
    f = tmp_path / "a.py"
    f.write_text(content)
    return _FilePlan(
        scan_file_id=uuid4(),
        file_id=uuid4(),
        relative_path="a.py",
        abs_path=f,
        language="python",
        size_bytes=f.stat().st_size,
        is_binary=is_binary,
    )


def test_preflight_skips_binary(tmp_path: Path) -> None:
    plan = _plan(tmp_path, is_binary=True)
    assert _preflight_skip(plan) == "binary"


def test_preflight_skips_oversize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_scan_file_size_mb", 0)  # 0 MB cap → 0 bytes
    plan = _plan(tmp_path, content="hello")
    assert _preflight_skip(plan) == "oversize"


def test_preflight_skips_too_large_for_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_scan_file_size_mb", 100)
    monkeypatch.setattr(settings, "gemma_max_input_tokens", 1)
    plan = _plan(tmp_path, content="long content here exceeds 4 chars")
    assert _preflight_skip(plan) == "too_large_for_context"


def test_preflight_passes_normal(tmp_path: Path) -> None:
    plan = _plan(tmp_path, content="def f(): pass\n")
    assert _preflight_skip(plan) is None


def test_preflight_missing_file(tmp_path: Path) -> None:
    plan = _FilePlan(
        scan_file_id=uuid4(),
        file_id=uuid4(),
        relative_path="missing.py",
        abs_path=tmp_path / "missing.py",
        language="python",
        size_bytes=10,
        is_binary=False,
    )
    assert _preflight_skip(plan) == "missing"


# ---- Keyword config parsing -------------------------------------------------


def test_parse_keywords_typical() -> None:
    cfg = _parse_keywords({"items": ["TODO", "fixme"], "case_sensitive": True, "regex": False})
    assert cfg is not None
    assert cfg.items == ["TODO", "fixme"]
    assert cfg.case_sensitive is True
    assert cfg.regex is False


def test_parse_keywords_empty_dict_returns_none() -> None:
    assert _parse_keywords({}) is None


def test_parse_keywords_none_input() -> None:
    assert _parse_keywords(None) is None


def test_parse_keywords_defaults_for_missing_flags() -> None:
    cfg = _parse_keywords({"items": ["a"]})
    assert cfg is not None
    assert cfg.case_sensitive is False
    assert cfg.regex is False


# ---- Per-file dispatch logic (DB-free variant) ------------------------------


class _OkScanner:
    name = "ok"

    def scan_file(self, content: str, ctx: ScanContext) -> ScanCallResult:
        return ScanCallResult(
            findings=[
                Finding(
                    title="t",
                    message="m",
                    recommendation=None,
                    severity="medium",
                    line_start=1,
                    line_end=1,
                    rule_id="R1",
                    confidence=0.9,
                )
            ],
            tokens_in=10,
            tokens_out=20,
            latency_ms=5,
        )


class _BoomScanner:
    name = "boom"

    def scan_file(self, content: str, ctx: ScanContext) -> ScanCallResult:
        raise RuntimeError("simulated scanner failure")


def test_process_file_no_db_one_success_one_failure(tmp_path: Path) -> None:
    """Mixed result: one scanner succeeds, one raises → status=done with errors recorded."""

    src = tmp_path / "x.py"
    src.write_text("print(1)\n")
    plan = _FilePlan(
        scan_file_id=uuid4(),
        file_id=uuid4(),
        relative_path="x.py",
        abs_path=src,
        language="python",
        size_bytes=src.stat().st_size,
        is_binary=False,
    )
    registry: dict[str, Scanner] = {"ok": _OkScanner(), "boom": _BoomScanner()}
    outcome = _process_file_no_db(
        plan,
        scan_types=["ok", "boom"],
        keywords_cfg=None,
        registry=registry,
    )
    assert outcome.final_status == "done"
    assert outcome.tokens_in == 10
    assert outcome.tokens_out == 20
    assert "ok" in outcome.findings_by_type
    assert "boom" in outcome.errors


def test_process_file_no_db_all_fail(tmp_path: Path) -> None:
    src = tmp_path / "x.py"
    src.write_text("print(1)\n")
    plan = _FilePlan(
        scan_file_id=uuid4(),
        file_id=uuid4(),
        relative_path="x.py",
        abs_path=src,
        language="python",
        size_bytes=src.stat().st_size,
        is_binary=False,
    )
    registry: dict[str, Scanner] = {"boom": _BoomScanner()}
    outcome = _process_file_no_db(
        plan,
        scan_types=["boom"],
        keywords_cfg=None,
        registry=registry,
    )
    assert outcome.final_status == "failed"
    assert outcome.final_error and "boom" in outcome.final_error


def test_process_file_no_db_keyword_scanner_uses_ctx(tmp_path: Path) -> None:
    src = tmp_path / "k.py"
    src.write_text("# TODO me\n# nothing\n")
    plan = _FilePlan(
        scan_file_id=uuid4(),
        file_id=uuid4(),
        relative_path="k.py",
        abs_path=src,
        language="python",
        size_bytes=src.stat().st_size,
        is_binary=False,
    )
    from worker.scanners.keywords import KeywordScanner

    registry: dict[str, Scanner] = {"keywords": KeywordScanner()}
    outcome = _process_file_no_db(
        plan,
        scan_types=["keywords"],
        keywords_cfg=KeywordsConfig(items=["TODO"], case_sensitive=False, regex=False),
        registry=registry,
    )
    assert outcome.final_status == "done"
    assert len(outcome.findings_by_type["keywords"]) == 1


# ---- Usage aggregation arithmetic ------------------------------------------


def test_aggregate_usage_sums_and_counts() -> None:
    # rows shape: (sum_tokens_in, sum_tokens_out, files_with_calls)
    usage = _aggregate_usage_from_rows(
        100, 200, files_with_calls=3, scan_types=["security", "bugs"]
    )
    assert usage == {"total_tokens_in": 100, "total_tokens_out": 200, "calls": 6}


def test_aggregate_usage_keywords_only_zero_calls() -> None:
    usage = _aggregate_usage_from_rows(0, 0, files_with_calls=0, scan_types=["keywords"])
    assert usage == {"total_tokens_in": 0, "total_tokens_out": 0, "calls": 0}


def test_aggregate_usage_only_security_selected() -> None:
    usage = _aggregate_usage_from_rows(50, 60, files_with_calls=2, scan_types=["security"])
    assert usage == {"total_tokens_in": 50, "total_tokens_out": 60, "calls": 2}
