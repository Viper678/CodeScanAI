"""Per-call retry policy for Gemma transport calls.

Implements docs/SCAN_RULES.md §"Retry logic" as a transport-agnostic wrapper
around any zero-arg callable so the unit tests can drive it with scripted
exceptions and a mocked sleep.

Exception taxonomy:
    GemmaRateLimited  -> 429; transport may carry Retry-After.
    GemmaServerError  -> 5xx, network, timeout (retried with backoff).
    GemmaClientError  -> non-429 4xx (terminal, no retry).
    GemmaUnrecoverable -> raised by ``call_with_retry`` once the budget is
        exhausted or a terminal error fires; always chains the underlying
        cause via ``__cause__``.

Anything else (random ``RuntimeError`` etc.) bubbles up untouched — we don't
swallow programmer errors into the retry loop.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Total attempts and per-attempt sleep schedule (see SCAN_RULES.md)."""

    max_attempts: int = 5
    backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)


DEFAULT_RETRY_POLICY = RetryPolicy()


class GemmaUnrecoverable(RuntimeError):
    """Terminal failure: budget exhausted or non-retryable error encountered."""


class GemmaRateLimited(Exception):
    """429 from Gemma, optionally carrying ``Retry-After`` seconds."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__(f"rate limited (retry_after={retry_after!r})")
        self.retry_after = retry_after


class GemmaServerError(Exception):
    """5xx, network failure, or timeout — retry with backoff."""


class GemmaClientError(Exception):
    """Non-429 4xx — caller bug, do not retry."""


def call_with_retry(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Invoke ``fn`` honoring the retry policy.

    Args:
        fn: Zero-arg callable that performs the transport call.
        policy: Attempt budget and backoff schedule.
        sleep: Injected so tests can assert sleep durations without waiting.

    Returns:
        ``fn``'s return value on the first successful attempt.

    Raises:
        GemmaUnrecoverable: Budget exhausted, or a terminal client error fired.
        Exception: Any non-Gemma exception is re-raised unchanged.
    """

    last_error: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except GemmaClientError as exc:
            raise GemmaUnrecoverable("client error (non-429 4xx)") from exc
        except GemmaRateLimited as exc:
            last_error = exc
            if attempt >= policy.max_attempts:
                break
            wait = exc.retry_after if exc.retry_after is not None else _backoff(policy, attempt)
            sleep(wait)
        except GemmaServerError as exc:
            last_error = exc
            if attempt >= policy.max_attempts:
                break
            sleep(_backoff(policy, attempt))

    raise GemmaUnrecoverable("retry budget exhausted") from last_error


def _backoff(policy: RetryPolicy, attempt: int) -> float:
    """Pick the sleep for ``attempt`` (1-indexed); reuses the last entry on overflow."""

    idx = min(attempt - 1, len(policy.backoff_seconds) - 1)
    return policy.backoff_seconds[idx]
