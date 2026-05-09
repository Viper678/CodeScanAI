"""Integration tests for ``/healthz`` and ``/readyz`` (T5.3).

The ``client`` fixture in ``conftest.py`` already mounts a real async Redis
on ``app.state.redis`` and a real DB session via the dependency override —
we only swap them out for the failure-mode tests. The happy-path test
exercises both for real, which is what an orchestrator's probe actually
sees in production.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from redis.exceptions import RedisError
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.main import app

# ---------------------------------------------------------------------------
# /healthz — process-up regression
# ---------------------------------------------------------------------------


async def test_healthz_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /readyz — happy path
# ---------------------------------------------------------------------------


async def test_readyz_returns_200_when_both_deps_healthy(
    client: httpx.AsyncClient,
) -> None:
    """Real DB + real Redis (mounted by the conftest fixture). This is what
    docker-compose's healthcheck and any orchestrator readiness probe will
    see when everything is wired up correctly."""

    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "redis": "ok"}


# ---------------------------------------------------------------------------
# /readyz — Redis failure
# ---------------------------------------------------------------------------


async def test_readyz_returns_503_when_redis_ping_raises(
    client: httpx.AsyncClient,
) -> None:
    """Swap ``app.state.redis`` for a stub that raises ``RedisError`` on
    ``ping()``; expect 503 with ``redis: "fail"`` and ``db: "ok"``.

    Mirrors the T5.1 pattern at ``test_rate_limits.py`` — restore the
    original client in a ``finally`` so a failing assert doesn't poison
    other tests on the shared ``app.state``.
    """

    broken_redis = MagicMock()
    broken_redis.ping = AsyncMock(side_effect=RedisError("simulated outage"))

    original_redis = app.state.redis
    app.state.redis = broken_redis
    try:
        response = await client.get("/readyz")
    finally:
        app.state.redis = original_redis

    assert response.status_code == 503
    assert response.json() == {"status": "fail", "db": "ok", "redis": "fail"}
    broken_redis.ping.assert_awaited()


# ---------------------------------------------------------------------------
# /readyz — Redis timeout
# ---------------------------------------------------------------------------


async def test_readyz_returns_503_when_redis_ping_hangs(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung ``ping()`` (sleeps past the 2s budget) must trip the timeout
    and surface as ``redis: "fail"`` rather than blocking the probe forever.

    Speed the budget down to 0.05s for the test so we're not actually
    waiting the production 2s — same code path, faster turnaround.
    """

    from app.routers import health as health_router_mod

    monkeypatch.setattr(health_router_mod, "CHECK_TIMEOUT_SECONDS", 0.05)

    async def _hang(*_args: Any, **_kwargs: Any) -> None:
        await asyncio.sleep(5.0)  # well past the bumped-down budget

    hung_redis = MagicMock()
    hung_redis.ping = _hang

    original_redis = app.state.redis
    app.state.redis = hung_redis
    try:
        response = await client.get("/readyz")
    finally:
        app.state.redis = original_redis

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "fail"
    assert body["redis"] == "fail"
    assert body["db"] == "ok"


# ---------------------------------------------------------------------------
# /readyz — DB failure
# ---------------------------------------------------------------------------


async def test_readyz_returns_503_when_db_select_raises(
    client: httpx.AsyncClient,
) -> None:
    """Override ``get_session`` to yield a session whose ``execute()`` raises
    ``OperationalError`` (the SQLAlchemyError subclass surfaced when the
    DB connection is broken)."""

    failing_session = MagicMock(spec=AsyncSession)
    failing_session.execute = AsyncMock(
        side_effect=OperationalError("SELECT 1", {}, Exception("simulated db outage"))
    )

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield failing_session

    original = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = override_session
    try:
        response = await client.get("/readyz")
    finally:
        if original is None:
            app.dependency_overrides.pop(get_session, None)
        else:
            app.dependency_overrides[get_session] = original

    assert response.status_code == 503
    assert response.json() == {"status": "fail", "db": "fail", "redis": "ok"}
    failing_session.execute.assert_awaited()
