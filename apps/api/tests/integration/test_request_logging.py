"""End-to-end test for the T5.4 request middleware.

We assert two things — both via stdlib ``caplog`` against the
``app.access`` logger emitted by :class:`RequestLoggingMiddleware`:

1. Every request gets a ``request_id`` in the structured access line, and
   the response carries a matching ``X-Request-ID`` header.
2. Authenticated requests carry ``user_id`` (set inside ``get_current_user``).
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.core.logging import (
    ApiKeyScrubFilter,
    JsonFormatter,
    request_id_var,
    user_id_var,
)


@pytest.fixture
def captured_access_log(
    caplog: pytest.LogCaptureFixture,
) -> pytest.LogCaptureFixture:
    """Capture the ``app.access`` logger at INFO with our JSON formatter.

    The middleware emits via ``logger.info(...)`` with extras; ``caplog``
    captures the LogRecord — we format it ourselves so the assertions read
    against the same shape an operator would see in production.
    """

    caplog.set_level(logging.INFO, logger="app.access")
    return caplog


def _formatted_access_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    fmt = JsonFormatter()
    scrub = ApiKeyScrubFilter()
    payloads: list[dict[str, object]] = []
    for record in caplog.records:
        if record.name != "app.access":
            continue
        scrub.filter(record)
        payloads.append(json.loads(fmt.format(record)))
    return payloads


async def test_healthz_request_logs_request_id_and_response_header_match(
    client: httpx.AsyncClient,
    captured_access_log: pytest.LogCaptureFixture,
) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id is not None and len(request_id) == 32

    lines = _formatted_access_lines(captured_access_log)
    assert any(
        line.get("method") == "GET"
        and line.get("path") == "/healthz"
        and line.get("status") == 200
        and line.get("request_id") == request_id
        and isinstance(line.get("latency_ms"), int)
        for line in lines
    ), f"no matching access line found in {lines}"


async def test_authed_request_logs_user_id(
    authed_client: httpx.AsyncClient,
    captured_access_log: pytest.LogCaptureFixture,
) -> None:
    """``get_current_user`` stamps the user_id contextvar, which the
    middleware-emitted access line then carries."""

    response = await authed_client.get("/api/v1/auth/me")
    assert response.status_code == 200

    lines = _formatted_access_lines(captured_access_log)
    me_lines = [line for line in lines if line.get("path") == "/api/v1/auth/me"]
    assert me_lines, f"no /me access line in {lines}"
    line = me_lines[-1]
    assert line.get("status") == 200
    assert "user_id" in line, f"user_id missing from {line}"
    assert isinstance(line["user_id"], str)


async def test_request_id_header_is_reused_when_well_formed(
    client: httpx.AsyncClient,
    captured_access_log: pytest.LogCaptureFixture,
) -> None:
    response = await client.get(
        "/healthz",
        headers={"X-Request-ID": "trace-abc-123_XYZ"},
    )
    assert response.headers.get("X-Request-ID") == "trace-abc-123_XYZ"

    lines = _formatted_access_lines(captured_access_log)
    assert any(line.get("request_id") == "trace-abc-123_XYZ" for line in lines)


async def test_request_id_header_replaced_when_malicious(
    client: httpx.AsyncClient,
    captured_access_log: pytest.LogCaptureFixture,
) -> None:
    """A newline / oversized header must not propagate into logs or response.

    Validated by ``_coerce_request_id`` per the unit tests; this is the
    end-to-end check that the middleware actually applies the coercion.
    """

    # httpx + h11 reject literal "\n" in headers at send time, so we use a
    # value that's invalid by content (too long) but valid as an HTTP header.
    response = await client.get("/healthz", headers={"X-Request-ID": "x" * 65})
    issued = response.headers.get("X-Request-ID")
    assert issued is not None
    assert issued != "x" * 65
    assert len(issued) == 32  # uuid hex was generated instead


async def test_contextvars_clear_between_requests(
    client: httpx.AsyncClient,
) -> None:
    """Hitting the API must not leak request_id / user_id into the outer
    test process's context."""

    # ContextVar default is ``None`` — verify it's still None after a request
    # round-trips through the middleware.
    assert request_id_var.get() is None
    assert user_id_var.get() is None
    await client.get("/healthz")
    assert request_id_var.get() is None
    assert user_id_var.get() is None
