"""Smoke test against a real vLLM (OpenAI-compatible) endpoint.

Skipped by default. Run with::

    RUN_GEMMA_REAL_TESTS=1 LLM_BASE_URL=http://<host>:8000/v1 pytest \
        codescan-backend/worker/tests/integration/test_gemma_real.py
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GEMMA_REAL_TESTS") != "1",
    reason="real-Gemma test, set RUN_GEMMA_REAL_TESTS=1 to run",
)


def test_security_scan_against_real_gemma() -> None:
    from worker.core.config import settings
    from worker.llm.client import GemmaClient

    assert settings.llm_base_url, "LLM_BASE_URL must be set"
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key is not None else None
    client = GemmaClient(
        base_url=settings.llm_base_url,
        api_key=api_key,
        model=settings.gemma_model,
    )
    result = client.scan_file(
        scan_type="security",
        relative_path="example.py",
        language="python",
        content='import os\npassword = "hunter2"\nos.system(f"echo {password}")\n',
    )
    assert result.tokens_in > 0
    assert result.tokens_out > 0
    assert result.latency_ms > 0
    for finding in result.findings:
        assert finding.severity in ("critical", "high", "medium", "low", "info")
        assert finding.line_start <= finding.line_end
