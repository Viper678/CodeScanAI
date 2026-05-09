"""Worker observability hooks (T5.4): Celery signals + optional Sentry init.

Kept separate from ``worker.core.logging`` because the formatter / scrub
filter are pure-Python (no Celery import) and unit-testable in isolation.
The signal handlers + Sentry init pull in Celery / sentry_sdk lazily and
need to run when ``worker.celery_app`` is imported.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

from celery.signals import task_failure, task_postrun, task_prerun

from worker.core.config import settings
from worker.core.logging import (
    file_id_var,
    scan_id_var,
    task_id_var,
    upload_id_var,
)

# Mirror of the regex in ``worker.core.logging`` — kept as a local copy here
# rather than imported because the Sentry ``before_send`` path runs OUTSIDE
# Python's logging system (so depending on log-internal symbols would invite
# an import cycle). Same shape: ``AIza`` followed by 35 chars of [A-Za-z0-9_-].
_SENTRY_API_KEY_PATTERN: Final = re.compile(r"AIza[A-Za-z0-9_-]{35}")
_SENTRY_REDACTED: Final = "AIza<redacted>"


def _scrub_sentry_value(value: Any) -> Any:
    """Recursive scrub for Sentry event payloads.

    Sentry's ``CeleryIntegration`` captures task failures via
    ``event_from_exception(exc_info, …)`` — the exception value, args, and
    chained traceback strings land in the event dict directly, bypassing
    our log scrub. Redact any ``AIza…`` shape we encounter so the worker
    never ships the Google API key to Sentry's ingest.
    """

    if isinstance(value, str):
        return _SENTRY_API_KEY_PATTERN.sub(_SENTRY_REDACTED, value)
    if isinstance(value, dict):
        return {k: _scrub_sentry_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_sentry_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_sentry_value(item) for item in value)
    return value


def _sentry_before_send(event: Any, _hint: dict[str, Any]) -> Any:
    """``sentry_sdk`` ``before_send`` hook — last-line PII / API-key scrub.

    Typed as ``Any`` to match ``sentry_sdk``'s typed ``Event`` TypedDict
    without importing it at module scope (the SDK is an optional dep).
    Returning the event passes it through to Sentry; returning ``None``
    drops it. We always return a (possibly-mutated) event so legitimate
    error tracking still works.

    Defensive strip mirrors the api-side hook: even though
    ``include_local_variables=False`` and ``max_request_body_size='never'``
    are set on init, we re-apply the invariant here in case a future SDK
    version flips a default.
    """

    if isinstance(event, dict):
        request = event.get("request")
        if isinstance(request, dict):
            request.pop("data", None)
        exception = event.get("exception")
        if isinstance(exception, dict):
            for value in exception.get("values", []):
                if not isinstance(value, dict):
                    continue
                stacktrace = value.get("stacktrace")
                if isinstance(stacktrace, dict):
                    for frame in stacktrace.get("frames", []):
                        if isinstance(frame, dict):
                            frame.pop("vars", None)

    return _scrub_sentry_value(event)


logger = logging.getLogger(__name__)

# Map Celery task names → which contextvar to seed from ``args[0]``. New tasks
# that should populate scan_id / upload_id correlation just append here.
_TASK_NAME_TO_VAR = {
    "worker.tasks.run_scan.run_scan": scan_id_var,
    "worker.tasks.prepare_upload.prepare_upload": upload_id_var,
}


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    # Reject anything that looks like a log-injection attempt — same shape
    # rule as the api's request-id middleware so the two surfaces match.
    if "\n" in text or "\r" in text or len(text) > 64:
        return None
    return text


def _on_task_prerun(  # type: ignore[no-untyped-def]  # justify: celery signal kwargs are untyped
    sender=None, task_id=None, task=None, args=None, **_kwargs
) -> None:
    """Seed correlation contextvars before the task body runs.

    ``task_id_var`` always comes from Celery's task instance UUID. ``scan_id``
    / ``upload_id`` are set when we recognize the task name and ``args[0]``
    looks reasonable. ``file_id`` is left for inner code to set when a
    per-file scope opens (see ``run_scan._process_file``).
    """

    task_name = getattr(task, "name", None) or sender
    coerced_task_id = _safe_str(task_id)
    if coerced_task_id is not None:
        task_id_var.set(coerced_task_id)

    var = _TASK_NAME_TO_VAR.get(task_name) if isinstance(task_name, str) else None
    if var is not None and args:
        coerced = _safe_str(args[0])
        if coerced is not None:
            var.set(coerced)


def _on_task_postrun(  # type: ignore[no-untyped-def]
    sender=None, task_id=None, task=None, args=None, **_kwargs
) -> None:
    """Reset correlation contextvars after the task body returns.

    Celery's prefork pool re-uses the worker process across tasks, so
    failing to clear here would let stale correlation IDs bleed into the
    next task's logs. ``ContextVar.set(None)`` is idempotent and cheap.
    """

    del sender, task_id, task, args
    task_id_var.set(None)
    scan_id_var.set(None)
    upload_id_var.set(None)
    file_id_var.set(None)


def _on_task_failure(  # type: ignore[no-untyped-def]
    sender=None, task_id=None, exception=None, **_kwargs
) -> None:
    """Surface an explicit structured ERROR with correlation IDs still set."""

    del task_id  # available via task_id_var
    task_name = getattr(sender, "name", None) or "unknown"
    logger.error(
        "task failed",
        extra={
            "task_name": task_name,
            "error_class": type(exception).__name__ if exception else None,
        },
    )


def register_signal_handlers() -> None:
    """Hook the prerun / postrun / failure handlers onto Celery's signals.

    Idempotent in practice — Celery's signal connect short-circuits identical
    receivers — but we don't rely on that and keep ``register_signal_handlers``
    callable exactly once at module import time of ``worker.celery_app``.
    """

    task_prerun.connect(_on_task_prerun, weak=False)
    task_postrun.connect(_on_task_postrun, weak=False)
    task_failure.connect(_on_task_failure, weak=False)


def init_sentry_if_configured() -> None:
    """Initialize Sentry when ``SENTRY_DSN`` is set; no-op otherwise.

    Called from ``worker.celery_app`` at import time so the SDK is wired up
    before the first task runs. ``traces_sample_rate=0`` keeps perf data
    off the wire by default.
    """

    if settings.sentry_dsn is None:
        return
    import logging as _logging

    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    # Disable Sentry's LoggingIntegration event capture entirely — keep
    # breadcrumbs (so logs leading up to a failure still attach to the
    # exception event) but stop generating standalone events from log
    # records. Reasoning:
    #
    # - ``CeleryIntegration`` already captures every unhandled task
    #   exception with ``mechanism=celery``. That's the canonical event
    #   we want.
    # - Many task code paths do ``logger.exception(...)`` and then
    #   ``raise`` — without this, Sentry would receive both a logging
    #   event (mechanism=logging, handled=True) AND the celery event
    #   (mechanism=celery, unhandled). Dedupe behaviour between the two
    #   isn't deterministic; we'd see duplicates or, worse, the weaker
    #   logging event winning and the unhandled one getting dropped.
    # - The previous approach (``ignore_logger(__name__)``) only covered
    #   THIS module — task-side loggers (run_scan, scanners, …) still
    #   double-captured.
    #
    # ``event_level=None`` disables event capture; ``level=INFO`` keeps
    # log records as breadcrumbs on whatever exception event eventually
    # fires.
    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        integrations=[
            CeleryIntegration(),
            LoggingIntegration(level=_logging.INFO, event_level=None),
        ],
        traces_sample_rate=0.0,
        send_default_pii=False,
        # Mirror of the api-side hardening — locals on stack frames could
        # leak ``GOOGLE_AI_API_KEY`` (in scope where the SDK is invoked)
        # or file content captured into a scanner local before the
        # Gemma call raised. Worker has no HTTP request body, but
        # disable for symmetry / future-proofing if we ever add HTTP.
        max_request_body_size="never",
        include_local_variables=False,
        # Last-line API-key scrub: the Celery integration captures exceptions
        # via ``event_from_exception`` directly, so a Gemma SDK error whose
        # message includes ``AIza…`` would otherwise ship to Sentry verbatim.
        before_send=_sentry_before_send,
    )
    logger.info("sentry initialized for worker")
