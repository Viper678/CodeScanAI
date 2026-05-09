"""Unit tests for the static-fixture transport used by the e2e suite (T5.5).

These verify that the mock returns parseable canned bodies and that the
scan-type sniff routes correctly given the shipped v1 system prompts.
"""

from __future__ import annotations

import json

from worker.llm.client import GemmaClient
from worker.llm.mock_transport import MockGemmaTransport
from worker.llm.prompts import load_prompt


def _scan_with(scan_type: str) -> dict[str, object]:
    transport = MockGemmaTransport()
    client = GemmaClient(api_key="placeholder", transport=transport)
    result = client.scan_file(
        scan_type=scan_type,  # type: ignore[arg-type]
        relative_path="hello.py",
        language="python",
        content="x = 1\nprint(x)\n",
    )
    return {
        "count": len(result.findings),
        "titles": [f.title for f in result.findings],
        "severities": [f.severity for f in result.findings],
    }


def test_security_prompt_returns_security_finding() -> None:
    out = _scan_with("security")
    assert out["count"] == 1
    titles = out["titles"]
    assert isinstance(titles, list)
    assert "API key" in titles[0]


def test_bugs_prompt_returns_bug_finding() -> None:
    out = _scan_with("bugs")
    assert out["count"] == 1
    titles = out["titles"]
    assert isinstance(titles, list)
    assert "null" in titles[0].lower()


def test_unknown_system_prompt_returns_empty() -> None:
    """Defensive: a future prompt revision that drops both keywords degrades
    cleanly to no findings rather than mis-routing."""

    transport = MockGemmaTransport()
    raw = transport(
        model="gemma-4-31b-it",
        system_prompt="You are a generic assistant.",
        user_prompt="File: a.py\nLanguage: python\n\n```python\nx = 1\n```\n",
        temperature=0.0,
        max_output_tokens=4096,
    )
    parsed = json.loads(raw.text)
    assert parsed == {"findings": []}


def test_security_prompt_text_is_actually_routed() -> None:
    """End-to-end smoke: feed the real v1 security prompt to the transport."""

    transport = MockGemmaTransport()
    raw = transport(
        model="gemma-4-31b-it",
        system_prompt=load_prompt("security", version="v1"),
        user_prompt="File: a.py\nLanguage: python\n\n```python\nx = 1\n```\n",
        temperature=0.0,
        max_output_tokens=4096,
    )
    body = json.loads(raw.text)
    assert body["findings"][0]["severity"] == "high"
