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


async def test_cors_exposes_request_id_header_for_browser_clients(
    client: httpx.AsyncClient,
) -> None:
    """Codex P3: with credentialed CORS, browsers can only read response
    headers listed in ``Access-Control-Expose-Headers`` AND can only send
    ones listed in ``Access-Control-Allow-Headers``. ``X-Request-ID`` must
    be in both or the JS frontend can't read the echoed id (even though
    it's on the wire) or forward an upstream id from the gateway.

    We assert two responses: the OPTIONS preflight echoes the allow list,
    and the actual GET response echoes the expose list (Starlette splits
    them across the two response types).
    """

    # 1. Preflight: ``Access-Control-Allow-Headers`` must include the header.
    preflight = await client.options(
        "/healthz",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Request-ID",
        },
    )
    assert preflight.status_code == 200
    allow = preflight.headers.get("Access-Control-Allow-Headers", "")
    assert "X-Request-ID" in allow, f"X-Request-ID missing from preflight Allow-Headers: {allow!r}"

    # 2. Actual response: ``Access-Control-Expose-Headers`` must include it.
    response = await client.get("/healthz", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    expose = response.headers.get("Access-Control-Expose-Headers", "")
    assert (
        "X-Request-ID" in expose
    ), f"X-Request-ID missing from response Expose-Headers: {expose!r}"


async def test_unhandled_500_from_authed_route_logs_user_id(
    authed_client: httpx.AsyncClient,
    captured_access_log: pytest.LogCaptureFixture,
) -> None:
    """Codex P2a follow-up: an authenticated route that raises after
    ``get_current_user`` has stamped ``request.state.user_id`` should still
    produce an access line carrying that ``user_id``. Otherwise 500s from
    authed requests lose the user correlation operators rely on for
    triage.
    """

    from fastapi import Depends

    from app.core.deps import get_current_user
    from app.main import app

    @app.get("/__test_authed_boom__", dependencies=[Depends(get_current_user)])
    async def authed_boom() -> None:
        raise RuntimeError("simulated unhandled error from authed route")

    try:
        response = await authed_client.get("/__test_authed_boom__")
    finally:
        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) != "/__test_authed_boom__"
        ]

    assert response.status_code == 500
    lines = _formatted_access_lines(captured_access_log)
    err_lines = [line for line in lines if line.get("path") == "/__test_authed_boom__"]
    assert err_lines, f"no access line for the authed 500 in {lines}"
    line = err_lines[-1]
    assert line.get("status") == 500
    assert "user_id" in line, f"user_id missing from authed 500 access line: {line!r}"
    assert isinstance(line["user_id"], str)


async def test_cors_headers_present_on_middleware_built_500(
    client: httpx.AsyncClient,
) -> None:
    """Codex round-6 P2: a 500 response built INSIDE
    ``RequestLoggingMiddleware`` must still carry CORS headers so a
    cross-origin browser can read the error envelope + X-Request-ID.

    The fix is middleware ordering: CORSMiddleware is added LAST so it's
    the outermost layer; our hand-built 500 flows back through it on
    the way out and picks up ``Access-Control-Allow-Origin`` /
    ``Access-Control-Expose-Headers``.
    """

    from app.main import app

    @app.get("/__test_cors_500__")
    async def boom() -> None:
        raise RuntimeError("simulated unhandled error for cors test")

    try:
        response = await client.get(
            "/__test_cors_500__",
            headers={"Origin": "http://localhost:3000"},
        )
    finally:
        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) != "/__test_cors_500__"
        ]

    assert response.status_code == 500
    assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000", (
        "500 response missing CORS Allow-Origin — cross-origin browser would "
        "see an opaque failure"
    )
    expose = response.headers.get("Access-Control-Expose-Headers", "")
    assert "X-Request-ID" in expose, f"X-Request-ID not exposed via CORS on the 500: {expose!r}"
    assert response.headers.get("X-Request-ID")


async def test_unhandled_500_calls_sentry_capture_exception(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex round-5 P2: when the middleware catches an unhandled exception
    to build a 500, Starlette's Sentry integration never sees it as
    unhandled — so we must call ``sentry_sdk.capture_exception()``
    explicitly. Without this, the only Sentry trace would be a handled
    log event (weaker severity / grouping) and a high ``LOG_LEVEL`` could
    suppress it entirely.

    Asserts the explicit capture happens by patching the sentry module.
    """

    import sys
    from unittest.mock import MagicMock

    from app.main import app

    fake_sdk = MagicMock()
    fake_sdk.capture_exception = MagicMock()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)

    @app.get("/__test_sentry_boom__")
    async def boom() -> None:
        raise RuntimeError("simulated for sentry capture test")

    try:
        response = await client.get("/__test_sentry_boom__")
    finally:
        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) != "/__test_sentry_boom__"
        ]

    assert response.status_code == 500
    fake_sdk.capture_exception.assert_called_once()


async def test_unhandled_500_carries_request_id_header(
    client: httpx.AsyncClient,
    captured_access_log: pytest.LogCaptureFixture,
) -> None:
    """Codex P2: when a route raises an unhandled exception, the 500 response
    must still carry ``X-Request-ID`` so a user can quote the same id that
    appears in the access log.

    Without the ``Exception`` handler in ``app.main``, Starlette's outer
    ``ServerErrorMiddleware`` builds the 500 outside our middleware's
    response path and the header never lands.
    """

    from app.main import app

    # Register a temporary route on the live app that raises. We stash the
    # original router state so cleanup doesn't bleed into other tests.
    @app.get("/__test_boom__")
    async def boom() -> None:
        raise RuntimeError("simulated unhandled error")

    try:
        response = await client.get("/__test_boom__")
    finally:
        # Pop the route off the live app so this test stays self-contained.
        app.router.routes = [
            route for route in app.router.routes if getattr(route, "path", None) != "/__test_boom__"
        ]

    assert response.status_code == 500
    request_id = response.headers.get("X-Request-ID")
    assert (
        request_id is not None and len(request_id) == 32
    ), f"X-Request-ID missing or malformed on 500: got {request_id!r}"
    body = response.json()
    assert body == {
        "error": {
            "code": "internal_error",
            "message": "Internal server error",
            "details": [],
        }
    }

    # The access line still gets emitted with the same request_id.
    lines = _formatted_access_lines(captured_access_log)
    assert any(
        line.get("path") == "/__test_boom__" and line.get("request_id") == request_id
        for line in lines
    ), f"no matching access line for the 500 in {lines}"
