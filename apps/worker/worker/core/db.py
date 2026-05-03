"""Synchronous SQLAlchemy session factory for worker tasks.

Celery tasks are sync, so the worker uses ``psycopg`` directly via SQLAlchemy
core/ORM rather than the api's async engine. The ORM models themselves live
in the api package — we re-declare a sync ``Base`` here only as a structural
mirror; we never run migrations from the worker.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from worker.core.config import settings

engine: Engine = create_engine(settings.database_sync_url, pool_pre_ping=True, future=True)
SessionMaker = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Commits on clean exit, rolls back on exception. The caller is responsible
    for raising — we always re-raise.
    """

    session = SessionMaker()
    try:
        yield session
        session.commit()
    except Exception:
        # justify: we re-raise so Celery records the failure; rollback first.
        session.rollback()
        raise
    finally:
        session.close()
