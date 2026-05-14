"""Unit tests for the sliding-window rate limiter (T5.1).

Run against a real Redis (the ``api_redis_client`` fixture connects to the
test db). We rely on the per-test ``rate_limit_key_namespace`` to keep keys
isolated and use a fake clock so the tests don't actually sleep across
windows.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.core.rate_limit import check_sliding_window


def _fake_clock(start: float) -> tuple[Callable[[], float], Callable[[float], None]]:
    """Tiny mutable clock helper. Returns (now_fn, advance_fn)."""

    state = {"t": start}

    def now() -> float:
        return state["t"]

    def advance(seconds: float) -> None:
        state["t"] += seconds

    return now, advance


@pytest.fixture
def isolated_key() -> str:
    return f"rl:test:{uuid4().hex}"


async def test_first_request_is_allowed(
    api_redis_client: Redis,
    isolated_key: str,
) -> None:
    now, _ = _fake_clock(start=1_000_000.0)

    decision = await check_sliding_window(
        api_redis_client,
        key=isolated_key,
        limit=5,
        window_seconds=60,
        clock=now,
    )

    assert decision.allowed is True
    assert decision.retry_after_seconds == 0


async def test_allows_up_to_limit_then_rejects(
    api_redis_client: Redis,
    isolated_key: str,
) -> None:
    now, advance = _fake_clock(start=1_000_000.0)

    for _ in range(5):
        decision = await check_sliding_window(
            api_redis_client,
            key=isolated_key,
            limit=5,
            window_seconds=60,
            clock=now,
        )
        assert decision.allowed is True
        advance(0.1)

    decision = await check_sliding_window(
        api_redis_client,
        key=isolated_key,
        limit=5,
        window_seconds=60,
        clock=now,
    )

    assert decision.allowed is False
    # The oldest in-window entry is at t=1_000_000.0; with window=60 it
    # falls out at t=1_000_060.0. Current time is roughly t=1_000_000.5,
    # so retry_after should be ~60.
    assert decision.retry_after_seconds >= 1
    assert decision.retry_after_seconds <= 61


async def test_window_slides_forward(
    api_redis_client: Redis,
    isolated_key: str,
) -> None:
    """Entries older than the window should drop out so new ones are allowed."""

    now, advance = _fake_clock(start=2_000_000.0)

    # Burn the budget at t=0..0.5.
    for _ in range(5):
        await check_sliding_window(
            api_redis_client,
            key=isolated_key,
            limit=5,
            window_seconds=60,
            clock=now,
        )
        advance(0.1)

    # 6th at t=0.5 should reject.
    decision = await check_sliding_window(
        api_redis_client,
        key=isolated_key,
        limit=5,
        window_seconds=60,
        clock=now,
    )
    assert decision.allowed is False

    # Skip past the window — at t=61 the first 5 entries (all at t<1) have
    # fallen out. The 6th entry at t=0.5 was rejected (and so not added),
    # so the window is empty.
    advance(60.5)

    decision = await check_sliding_window(
        api_redis_client,
        key=isolated_key,
        limit=5,
        window_seconds=60,
        clock=now,
    )
    assert decision.allowed is True


async def test_rejected_request_does_not_consume_a_slot(
    api_redis_client: Redis,
    isolated_key: str,
) -> None:
    """A rejected request must NOT extend the cooldown.

    The credential-stuffing model assumes a flood of attempts; if every
    rejection added another slot, the window would never empty out and
    the limit would converge to 0. Verify instead that rejections leave
    the existing 5 slots untouched.
    """

    now, advance = _fake_clock(start=3_000_000.0)

    for _ in range(5):
        await check_sliding_window(
            api_redis_client,
            key=isolated_key,
            limit=5,
            window_seconds=60,
            clock=now,
        )
        advance(0.1)

    # Hammer with 10 rejected requests — should not budge the window.
    for _ in range(10):
        decision = await check_sliding_window(
            api_redis_client,
            key=isolated_key,
            limit=5,
            window_seconds=60,
            clock=now,
        )
        assert decision.allowed is False
        advance(0.1)

    # After ~60s the original 5 (which started at t=0..0.5) should drop
    # out and a fresh request at t=60.6 succeeds. If rejected requests
    # had added slots, this would still reject.
    advance(60.0)

    decision = await check_sliding_window(
        api_redis_client,
        key=isolated_key,
        limit=5,
        window_seconds=60,
        clock=now,
    )
    assert decision.allowed is True


async def test_retry_after_reflects_oldest_entry_falling_out(
    api_redis_client: Redis,
    isolated_key: str,
) -> None:
    now, advance = _fake_clock(start=4_000_000.0)

    # Burn the budget at t=0.
    for _ in range(5):
        await check_sliding_window(
            api_redis_client,
            key=isolated_key,
            limit=5,
            window_seconds=60,
            clock=now,
        )

    # Advance to t=30 — the oldest entry falls out at t=60, so retry_after
    # should be ~30.
    advance(30.0)

    decision = await check_sliding_window(
        api_redis_client,
        key=isolated_key,
        limit=5,
        window_seconds=60,
        clock=now,
    )

    assert decision.allowed is False
    assert 28 <= decision.retry_after_seconds <= 32


async def test_separate_keys_have_independent_budgets(
    api_redis_client: Redis,
) -> None:
    key_a = f"rl:test:{uuid4().hex}"
    key_b = f"rl:test:{uuid4().hex}"
    now, _ = _fake_clock(start=5_000_000.0)

    for _ in range(5):
        await check_sliding_window(
            api_redis_client,
            key=key_a,
            limit=5,
            window_seconds=60,
            clock=now,
        )

    # Key B should still have its full budget.
    decision = await check_sliding_window(
        api_redis_client,
        key=key_b,
        limit=5,
        window_seconds=60,
        clock=now,
    )
    assert decision.allowed is True
