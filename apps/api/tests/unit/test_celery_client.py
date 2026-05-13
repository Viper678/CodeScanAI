"""Regression: api producer Celery keyprefix (M3).

The api's enqueue-only Celery app must set the same ``global_keyprefix`` on
``broker_transport_options`` as the worker's consumer-side Celery app (see
``apps/worker/worker/celery_app.py`` and ``apps/worker/tests/test_celery_app.py``).
A mismatch is silent: producer pushes to ``codescan``, consumer subscribes to
``celery-broker:codescan``, and tasks never get delivered. Codex P1 on M3.
"""

from __future__ import annotations

from app.services.celery_client import _celery_app


def test_api_celery_app_has_broker_global_keyprefix() -> None:
    _celery_app.cache_clear()
    app = _celery_app()
    assert app.conf.broker_transport_options == {
        "global_keyprefix": "celery-broker:",
    }
