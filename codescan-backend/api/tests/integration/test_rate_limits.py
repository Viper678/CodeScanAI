"""Integration tests for the rate limits wired in T5.1.

Each test bumps the relevant settings.rate_limit_* attribute down to the
spec value (the global conftest fixture defaults them to 100 so the rest of
the suite isn't affected). The per-test ``rate_limit_key_namespace`` is
already isolated so we can burn the budget without leaking into siblings.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from redis.exceptions import RedisError

from app.core.config import settings
from app.main import app

CSRF_HEADERS = {"X-Requested-With": "codescan"}


def _zip_bytes(entries: dict[str, str] | None = None) -> bytes:
    payload = entries or {"hello.py": "print('hi')\n"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in payload.items():
            archive.writestr(name, body)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login — 5/IP/min
# ---------------------------------------------------------------------------


async def test_login_returns_429_after_threshold(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """6th login attempt from the same IP within a minute is rate-limited.

    The first 5 hit the auth handler (and 401 because the credentials are
    wrong); the 6th is short-circuited by the rate-limit dep with 429 +
    a ``Retry-After`` header and the standard error envelope.
    """

    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 5)

    payload = {"email": f"missing-{uuid4().hex[:8]}@example.com", "password": "x" * 12}

    for _ in range(5):
        response = await client.post("/api/v1/auth/login", json=payload)
        # 401 because the user doesn't exist; the limiter let it through.
        assert response.status_code == 401, response.text

    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 429
    assert response.headers.get("Retry-After") is not None
    assert int(response.headers["Retry-After"]) >= 1

    body = response.json()
    assert body["error"]["code"] == "rate_limited"
    assert "rate limit" in body["error"]["message"].lower()


# ---------------------------------------------------------------------------
# POST /api/v1/auth/register — 5/IP/min
# ---------------------------------------------------------------------------


async def test_register_returns_429_after_threshold(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rate_limit_register_per_minute", 5)

    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"reg-{uuid4().hex[:8]}@example.com",
                "password": "correct-horse-battery-staple",
            },
        )
        assert response.status_code == 201, response.text
        client.cookies.clear()  # fresh user every loop iteration

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"over-{uuid4().hex[:8]}@example.com",
            "password": "correct-horse-battery-staple",
        },
    )
    assert response.status_code == 429
    assert response.headers.get("Retry-After") is not None
    assert response.json()["error"]["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# POST /api/v1/scans — 30/user/hour
# ---------------------------------------------------------------------------


async def test_scan_create_returns_429_after_threshold(
    authed_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-user limit on scan creation. We don't actually need the scans to
    succeed — we only need the rate limiter to count attempts. So we POST
    intentionally invalid bodies that trip 422 and confirm the rate limiter
    still ticks against them (the limit dep runs *before* the route body)."""

    monkeypatch.setattr(settings, "rate_limit_scan_per_hour", 3)

    invalid_payload: dict[str, Any] = {
        "upload_id": str(uuid4()),
        "scan_types": [],  # 422
        "file_ids": [],
    }

    for _ in range(3):
        response = await authed_client.post(
            "/api/v1/scans",
            headers=CSRF_HEADERS,
            json=invalid_payload,
        )
        # 404 (upload not found) or 422 (validation) — either is fine; we
        # just need a non-429 code to confirm the limiter let it through.
        assert response.status_code != 429, response.text

    response = await authed_client.post(
        "/api/v1/scans",
        headers=CSRF_HEADERS,
        json=invalid_payload,
    )
    assert response.status_code == 429
    assert response.headers.get("Retry-After") is not None
    assert response.json()["error"]["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# POST /api/v1/uploads — 10/user/hour
# ---------------------------------------------------------------------------


async def test_upload_returns_429_after_threshold(
    authed_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(settings, "rate_limit_upload_per_hour", 2)
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    # Mock the Celery enqueue so we don't try to talk to a real broker.
    from unittest.mock import MagicMock, patch

    with patch(
        "app.services.upload_service.enqueue_prepare_upload",
        new=MagicMock(),
    ):
        for _ in range(2):
            response = await authed_client.post(
                "/api/v1/uploads",
                headers=CSRF_HEADERS,
                files={"file": ("repo.zip", _zip_bytes(), "application/zip")},
                data={"kind": "zip"},
            )
            assert response.status_code == 202, response.text

        response = await authed_client.post(
            "/api/v1/uploads",
            headers=CSRF_HEADERS,
            files={"file": ("repo.zip", _zip_bytes(), "application/zip")},
            data={"kind": "zip"},
        )

    assert response.status_code == 429
    assert response.headers.get("Retry-After") is not None
    assert response.json()["error"]["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# Fail-open behaviour when Redis is unreachable
# ---------------------------------------------------------------------------


async def test_login_fails_open_when_redis_is_down(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Redis blips, the request must still reach the route handler.

    Rate limiting is best-effort defense — see the docstring on
    ``app.core.rate_limit``. Swap ``app.state.redis`` for a mock that raises
    ``RedisError`` on every operation and confirm the request still produces
    the expected 401 (wrong-creds) rather than a 429 or 500. We also verify
    the limiter actually CALLED the broken redis (so the fail-open path is
    exercised, not just bypassed).
    """

    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 5)

    # ``pipeline()`` is synchronous in redis-py; raise on the first call so
    # the ``try:`` block in the limiter catches it and falls open.
    broken_redis = MagicMock()
    broken_redis.pipeline.side_effect = RedisError("simulated outage")

    original_redis = app.state.redis
    app.state.redis = broken_redis
    try:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "x" * 12},
        )
    finally:
        app.state.redis = original_redis

    assert response.status_code == 401, response.text
    # Confirm the limiter actually tried Redis — i.e. fail-open is the path
    # taken, not "the limiter never ran". Without this assertion an unrelated
    # bug that bypasses the limiter would silently masquerade as fail-open.
    broken_redis.pipeline.assert_called()


async def test_repeated_calls_during_redis_outage_all_succeed(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check: under a sustained Redis outage the limiter never trips.

    Important for understanding the fail-open contract: an outage SHOULDN'T
    accidentally reject traffic. Make 7 calls (limit is 5) and confirm none
    of them get a 429.
    """

    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 5)

    broken_redis = MagicMock()
    broken_redis.pipeline.side_effect = RedisError("simulated outage")

    original_redis = app.state.redis
    app.state.redis = broken_redis
    try:
        statuses = []
        for _ in range(7):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "x" * 12},
            )
            statuses.append(response.status_code)
    finally:
        app.state.redis = original_redis

    assert all(
        code != 429 for code in statuses
    ), f"fail-open broken: at least one request was 429ed during outage: {statuses}"
