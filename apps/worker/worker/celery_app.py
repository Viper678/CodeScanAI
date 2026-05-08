"""Celery app + worker-process startup signal handler.

The startup hook clears any Postgres advisory locks the recycled worker
process may have left behind on its previous incarnation — a dead psycopg
session's locks linger until Postgres notices the TCP connection died, which
can take minutes. See ``apps/worker/worker/tasks/run_scan.py`` for the lock
policy.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Final

from celery import Celery
from celery.signals import worker_process_init
from sqlalchemy import func, select

DEFAULT_BROKER_URL: Final = "redis://redis:6379/1"
DEFAULT_RESULT_BACKEND: Final = "redis://redis:6379/2"

logger = logging.getLogger(__name__)

celery_app = Celery(
    "worker",
    broker=os.getenv("CELERY_BROKER_URL", DEFAULT_BROKER_URL),
    backend=os.getenv("CELERY_RESULT_BACKEND", DEFAULT_RESULT_BACKEND),
    include=["worker.tasks.ping", "worker.tasks.prepare_upload", "worker.tasks.run_scan"],
)

celery_app.conf.update(
    task_default_queue="codescan",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)


def _release_orphan_advisory_locks() -> None:
    """Drop any advisory locks held by this process's pooled connections.

    Runs once per worker process at fork-time. Imports are lazy so importing
    ``celery_app`` for task discovery doesn't pull the SQLAlchemy engine.
    """

    from worker.core import db as worker_db

    try:
        with worker_db.engine.connect() as conn:
            conn.execute(select(func.pg_advisory_unlock_all()))
    except Exception:  # justify: cleanup must not crash worker startup
        logger.exception("pg_advisory_unlock_all on worker startup failed")


@worker_process_init.connect  # type: ignore[misc]
def _on_worker_process_init(**_: Any) -> None:
    _release_orphan_advisory_locks()
