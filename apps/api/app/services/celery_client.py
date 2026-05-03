"""Thin Celery enqueue helpers used by the API.

The API process must not import anything from ``apps/worker``; it only sends
tasks by name on the shared broker. This keeps the API deployable independently
and prevents accidental coupling to worker-side imports
(``google-genai``, scanners, etc.).
"""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from celery import Celery

from app.core.config import settings

PREPARE_UPLOAD_TASK_NAME = "worker.tasks.prepare_upload.prepare_upload"
RUN_SCAN_TASK_NAME = "worker.tasks.run_scan.run_scan"
DEFAULT_QUEUE = "codescan"


@lru_cache(maxsize=1)
def _celery_app() -> Celery:
    """Create a process-wide Celery app for enqueueing only.

    Cached so we don't churn connections; the broker URL is captured at first
    call. Tests should patch ``enqueue_prepare_upload`` directly rather than
    poking at this app.
    """

    return Celery("codescan-api-enqueue", broker=settings.celery_broker_url)


def enqueue_prepare_upload(upload_id: UUID) -> None:
    """Send a ``prepare_upload`` task to the worker queue."""

    _celery_app().send_task(
        PREPARE_UPLOAD_TASK_NAME,
        args=[str(upload_id)],
        queue=DEFAULT_QUEUE,
    )


def enqueue_run_scan(scan_id: UUID) -> None:
    """Send a ``run_scan`` task to the worker queue."""

    _celery_app().send_task(
        RUN_SCAN_TASK_NAME,
        args=[str(scan_id)],
        queue=DEFAULT_QUEUE,
    )
