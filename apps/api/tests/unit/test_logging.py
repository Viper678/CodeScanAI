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


def test_formatter_redacts_api_key_in_extras_serialized_via_default_str() -> None:
    """Codex final round: an ``extra={"obj": some_object}`` where the
    object's ``__str__`` contains the key would otherwise leak through —
    the scrub filter walks ``record.__dict__`` for strings/dicts/lists,
    not arbitrary objects, so the object is added to ``payload`` as-is
    and ``json.dumps(..., default=str)`` stringifies it AFTER all
    scrubbing has run. The formatter applies the regex to the final
    serialized JSON line as a hard backstop. Mirrors the worker fix.
    """

    class _Carrier:
        def __str__(self) -> str:
            return f"err: key={_FAKE_KEY}"

    record = _record(extra={"obj": _Carrier()})
    ApiKeyScrubFilter().filter(record)
    serialized = JsonFormatter().format(record)
    assert _FAKE_KEY not in serialized, f"API key leaked through extras default=str: {serialized!r}"
    assert "AIza<redacted>" in serialized


def test_formatter_redacts_api_key_in_object_arg_after_interpolation() -> None:
    """Codex round-7 P1: an arg whose ``__str__`` contains the key bypasses
    the scrub filter (filter only walks string args). The key only
    materializes during ``record.getMessage()``'s ``%`` interpolation,
    which runs at format time. ``JsonFormatter`` must scrub the rendered
    message as a backstop. Mirrored from the worker copy.
    """

    class _LeakyError(Exception):
        def __str__(self) -> str:
            return f"https://api.example.com/?key={_FAKE_KEY}"

    record = _record(msg="upstream call failed: %s", args=(_LeakyError(),))
    ApiKeyScrubFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))
    assert (
        _FAKE_KEY not in payload["message"]
    ), f"API key leaked through %s interpolation: {payload['message']!r}"
    assert "AIza<redacted>" in payload["message"]


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
        # Trailing-newline edge: Python's ``$`` matches before a final
        # ``\n`` by default, so an ``re.match(r"^…$", "abc\n")`` succeeds.
        # We use ``fullmatch`` to reject this — pin the case here so a
        # future "simplification" doesn't reintroduce the leak.
        "abc\n",
        "abc\r",
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


# ---- Codex P1 follow-up: redact API keys in serialized exception text -------


def test_formatter_scrubs_api_key_in_exception_traceback() -> None:
    """Codex P1 follow-up: ``logger.exception`` serializes the exception
    via ``formatException``, which the scrub filter doesn't touch — so an
    API key embedded in the exception MESSAGE (e.g. a Gemma SDK
    ``HTTPError`` whose ``url`` includes the key) would leak into the
    ``exc`` field. The formatter applies the regex to the formatted text
    as a hard backstop. This test pins that down.
    """

    import sys

    leaky = "AIza" + "x" * 35
    try:
        raise RuntimeError(f"upstream call failed for key {leaky}")
    except RuntimeError:
        record = logging.LogRecord(
            name="app.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=0,
            msg="boom",
            args=None,
            exc_info=sys.exc_info(),
        )

    formatted = json.loads(JsonFormatter().format(record))
    assert "exc" in formatted
    assert leaky not in formatted["exc"], f"API key leaked into exc field: {formatted['exc']!r}"
    assert "AIza<redacted>" in formatted["exc"]


# ---- Codex P2b follow-up: uvicorn loggers wired into JSON handler -----------


def test_configure_logging_sets_handler_level_so_propagated_records_are_filtered() -> None:
    """Codex round-3 P3: setting only the ROOT LOGGER level isn't enough —
    Python checks ``record.levelno >= hdlr.level`` on each handler when
    walking the propagation chain (see ``Logger.callHandlers``). If the
    handler stays at ``NOTSET`` (0), an INFO record from a child logger
    with ``level=INFO`` will still reach the root handler even when we set
    the root level to ERROR. ``configure_logging`` must set the handler
    level so the LOG_LEVEL contract actually filters propagated traffic.
    """

    import io

    from app.core.logging import configure_logging

    configure_logging(level="error")
    root = logging.getLogger()
    assert root.handlers, "configure_logging must install a handler"
    handler = root.handlers[0]
    assert (
        handler.level == logging.ERROR
    ), f"handler must inherit the configured level (ERROR=40); got {handler.level}"

    # End-to-end: redirect the handler's stream to a buffer, emit an INFO
    # record from a child logger that has its own INFO level, and confirm
    # nothing lands in the buffer.
    buf = io.StringIO()
    assert isinstance(handler, logging.StreamHandler)
    original_stream = handler.stream
    handler.stream = buf
    try:
        child = logging.getLogger("propagation.test.child")
        child.setLevel(logging.INFO)
        child.info("this should not be emitted at LOG_LEVEL=error")
        child.error("this SHOULD be emitted")
    finally:
        handler.stream = original_stream

    output = buf.getvalue()
    assert (
        "should not be emitted" not in output
    ), f"INFO record bypassed handler level filter: {output!r}"
    assert "SHOULD be emitted" in output, f"ERROR record was filtered too aggressively: {output!r}"


def test_configure_logging_routes_uvicorn_error_through_root() -> None:
    """Codex P2b: Uvicorn configures ``uvicorn.error`` with its own
    handler + ``propagate=False`` BEFORE ``app.main`` is imported, which
    leaves startup / lifespan logs in plaintext. ``configure_logging``
    must strip those handlers and flip propagate back on so records
    reach our root JSON handler.
    """

    from app.core.logging import configure_logging

    # Simulate Uvicorn's pre-configuration: install a handler on
    # ``uvicorn.error`` and disable propagation, the way uvicorn.config does.
    uv_logger = logging.getLogger("uvicorn.error")
    uv_logger.addHandler(logging.NullHandler())
    uv_logger.propagate = False
    try:
        configure_logging(level="info")
        assert uv_logger.handlers == [], (
            f"uvicorn.error still has handlers after configure_logging: " f"{uv_logger.handlers!r}"
        )
        assert (
            uv_logger.propagate is True
        ), "uvicorn.error must propagate so records reach our root JSON handler"
        # Same treatment for the parent ``uvicorn`` logger.
        parent = logging.getLogger("uvicorn")
        assert parent.handlers == []
        assert parent.propagate is True
    finally:
        # Reset so unrelated tests aren't affected by our pre-config.
        for name in ("uvicorn", "uvicorn.error"):
            lg = logging.getLogger(name)
            lg.handlers = []
            lg.propagate = True
