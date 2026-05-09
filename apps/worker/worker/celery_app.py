import os
from typing import Final

from celery import Celery
from celery.schedules import crontab

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
