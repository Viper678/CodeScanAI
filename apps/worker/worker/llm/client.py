"""Gemma client — the single module that talks to ``google.genai``.

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

The default transport lazily imports ``google.genai`` so that unit tests —
which always inject ``transport=`` — never pay the SDK import cost and
never accidentally hit the network.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import ValidationError

from worker.llm.prompts import load_prompt
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
    policy can act on them without knowing about ``google.genai``.
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

    ``api_key`` is only consumed by the default transport (constructed
    lazily). Tests pass ``transport=`` and may use a placeholder api_key.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemma-4-31b-it",
        transport: GemmaTransport | None = None,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._model = model
        self._retry_policy = retry_policy
        self._sleep = sleep
        self._clock = clock
        if transport is not None:
            self._transport: GemmaTransport = transport
        else:
            if not api_key:
                raise ValueError(
                    "api_key is required when no transport is injected; "
                    "set GOOGLE_AI_API_KEY in the environment."
                )
            self._transport = _DefaultGemmaTransport(api_key=api_key)

    def scan_file(
        self,
        *,
        scan_type: Literal["security", "bugs"],
        relative_path: str,
        language: str | None,
        content: str,
    ) -> ScanResult:
        """Scan one file. Times the call and returns a structured result."""

        system_prompt = load_prompt(scan_type)
        user_prompt = _build_user_prompt(
            relative_path=relative_path, language=language, content=content
        )

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
        return ScanResult(
            findings=list(parsed.findings),
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


# ---- Default transport (only path that imports google.genai) ---------------


class _DefaultGemmaTransport:
    """Production transport. Lazily constructs the SDK client on first call.

    SDK exception translation:
        ``google.genai.errors.ClientError``  -> 429 -> GemmaRateLimited
                                              -> other 4xx -> GemmaClientError
        ``google.genai.errors.ServerError``  -> GemmaServerError
        Network/timeout (``httpx``/``requests`` errors) -> GemmaServerError
    """

    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key
        self._client: object | None = None

    def __call__(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_output_tokens: int,
    ) -> RawResponse:
        # Lazy import: keeps ``google.genai`` out of unit-test import graphs.
        from google import genai
        from google.genai import errors as genai_errors
        from google.genai import types as genai_types

        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)

        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
        )

        try:
            response = self._client.models.generate_content(  # type: ignore[attr-defined]
                model=model,
                contents=user_prompt,
                config=config,
            )
        except genai_errors.ClientError as exc:
            if getattr(exc, "code", None) == 429:
                raise GemmaRateLimited(retry_after=_extract_retry_after(exc)) from exc
            raise GemmaClientError(str(exc)) from exc
        except genai_errors.ServerError as exc:
            raise GemmaServerError(str(exc)) from exc
        except Exception as exc:  # justify: network/timeout types vary across httpx/requests
            if _looks_like_transport_error(exc):
                raise GemmaServerError(str(exc)) from exc
            raise

        text = response.text or ""
        usage = getattr(response, "usage_metadata", None)
        tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0)
        tokens_out = int(getattr(usage, "candidates_token_count", 0) or 0)
        return RawResponse(text=text, tokens_in=tokens_in, tokens_out=tokens_out)


def _extract_retry_after(exc: Exception) -> float | None:
    """Best-effort Retry-After lookup on a ``google.genai`` ClientError response."""

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


def _looks_like_transport_error(exc: Exception) -> bool:
    """Heuristic: treat httpx/requests/socket errors as 5xx-equivalent."""

    name = type(exc).__module__
    return name.startswith(("httpx", "requests", "urllib3", "socket"))
