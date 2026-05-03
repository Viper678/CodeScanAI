"""Unit tests for ``GemmaClient`` — fake transports only, never imports google.genai."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from worker.llm.client import (
    MAX_OUTPUT_TOKENS,
    REPAIR_SUFFIX,
    TEMPERATURE,
    GemmaClient,
    RawResponse,
)
from worker.llm.retry import GemmaUnrecoverable, RetryPolicy

VALID_BODY = json.dumps(
    {
        "findings": [
            {
                "title": "Hardcoded secret",
                "message": "literal password in source",
                "recommendation": "use a secrets manager",
                "severity": "high",
                "line_start": 1,
                "line_end": 1,
                "rule_id": "CWE-798",
                "confidence": 0.9,
            }
        ]
    }
)
EMPTY_BODY = json.dumps({"findings": []})


@dataclass
class FakeTransport:
    """Captures call args; pops scripted RawResponses (or raises if Exception)."""

    responses: list[Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_output_tokens: int,
    ) -> RawResponse:
        self.calls.append(
            {
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            }
        )
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, RawResponse)
        return item


def _make_clock(*ticks: float) -> Callable[[], float]:
    it = iter(ticks)
    return lambda: next(it)


def _make_client(transport: FakeTransport, **overrides: Any) -> GemmaClient:
    kwargs: dict[str, Any] = {
        "api_key": "fake",
        "transport": transport,
        "sleep": MagicMock(),
        "clock": _make_clock(0.0, 0.123),
    }
    kwargs.update(overrides)
    return GemmaClient(**kwargs)


def test_happy_path_returns_parsed_findings_and_latency() -> None:
    transport = FakeTransport(
        responses=[RawResponse(text=VALID_BODY, tokens_in=100, tokens_out=42)]
    )
    client = _make_client(transport)

    result = client.scan_file(
        scan_type="security",
        relative_path="x.py",
        language="python",
        content="print(1)\n",
    )

    assert len(result.findings) == 1
    assert result.findings[0].title == "Hardcoded secret"
    assert result.tokens_in == 100
    assert result.tokens_out == 42
    assert result.latency_ms == 123

    # Transport got the scan_type's system prompt and the configured knobs.
    assert len(transport.calls) == 1
    sent = transport.calls[0]
    assert sent["temperature"] == TEMPERATURE
    assert sent["max_output_tokens"] == MAX_OUTPUT_TOKENS
    assert "Respond ONLY with JSON" in sent["system_prompt"]


def test_empty_findings_round_trips() -> None:
    transport = FakeTransport(responses=[RawResponse(text=EMPTY_BODY, tokens_in=10, tokens_out=5)])
    client = _make_client(transport)

    result = client.scan_file(
        scan_type="bugs", relative_path="x.py", language="python", content="x = 1\n"
    )

    assert result.findings == []
    assert result.tokens_in == 10
    assert result.tokens_out == 5


def test_invalid_json_then_repair_succeeds() -> None:
    transport = FakeTransport(
        responses=[
            RawResponse(text="not json at all", tokens_in=80, tokens_out=10),
            RawResponse(text=VALID_BODY, tokens_in=120, tokens_out=50),
        ]
    )
    client = _make_client(transport)

    result = client.scan_file(
        scan_type="security",
        relative_path="x.py",
        language="python",
        content="print(1)\n",
    )

    assert len(result.findings) == 1
    # Token reporting decision: we report ONLY the repair (final) call's tokens.
    assert result.tokens_in == 120
    assert result.tokens_out == 50

    # Repair prompt was suffixed with the canonical sentinel.
    assert len(transport.calls) == 2
    repair_prompt = transport.calls[1]["user_prompt"]
    assert repair_prompt.endswith(REPAIR_SUFFIX)
    assert "Your previous response was not valid JSON" in repair_prompt


def test_invalid_json_twice_raises_unrecoverable() -> None:
    transport = FakeTransport(
        responses=[
            RawResponse(text="not json", tokens_in=10, tokens_out=1),
            RawResponse(text="still not", tokens_in=11, tokens_out=2),
        ]
    )
    client = _make_client(transport)
    with pytest.raises(GemmaUnrecoverable, match="invalid_json"):
        client.scan_file(
            scan_type="security",
            relative_path="x.py",
            language="python",
            content="print(1)\n",
        )


def test_pydantic_validation_error_triggers_repair() -> None:
    bad = json.dumps(
        {
            "findings": [
                {
                    "title": "x",
                    "message": "y",
                    "severity": "hyper",  # invalid enum value
                    "line_start": 1,
                    "line_end": 1,
                }
            ]
        }
    )
    transport = FakeTransport(
        responses=[
            RawResponse(text=bad, tokens_in=10, tokens_out=1),
            RawResponse(text=VALID_BODY, tokens_in=20, tokens_out=2),
        ]
    )
    client = _make_client(transport)

    result = client.scan_file(
        scan_type="security", relative_path="x.py", language="python", content="x\n"
    )
    assert len(result.findings) == 1


def test_pydantic_validation_error_then_repair_fails() -> None:
    bad = json.dumps(
        {
            "findings": [
                {
                    "title": "x",
                    "message": "y",
                    "severity": "hyper",
                    "line_start": 1,
                    "line_end": 1,
                }
            ]
        }
    )
    transport = FakeTransport(
        responses=[
            RawResponse(text=bad, tokens_in=10, tokens_out=1),
            RawResponse(text=bad, tokens_in=10, tokens_out=1),
        ]
    )
    client = _make_client(transport)
    with pytest.raises(GemmaUnrecoverable, match="invalid_json"):
        client.scan_file(
            scan_type="security", relative_path="x.py", language="python", content="x\n"
        )


def test_user_prompt_line_numbering() -> None:
    transport = FakeTransport(responses=[RawResponse(text=EMPTY_BODY, tokens_in=1, tokens_out=1)])
    client = _make_client(transport)

    client.scan_file(
        scan_type="security",
        relative_path="x.py",
        language="python",
        content="a\nb\nc\n",
    )

    sent_prompt = transport.calls[0]["user_prompt"]
    assert "   1 │ a\n   2 │ b\n   3 │ c\n" in sent_prompt


def test_user_prompt_header_includes_path_and_language() -> None:
    transport = FakeTransport(responses=[RawResponse(text=EMPTY_BODY, tokens_in=1, tokens_out=1)])
    client = _make_client(transport)

    client.scan_file(
        scan_type="security",
        relative_path="src/app.py",
        language="python",
        content="x = 1\n",
    )
    prompt = transport.calls[0]["user_prompt"]
    assert prompt.startswith("File: src/app.py\nLanguage: python\n")


def test_user_prompt_header_unknown_language_when_none() -> None:
    transport = FakeTransport(responses=[RawResponse(text=EMPTY_BODY, tokens_in=1, tokens_out=1)])
    client = _make_client(transport)

    client.scan_file(
        scan_type="security",
        relative_path="weird.bin.txt",
        language=None,
        content="hi\n",
    )
    prompt = transport.calls[0]["user_prompt"]
    assert "Language: unknown" in prompt


def test_default_transport_not_constructed_when_one_is_injected() -> None:
    """Asserting indirectly: importing client must not have imported google.genai."""

    import sys

    transport = FakeTransport(responses=[RawResponse(text=EMPTY_BODY, tokens_in=1, tokens_out=1)])
    _make_client(transport)
    # The fake transport never triggers the lazy import either.
    assert "google.genai" not in sys.modules


def test_retry_policy_passed_through_to_call_with_retry() -> None:
    """Server errors are surfaced through the policy without crashing the client."""

    from worker.llm.retry import GemmaServerError

    transport = FakeTransport(
        responses=[
            GemmaServerError("first"),
            RawResponse(text=EMPTY_BODY, tokens_in=1, tokens_out=1),
        ]
    )
    sleep = MagicMock()
    client = GemmaClient(
        api_key="fake",
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=(0.1, 0.2, 0.4)),
        sleep=sleep,
        clock=_make_clock(0.0, 0.05),
    )
    result = client.scan_file(
        scan_type="security", relative_path="x.py", language="python", content="x\n"
    )
    assert result.findings == []
    sleep.assert_called_once_with(0.1)


def test_constructing_default_transport_requires_api_key() -> None:
    with pytest.raises(ValueError, match="api_key is required"):
        GemmaClient(api_key="")


def test_drops_findings_with_line_end_past_eof() -> None:
    body = json.dumps(
        {
            "findings": [
                {
                    "title": "in bounds",
                    "message": "ok",
                    "recommendation": None,
                    "severity": "low",
                    "line_start": 1,
                    "line_end": 2,
                    "rule_id": None,
                    "confidence": 0.5,
                },
                {
                    "title": "past EOF",
                    "message": "Gemma hallucinated a line beyond the file",
                    "recommendation": None,
                    "severity": "high",
                    "line_start": 5,
                    "line_end": 9,
                    "rule_id": None,
                    "confidence": 0.5,
                },
            ]
        }
    )
    transport = FakeTransport(responses=[RawResponse(text=body, tokens_in=10, tokens_out=5)])
    client = _make_client(transport)

    result = client.scan_file(
        scan_type="security",
        relative_path="x.py",
        language="python",
        content="a\nb\nc\n",  # 3 lines
    )

    assert [f.title for f in result.findings] == ["in bounds"]


def test_drops_all_findings_when_content_is_empty() -> None:
    body = json.dumps(
        {
            "findings": [
                {
                    "title": "phantom",
                    "message": "no file content but Gemma still reported a line",
                    "recommendation": None,
                    "severity": "info",
                    "line_start": 1,
                    "line_end": 1,
                    "rule_id": None,
                    "confidence": 0.1,
                }
            ]
        }
    )
    transport = FakeTransport(responses=[RawResponse(text=body, tokens_in=5, tokens_out=1)])
    client = _make_client(transport)

    result = client.scan_file(
        scan_type="security",
        relative_path="empty.py",
        language="python",
        content="",
    )

    assert result.findings == []


def test_prompt_version_is_threaded_through_to_load_prompt() -> None:
    transport = FakeTransport(responses=[RawResponse(text=VALID_BODY, tokens_in=1, tokens_out=1)])

    with pytest.raises(ValueError, match="version"):
        client = _make_client(transport, prompt_version="v999")
        client.scan_file(
            scan_type="security", relative_path="x.py", language="python", content="x\n"
        )
