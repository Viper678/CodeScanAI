"""Unit tests for the per-call retry policy."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from worker.llm.retry import (
    GemmaClientError,
    GemmaRateLimited,
    GemmaServerError,
    GemmaUnrecoverable,
    RetryPolicy,
    call_with_retry,
)


def _scripted(*effects: Any) -> Callable[[], Any]:
    """Return a zero-arg callable that returns or raises ``effects`` in order."""

    it = iter(effects)

    def fn() -> Any:
        eff = next(it)
        if isinstance(eff, Exception):
            raise eff
        return eff

    return fn


def test_happy_path_returns_immediately() -> None:
    sleep = MagicMock()
    fn = _scripted("ok")
    assert call_with_retry(fn, sleep=sleep) == "ok"
    sleep.assert_not_called()


def test_five_5xx_raises_unrecoverable_with_partial_backoff() -> None:
    sleep = MagicMock()
    fn = _scripted(
        GemmaServerError("boom1"),
        GemmaServerError("boom2"),
        GemmaServerError("boom3"),
        GemmaServerError("boom4"),
        GemmaServerError("boom5"),
    )
    with pytest.raises(GemmaUnrecoverable, match="retry budget exhausted"):
        call_with_retry(fn, sleep=sleep)
    # Sleeps fire BETWEEN attempts, so 5 attempts = 4 sleeps.
    sleep.assert_has_calls([call(1.0), call(2.0), call(4.0), call(8.0)])
    assert sleep.call_count == 4


def test_two_5xx_then_success() -> None:
    sleep = MagicMock()
    fn = _scripted(GemmaServerError("a"), GemmaServerError("b"), "result")
    assert call_with_retry(fn, sleep=sleep) == "result"
    sleep.assert_has_calls([call(1.0), call(2.0)])
    assert sleep.call_count == 2


def test_429_with_retry_after_uses_that_value() -> None:
    sleep = MagicMock()
    fn = _scripted(GemmaRateLimited(retry_after=3.0), "ok")
    assert call_with_retry(fn, sleep=sleep) == "ok"
    sleep.assert_called_once_with(3.0)


def test_429_without_retry_after_falls_back_to_backoff() -> None:
    sleep = MagicMock()
    fn = _scripted(GemmaRateLimited(retry_after=None), "ok")
    assert call_with_retry(fn, sleep=sleep) == "ok"
    sleep.assert_called_once_with(1.0)


def test_non_429_4xx_is_terminal() -> None:
    sleep = MagicMock()
    fn = _scripted(GemmaClientError("400 bad request"))
    with pytest.raises(GemmaUnrecoverable, match="client error"):
        call_with_retry(fn, sleep=sleep)
    sleep.assert_not_called()


def test_random_exception_bubbles_up_unchanged() -> None:
    sleep = MagicMock()
    fn = _scripted(RuntimeError("bug"))
    with pytest.raises(RuntimeError, match="bug"):
        call_with_retry(fn, sleep=sleep)
    sleep.assert_not_called()


def test_exhaustion_chains_last_error_as_cause() -> None:
    sleep = MagicMock()
    last = GemmaServerError("final")
    fn = _scripted(
        GemmaServerError("a"),
        GemmaServerError("b"),
        GemmaServerError("c"),
        GemmaServerError("d"),
        last,
    )
    with pytest.raises(GemmaUnrecoverable) as excinfo:
        call_with_retry(fn, sleep=sleep)
    assert excinfo.value.__cause__ is last


def test_custom_policy_respected() -> None:
    sleep = MagicMock()
    policy = RetryPolicy(max_attempts=2, backoff_seconds=(0.5,))
    fn = _scripted(GemmaServerError("a"), GemmaServerError("b"))
    with pytest.raises(GemmaUnrecoverable):
        call_with_retry(fn, policy=policy, sleep=sleep)
    sleep.assert_called_once_with(0.5)
