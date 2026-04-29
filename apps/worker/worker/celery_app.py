import os
from typing import Final

from celery import Celery

DEFAULT_BROKER_URL: Final = "redis://redis:6379/1"
DEFAULT_RESULT_BACKEND: Final = "redis://redis:6379/2"

celery_app = Celery(
    "worker",
    broker=os.getenv("CELERY_BROKER_URL", DEFAULT_BROKER_URL),
    backend=os.getenv("CELERY_RESULT_BACKEND", DEFAULT_RESULT_BACKEND),
    include=["worker.tasks.ping"],
)

celery_app.conf.update(
    task_default_queue="codescan",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)
