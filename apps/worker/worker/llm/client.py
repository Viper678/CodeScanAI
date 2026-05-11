"""Gemma client — the single module that talks to the vLLM OpenAI-compatible API.

The orchestrator (T3.4) calls ``GemmaClient.scan_file`` once per (file,
scan_type). This module:

1. Loads the versioned system prompt for the scan type.
2. Builds the user prompt envelope from docs/SCAN_RULES.md
   §"Common scan envelope" — File / Language header plus line-numbered code.
3. Issues the call through an injectable :class:`GemmaTransport`, wrapping
   the call in :func:`call_with_retry` so 429/5xx/timeout backoff lives
   in one place.
4. Parses the response with :class:`FindingsResponse`. On invalid JSON or
   Pydantic validation error, makes exactly one repair attempt with a
   suffixed user prompt (per SCAN_RULES.md §"Retry logic").
5. Returns :class:`ScanResult` (findings + tokens_in/out + latency_ms) so
   the orchestrator can persist it on ``scan_files``.

The default transport lazily imports ``openai`` so that unit tests —
which always inject ``transport=`` — never pay the SDK import cost and
never accidentally hit the network.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import ValidationError

from worker.llm.prompts import PROMPT_VERSION, load_prompt
from worker.llm.retry import (
    DEFAULT_RETRY_POLICY,
    GemmaClientError,
    GemmaRateLimited,
    GemmaServerError,
    GemmaUnrecoverable,
    RetryPolicy,
    call_with_retry,
)
from worker.llm.schemas import FindingsResponse, LlmFinding

# Hard-coded per docs/SCAN_RULES.md §"Common scan envelope".
TEMPERATURE = 0.0
MAX_OUTPUT_TOKENS = 4096
REPAIR_SUFFIX = "\n\nYour previous response was not valid JSON. Respond ONLY with the JSON object."
# vLLM (and many OpenAI-compatible servers) accept any non-empty api_key when
# the server is started without ``--api-key``. The SDK constructor itself
# refuses an empty string, so we pass this placeholder when the operator
# didn't configure ``LLM_API_KEY``.
_PLACEHOLDER_API_KEY = "unused-by-vllm"
# Per-call HTTP timeout for the openai client. The SDK's default is 600s
# which would let a stalled connection burn the worker's per-call retry
# budget; cap at 2 minutes so the retry policy can fire instead.
_HTTP_TIMEOUT_SECONDS = 120.0

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawResponse:
    """Transport-level response: text body plus token counts from usage metadata."""

    text: str
    tokens_in: int
    tokens_out: int


@dataclass(frozen=True)
class ScanResult:
    """Per-file scan result returned to the orchestrator."""

    findings: list[LlmFinding]
    tokens_in: int
    tokens_out: int
    latency_ms: int


class GemmaTransport(Protocol):
    """Single Gemma request.

    Implementations translate SDK exceptions to :class:`GemmaRateLimited`,
    :class:`GemmaServerError`, or :class:`GemmaClientError` so the retry
    policy can act on them without knowing about the underlying SDK.
    """

    def __call__(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_output_tokens: int,
    ) -> RawResponse: ...


class GemmaClient:
    """Wraps a Gemma transport with prompt loading, retry, and validation.

    ``base_url`` is only consumed by the default transport (constructed
    lazily). Tests pass ``transport=`` and may use a placeholder base_url.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        model: str = "gemma-4-31b-it",
        prompt_version: str = PROMPT_VERSION,
        transport: GemmaTransport | None = None,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._model = model
        self._prompt_version = prompt_version
        self._retry_policy = retry_policy
        self._sleep = sleep
        self._clock = clock
        if transport is not None:
            self._transport: GemmaTransport = transport
        else:
            if not base_url:
                raise ValueError(
                    "base_url is required when no transport is injected; "
                    "set LLM_BASE_URL in the environment."
                )
            self._transport = _DefaultGemmaTransport(base_url=base_url, api_key=api_key)

    def scan_file(
        self,
        *,
        scan_type: Literal["security", "bugs"],
        relative_path: str,
        language: str | None,
        content: str,
    ) -> ScanResult:
        """Scan one file. Times the call and returns a structured result."""

        system_prompt = load_prompt(scan_type, version=self._prompt_version)
        user_prompt = _build_user_prompt(
            relative_path=relative_path, language=language, content=content
        )
        total_lines = _count_lines(content)

        start = self._clock()
        raw = self._call(system_prompt=system_prompt, user_prompt=user_prompt)

        try:
            parsed = FindingsResponse.model_validate_json(raw.text)
            tokens_in, tokens_out = raw.tokens_in, raw.tokens_out
        except (ValidationError, ValueError, json.JSONDecodeError):
            repaired = self._repair(
                system_prompt=system_prompt,
                user_prompt=user_prompt + REPAIR_SUFFIX,
            )
            parsed = repaired[0]
            # Token reporting decision: report ONLY the successful (final) call's
            # tokens since that's the response whose findings are persisted. The
            # repair-attempt tokens are still spent but they don't correspond to
            # a stored finding; orchestrator-level "calls" counter (T3.4) tracks
            # the extra round-trip separately.
            tokens_in, tokens_out = repaired[1], repaired[2]

        end = self._clock()
        # SCAN_RULES.md §"Output validation": drop findings whose line range
        # falls outside the scanned file. Common LLM failure mode is reporting
        # line_end past EOF; persisting impossible locations would mislead the
        # UI and triage. Filter silently with a warning rather than failing
        # the whole file for one bad finding.
        kept = _filter_in_bounds(parsed.findings, total_lines=total_lines)
        return ScanResult(
            findings=kept,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=int((end - start) * 1000),
        )

    def _call(self, *, system_prompt: str, user_prompt: str) -> RawResponse:
        def _do() -> RawResponse:
            return self._transport(
                model=self._model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=TEMPERATURE,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )

        return call_with_retry(_do, policy=self._retry_policy, sleep=self._sleep)

    def _repair(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[FindingsResponse, int, int]:
        """One re-prompt attempt for invalid JSON / failed Pydantic validation."""

        try:
            raw = self._call(system_prompt=system_prompt, user_prompt=user_prompt)
            parsed = FindingsResponse.model_validate_json(raw.text)
        except (ValidationError, ValueError, json.JSONDecodeError) as repair_err:
            raise GemmaUnrecoverable("invalid_json") from repair_err
        return parsed, raw.tokens_in, raw.tokens_out


# ---- User prompt envelope ---------------------------------------------------


def _build_user_prompt(*, relative_path: str, language: str | None, content: str) -> str:
    """Render the per-file user prompt per docs/SCAN_RULES.md §"Common scan envelope"."""

    lang = language if language else "unknown"
    numbered = _number_lines(content)
    return (
        f"File: {relative_path}\n" f"Language: {lang}\n" f"\n" f"```{lang}\n" f"{numbered}" f"```\n"
    )


def _number_lines(content: str) -> str:
    """Prefix each line with ``%4d │ ``; preserves a trailing newline if present."""

    if not content:
        return ""
    lines = content.split("\n")
    trailing_newline = lines[-1] == ""
    if trailing_newline:
        lines = lines[:-1]
    rendered = "\n".join(f"{i:>4d} │ {line}" for i, line in enumerate(lines, start=1))
    return rendered + ("\n" if trailing_newline else "")


def _count_lines(content: str) -> int:
    """Count lines the same way ``_number_lines`` does so bounds match the prompt."""

    if not content:
        return 0
    lines = content.split("\n")
    if lines[-1] == "":
        lines = lines[:-1]
    return len(lines)


def _filter_in_bounds(findings: list[LlmFinding], *, total_lines: int) -> list[LlmFinding]:
    """Drop findings whose line range is outside the scanned file."""

    kept: list[LlmFinding] = []
    for finding in findings:
        if total_lines == 0 or finding.line_end > total_lines or finding.line_start < 1:
            _logger.warning(
                "dropping out-of-bounds finding: lines %d-%d, file has %d lines (title=%r)",
                finding.line_start,
                finding.line_end,
                total_lines,
                finding.title,
            )
            continue
        kept.append(finding)
    return kept


# ---- Default transport (only path that imports openai) ---------------------


class _DefaultGemmaTransport:
    """Production transport. Constructs the SDK client eagerly in ``__init__``.

    Why eager (and not a lazy ``if self._client is None: …`` in ``__call__``):
    the orchestrator (T3.4) shares one ``GemmaClient`` across a
    ``ThreadPoolExecutor`` with ``scan_concurrency`` workers. Lazy init is
    a check-then-set race in that setting — two threads racing on the first
    call could each construct an ``openai.OpenAI`` client; the loser's
    instance is garbage-collected, closing its underlying ``httpx.Client``,
    and the winner's in-flight request errors out with
    ``Cannot send a request, as the client has been closed.``
    Eager init in ``__init__`` runs on the orchestrator's main thread before
    the pool is opened, sidestepping the race entirely.

    SDK exception translation:
        ``openai.RateLimitError``      -> GemmaRateLimited (Retry-After honored)
        ``openai.APIStatusError`` 5xx  -> GemmaServerError
        ``openai.APIStatusError`` 4xx  -> GemmaClientError
        ``openai.APITimeoutError``     -> GemmaServerError
        ``openai.APIConnectionError``  -> GemmaServerError
    """

    def __init__(self, *, base_url: str, api_key: str | None = None) -> None:
        # Import inside __init__ keeps ``openai`` out of unit-test import
        # graphs: tests that supply ``transport=`` to ``GemmaClient`` never
        # touch this constructor.
        from openai import OpenAI

        # The openai SDK refuses an empty api_key argument even when the
        # upstream server is unauthenticated (vLLM started without
        # ``--api-key``). Pass a placeholder string — vLLM ignores the
        # Authorization header when ``--api-key`` was not set on its CLI.
        effective_key = api_key if api_key else _PLACEHOLDER_API_KEY
        self._client = OpenAI(
            base_url=base_url,
            api_key=effective_key,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )

    def __call__(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_output_tokens: int,
    ) -> RawResponse:
        import openai

        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_output_tokens,
                # vLLM extension: constrain the decode to schema-valid JSON.
                # The repair loop in ``GemmaClient.scan_file`` still acts as
                # a safety net for non-vLLM OpenAI-compat servers (dev) that
                # silently ignore the unknown ``guided_json`` field.
                extra_body={"guided_json": FindingsResponse.model_json_schema()},
            )
        except openai.RateLimitError as exc:
            raise GemmaRateLimited(retry_after=_extract_retry_after(exc)) from exc
        except openai.APITimeoutError as exc:
            raise GemmaServerError(str(exc)) from exc
        except openai.APIConnectionError as exc:
            raise GemmaServerError(str(exc)) from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise GemmaServerError(str(exc)) from exc
            raise GemmaClientError(str(exc)) from exc

        text = response.choices[0].message.content or "" if response.choices else ""
        usage = response.usage
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        return RawResponse(text=text, tokens_in=tokens_in, tokens_out=tokens_out)


def _extract_retry_after(exc: Exception) -> float | None:
    """Best-effort Retry-After lookup on an openai ``APIStatusError`` response."""

    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after") if hasattr(headers, "get") else None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
