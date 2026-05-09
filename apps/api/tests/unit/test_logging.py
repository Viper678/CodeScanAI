"""Unit tests for the structured-logging primitives (T5.4).

Pure-Python tests against ``app.core.logging`` — no FastAPI / TestClient.
The integration of the middleware end-to-end is covered separately under
``tests/integration/test_request_logging.py``.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.core.logging import (
    ApiKeyScrubFilter,
    CorrelationFilter,
    JsonFormatter,
    _coerce_request_id,
    request_id_var,
    user_id_var,
)


def _record(
    *,
    level: int = logging.INFO,
    msg: str = "hello",
    args: tuple[object, ...] | None = None,
    extra: dict[str, object] | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args or (),
        exc_info=None,
    )
    if extra:
        for key, value in extra.items():
            record.__dict__[key] = value
    return record


# ---- JsonFormatter ---------------------------------------------------------


def test_formatter_emits_required_fields() -> None:
    record = _record(msg="upload received", args=("abc",))
    record.msg = "upload received: %s"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "upload received: abc"
    # ISO8601 timestamp ends with timezone (UTC offset).
    assert payload["timestamp"].endswith("+00:00")


def test_formatter_omits_correlation_keys_when_unset() -> None:
    payload = json.loads(JsonFormatter().format(_record()))
    assert "request_id" not in payload
    assert "user_id" not in payload


def test_formatter_includes_request_id_when_filter_runs() -> None:
    token = request_id_var.set("abc123")
    try:
        record = _record()
        CorrelationFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert payload["request_id"] == "abc123"


def test_formatter_includes_user_id_when_filter_runs() -> None:
    user_token = user_id_var.set("user-uuid")
    try:
        record = _record()
        CorrelationFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        user_id_var.reset(user_token)
    assert payload["user_id"] == "user-uuid"


def test_correlation_filter_snapshots_at_emit_time() -> None:
    """Verify the snapshot semantic — the contextvar value at filter-time
    sticks to the record even after the contextvar is reset later."""

    record = _record()
    token = request_id_var.set("captured")
    try:
        CorrelationFilter().filter(record)
    finally:
        request_id_var.reset(token)
    # Contextvar is back to None, but the record carries the snapshot.
    assert request_id_var.get() is None
    payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "captured"


def test_formatter_passes_extra_kwargs_through() -> None:
    record = _record(extra={"method": "GET", "status": 200, "latency_ms": 7})
    payload = json.loads(JsonFormatter().format(record))
    assert payload["method"] == "GET"
    assert payload["status"] == 200
    assert payload["latency_ms"] == 7


def test_formatter_drops_builtin_record_attrs() -> None:
    payload = json.loads(JsonFormatter().format(_record()))
    # ``filename`` / ``pathname`` / ``module`` would just leak the call site.
    assert "filename" not in payload
    assert "pathname" not in payload
    assert "module" not in payload


# ---- ApiKeyScrubFilter -----------------------------------------------------


_FAKE_KEY = "AIza" + "x" * 35  # matches the regex shape; not a real key


def test_scrub_filter_redacts_msg() -> None:
    record = _record(msg=f"key leaked: {_FAKE_KEY}")
    ApiKeyScrubFilter().filter(record)
    assert _FAKE_KEY not in record.msg
    assert "AIza<redacted>" in record.msg


def test_scrub_filter_redacts_args() -> None:
    record = _record(msg="key=%s status=%s", args=(_FAKE_KEY, 200))
    ApiKeyScrubFilter().filter(record)
    assert record.args is not None
    assert _FAKE_KEY not in record.getMessage()
    assert "AIza<redacted>" in record.getMessage()


def test_scrub_filter_redacts_extras_recursively() -> None:
    record = _record(
        extra={"context": {"nested": [f"prefix {_FAKE_KEY} suffix", "ok"]}},
    )
    ApiKeyScrubFilter().filter(record)
    nested = record.__dict__["context"]["nested"]
    assert _FAKE_KEY not in nested[0]
    assert "AIza<redacted>" in nested[0]
    assert nested[1] == "ok"


def test_scrub_filter_leaves_non_string_args_alone() -> None:
    record = _record(msg="status=%d count=%d", args=(200, 42))
    ApiKeyScrubFilter().filter(record)
    assert record.args == (200, 42)


# ---- Request-ID coercion ---------------------------------------------------


def test_request_id_generated_when_header_missing() -> None:
    rid = _coerce_request_id(None)
    # uuid4().hex is 32 lowercase hex chars.
    assert len(rid) == 32
    assert all(c in "0123456789abcdef" for c in rid)


def test_request_id_reused_when_header_valid() -> None:
    assert _coerce_request_id("abc-123_XYZ") == "abc-123_XYZ"
    assert _coerce_request_id("a" * 64) == "a" * 64


@pytest.mark.parametrize(
    "bad",
    [
        "has spaces",
        "has\nnewline",
        "has\rcarriage",
        ":has-colon",
        "x" * 65,  # too long
        "",
        "name@with-at",
    ],
)
def test_request_id_rejected_when_header_invalid(bad: str) -> None:
    """Anything outside ``[A-Za-z0-9_-]{1,64}`` is rejected — newlines etc
    would let a malicious caller inject characters that break the JSON line
    boundary in log aggregators."""

    rid = _coerce_request_id(bad)
    # We don't echo the bad value back; we generate a fresh one.
    assert rid != bad
    assert len(rid) == 32
