"""Unit tests for orchestrator components that don't need a real DB.

The end-to-end test (DB + thread pool + Celery task body) lives under
``tests/integration/test_run_scan.py``. Here we verify pure logic: pre-flight
skip rules, keyword config parsing, per-file scanner dispatch, error
aggregation, and the per-file outcome math.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

import pytest

from worker.core.config import settings
from worker.core.logging import scan_id_var
from worker.scanners.base import (
    Finding,
    KeywordsConfig,
    ScanCallResult,
    ScanContext,
    Scanner,
)
from worker.storage.local import LocalStorage
from worker.tasks.run_scan import (
    _aggregate_usage_from_rows,
    _FilePlan,
    _parse_keywords,
    _preflight_skip,
    _process_file_no_db,
    run_scan,
)

# ---- Pre-flight skip --------------------------------------------------------


def _plan(
    tmp_path: Path, *, content: str = "x", is_binary: bool = False
) -> tuple[_FilePlan, LocalStorage]:
    """Construct a (_FilePlan, LocalStorage) pair backed by ``tmp_path``.

    The plan's key (``a.py``) is written via the returned LocalStorage so
    the test can hand the same storage to ``_preflight_skip`` /
    ``_process_file_no_db``. Returns the storage alongside so callers can
    chain assertions about the on-disk state.
    """

    storage = LocalStorage(tmp_path)
    storage.put_bytes("a.py", content.encode())
    plan = _FilePlan(
        scan_file_id=uuid4(),
        file_id=uuid4(),
        relative_path="a.py",
        key="a.py",
        language="python",
        size_bytes=len(content.encode()),
        is_binary=is_binary,
    )
    return plan, storage


def test_preflight_skips_binary(tmp_path: Path) -> None:
    plan, storage = _plan(tmp_path, is_binary=True)
    assert _preflight_skip(plan, storage) == "binary"


def test_preflight_skips_oversize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_scan_file_size_mb", 0)  # 0 MB cap → 0 bytes
    plan, storage = _plan(tmp_path, content="hello")
    assert _preflight_skip(plan, storage) == "oversize"


def test_preflight_skips_too_large_for_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_scan_file_size_mb", 100)
    monkeypatch.setattr(settings, "gemma_max_input_tokens", 1)
    plan, storage = _plan(tmp_path, content="long content here exceeds 4 chars")
    assert _preflight_skip(plan, storage) == "too_large_for_context"


def test_preflight_passes_normal(tmp_path: Path) -> None:
    plan, storage = _plan(tmp_path, content="def f(): pass\n")
    assert _preflight_skip(plan, storage) is None


def test_preflight_missing_file(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    plan = _FilePlan(
        scan_file_id=uuid4(),
        file_id=uuid4(),
        relative_path="missing.py",
        key="missing.py",
        language="python",
        size_bytes=10,
        is_binary=False,
    )
    assert _preflight_skip(plan, storage) == "missing"


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

    storage = LocalStorage(tmp_path)
    storage.put_bytes("x.py", b"print(1)\n")
    plan = _FilePlan(
        scan_file_id=uuid4(),
        file_id=uuid4(),
        relative_path="x.py",
        key="x.py",
        language="python",
        size_bytes=storage.size("x.py"),
        is_binary=False,
    )
    registry: dict[str, Scanner] = {"ok": _OkScanner(), "boom": _BoomScanner()}
    outcome = _process_file_no_db(
        plan,
        scan_types=["ok", "boom"],
        keywords_cfg=None,
        registry=registry,
        storage=storage,
    )
    assert outcome.final_status == "done"
    assert outcome.tokens_in == 10
    assert outcome.tokens_out == 20
    assert "ok" in outcome.findings_by_type
    assert "boom" in outcome.errors


def test_process_file_no_db_all_fail(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put_bytes("x.py", b"print(1)\n")
    plan = _FilePlan(
        scan_file_id=uuid4(),
        file_id=uuid4(),
        relative_path="x.py",
        key="x.py",
        language="python",
        size_bytes=storage.size("x.py"),
        is_binary=False,
    )
    registry: dict[str, Scanner] = {"boom": _BoomScanner()}
    outcome = _process_file_no_db(
        plan,
        scan_types=["boom"],
        keywords_cfg=None,
        registry=registry,
        storage=storage,
    )
    assert outcome.final_status == "failed"
    assert outcome.final_error and "boom" in outcome.final_error


def test_process_file_no_db_keyword_scanner_uses_ctx(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.put_bytes("k.py", b"# TODO me\n# nothing\n")
    plan = _FilePlan(
        scan_file_id=uuid4(),
        file_id=uuid4(),
        relative_path="k.py",
        key="k.py",
        language="python",
        size_bytes=storage.size("k.py"),
        is_binary=False,
    )
    from worker.scanners.keywords import KeywordScanner

    registry: dict[str, Scanner] = {"keywords": KeywordScanner()}
    outcome = _process_file_no_db(
        plan,
        scan_types=["keywords"],
        keywords_cfg=KeywordsConfig(items=["TODO"], case_sensitive=False, regex=False),
        registry=registry,
        storage=storage,
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


# ---- Default scanner registry -----------------------------------------------


def test_default_registry_keywords_only_does_not_construct_gemma_client() -> None:
    """Keyword-only scans must not construct the LLM client (codex P2 on PR #20).

    Originally this test pinned that ``GOOGLE_AI_API_KEY`` could be unset; the
    invariant survived the M1 swap to vLLM unchanged — the registry function
    gates LLM construction on ``needs_llm``, and ``llm_base_url`` always has
    a default so it's never ``None``.
    """

    from worker.tasks.run_scan import _default_scanner_registry

    registry = _default_scanner_registry(["keywords"], None)

    assert set(registry.keys()) == {"keywords"}


def test_default_registry_only_security_constructs_security_only() -> None:
    from worker.tasks.run_scan import _default_scanner_registry

    registry = _default_scanner_registry(["security"], None)

    assert set(registry.keys()) == {"security"}


# ---- Delete-during-scan race handling ---------------------------------------


def test_run_scan_swallows_mid_run_disappearance_and_logs_info(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Benign race: user deleted the upload while the scan was running, the DB
    cascade dropped the scan row mid-run, and ``_run`` raised the sentinel
    ``LookupError("scan disappeared mid-run: <id>")``. The task body must
    catch it, log at INFO, and return ``None`` so Celery doesn't surface a
    spurious ERROR + traceback for what is user-initiated cleanup.

    The ``scan_id_var`` is seeded explicitly so the worker's LogRecord factory
    attaches ``scan_id`` to every record — same shape as production. This also
    pins a real regression: if anyone re-adds ``scan_id`` to the ``extra=``
    dict, Python's logging raises ``KeyError`` on the overwrite and the
    swallow-and-return-None path collapses back into a Celery ERROR.
    """

    scan_id = str(uuid4())

    def _fake_run(scan_id_arg: str, **_kwargs: object) -> dict[str, object]:
        raise LookupError(f"scan disappeared mid-run: {scan_id_arg}")

    monkeypatch.setattr("worker.tasks.run_scan._run", _fake_run)

    token = scan_id_var.set(scan_id)
    try:
        caplog.set_level(logging.INFO, logger="worker.tasks.run_scan")
        result = run_scan(scan_id)
    finally:
        scan_id_var.reset(token)

    assert result is None
    matching = [
        rec
        for rec in caplog.records
        if rec.levelno == logging.INFO and rec.message == "scan deleted by user mid-run, no-op"
    ]
    assert matching, "expected an INFO log on the benign delete-mid-run race"
    record = matching[0]
    # ``scan_id`` is contributed by the LogRecord factory snapshotting
    # ``scan_id_var``; ``reason`` is the only field this code path adds.
    assert getattr(record, "scan_id", None) == scan_id
    assert "scan disappeared mid-run" in getattr(record, "reason", "")


def test_run_scan_rethrows_other_lookup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discriminator check: only the sentinel mid-run prefix is swallowed.

    ``_run`` also raises ``LookupError("scan not found: <id>")`` when the scan
    id doesn't resolve at task start — that's a real bug (probably a stale
    Celery message), so the task body must re-raise so Celery's failure
    handler logs an ERROR.
    """

    scan_id = str(uuid4())

    def _fake_run(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise LookupError(f"scan not found: {scan_id}")

    monkeypatch.setattr("worker.tasks.run_scan._run", _fake_run)

    with pytest.raises(LookupError, match="scan not found"):
        run_scan(scan_id)
