from worker.celery_app import celery_app


@celery_app.task(name="worker.tasks.ping")  # type: ignore[misc]
def ping() -> str:
    return "pong"
