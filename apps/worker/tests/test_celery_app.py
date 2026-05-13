"""Regression: Celery transport keyprefixes (M3).

The Celery broker, the Celery result backend, and the api's rate limiter all
share one Redis db post-M3 (single legacy Memorystore for Redis in prod, see
docs/GCP_MIGRATION.md §M3 / §D1). ``broker_transport_options`` /
``result_backend_transport_options`` carry ``global_keyprefix`` so broker /
result keys live under their own namespaces and cannot collide with rate-limit
keys (which live under ``rl:``).

If a future refactor drops or renames these prefixes the collision risk silently
returns — keys would interleave on the same db with no error at startup, and
the failure mode would be a Celery worker mis-parsing what it thinks is a
queued task. The assertions below are the cheapest invariant guard.
"""

from __future__ import annotations

from worker.celery_app import celery_app


def test_broker_transport_options_set_global_keyprefix() -> None:
    assert celery_app.conf.broker_transport_options == {
        "global_keyprefix": "celery-broker:",
    }


def test_result_backend_transport_options_set_global_keyprefix() -> None:
    assert celery_app.conf.result_backend_transport_options == {
        "global_keyprefix": "celery-result:",
    }
