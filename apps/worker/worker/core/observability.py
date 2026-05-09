"""Worker observability hooks (T5.4): Celery signals for correlation IDs.

Kept separate from ``worker.core.logging`` because the formatter / scrub
filter are pure-Python (no Celery import) and unit-testable in isolation.
The signal handlers pull in Celery and need to run when
``worker.celery_app`` is imported.
"""

from __future__ import annotations

import logging
from typing import Any

from celery.signals import task_failure, task_postrun, task_prerun

from worker.core.logging import (
    file_id_var,
    scan_id_var,
    task_id_var,
    upload_id_var,
)

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
