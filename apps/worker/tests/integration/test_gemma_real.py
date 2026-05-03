"""Smoke test against the real Gemma API.

Skipped by default. Run with::

    RUN_GEMMA_REAL_TESTS=1 GOOGLE_AI_API_KEY=... pytest \
        apps/worker/tests/integration/test_gemma_real.py
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

    api_key = settings.google_ai_api_key
    assert api_key is not None, "GOOGLE_AI_API_KEY must be set"
    client = GemmaClient(api_key=api_key.get_secret_value(), model=settings.gemma_model)
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
