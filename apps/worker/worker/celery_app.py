import os
from typing import Any, Final

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging

from worker.core.config import settings
from worker.core.logging import configure_logging
from worker.core.observability import register_signal_handlers


# Take over Celery's logging setup entirely. Without this, when the worker
# is started via ``celery worker --loglevel=info`` the Celery bootstrap
# would run AFTER our import-time ``configure_logging`` and reset the root
# logger's level to the CLI loglevel — silently overriding the
# ``LOG_LEVEL`` env knob we advertise as the source of truth.
# Connecting any handler to ``setup_logging`` tells Celery "I've handled
# logging, don't touch it" — the CLI ``--loglevel`` flag becomes a no-op
# and ``settings.log_level`` (env-driven) wins.
@setup_logging.connect  # type: ignore[misc]  # justify: celery signal decorators are untyped
def _setup_logging(**_kwargs: Any) -> None:
    configure_logging(level=settings.log_level)


# Run once at module import time as a backup — covers code paths that
# import the celery_app module without going through ``celery worker``
# (e.g. the api enqueueing tasks, unit tests). The signal handler above
# re-runs on actual worker startup. ``configure_logging`` is idempotent.
configure_logging(level=settings.log_level)
register_signal_handlers()

DEFAULT_BROKER_URL: Final = "redis://redis:6379/1"
DEFAULT_RESULT_BACKEND: Final = "redis://redis:6379/2"

celery_app = Celery(
    "worker",
    broker=os.getenv("CELERY_BROKER_URL", DEFAULT_BROKER_URL),
    backend=os.getenv("CELERY_RESULT_BACKEND", DEFAULT_RESULT_BACKEND),
    include=[
        "worker.tasks.ping",
        "worker.tasks.prepare_upload",
        "worker.tasks.run_scan",
        "worker.tasks.cleanup",
    ],
)

celery_app.conf.update(
    task_default_queue="codescan",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    # T5.4: keep our JSON formatter + scrub filter on the root logger.
    # Celery's default ``worker_hijack_root_logger=True`` would replace
    # the handlers we install in ``configure_logging`` once the worker
    # bootstrap finishes, silently downgrading task logs to Celery's
    # ColorFormatter and bypassing the API-key scrub. Disabling the
    # hijack lets our setup survive into task execution.
    worker_hijack_root_logger=False,
    # Daily retention sweep — beat ticks at 03:00 UTC. The task itself reads
    # ``settings.retention_days`` and short-circuits when retention is None
    # (the default), so an "always-scheduled, sometimes no-op" shape lets
    # operators flip retention on/off via env without touching beat config.
    # See worker/tasks/cleanup.py and docs/FILE_HANDLING.md §"Garbage collection".
    beat_schedule={
        "cleanup-old-uploads": {
            "task": "worker.tasks.cleanup.cleanup_old_uploads",
            "schedule": crontab(hour="3", minute="0"),
        },
    },
)
