"""End-to-end test for ``cleanup_old_uploads`` against a real Postgres.

Skipped automatically when no Postgres is reachable. Mirrors
``test_prepare_upload.py``'s schema-bootstrap pattern. We apply the
upload-side DDL only (the cascade through files/scans/findings is
covered by the api's migration round-trip in
``apps/api/tests/integration/test_migrations.py``); this test focuses
on the upload row + on-disk artifacts which are what cleanup actually
manages directly.
"""

from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


def _host_test_url(url: URL) -> URL:
    if url.host == "postgres":
        return url.set(host="localhost")
    return url


def _render(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def _admin_url(base_sync_url: str) -> str:
    return _render(
        _host_test_url(make_url(base_sync_url)).set(
            drivername="postgresql",
            database="postgres",
        )
    )


def _build_test_url(base_sync_url: str, db_name: str) -> tuple[str, str]:
    sync = _host_test_url(make_url(base_sync_url)).set(database=db_name)
    psycopg_url = sync.set(drivername="postgresql")
    return _render(sync), _render(psycopg_url)


def _create_db(admin_url: str, db_name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))


def _drop_db(admin_url: str, db_name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (db_name,),
        )
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name)))


def _postgres_reachable(admin_url: str) -> bool:
    try:
        with psycopg.connect(admin_url, connect_timeout=2):
            return True
    except psycopg.Error:
        return False


_SCHEMA_DDL = """
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE users (
    id UUID PRIMARY KEY,
    email CITEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE uploads (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('zip', 'loose')),
    size_bytes BIGINT NOT NULL,
    storage_path TEXT NOT NULL,
    extract_path TEXT,
    status TEXT NOT NULL CHECK (status IN ('received', 'extracting', 'ready', 'failed')),
    error TEXT,
    file_count INTEGER NOT NULL DEFAULT 0,
    scannable_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _apply_schema(psycopg_url: str) -> None:
    with psycopg.connect(psycopg_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(_SCHEMA_DDL)


@pytest.fixture(scope="module")
def _base_url() -> str:
    return os.environ.get(
        "DATABASE_SYNC_URL",
        "postgresql+psycopg://codescan:codescan-dev-only-change-me@localhost:5432/codescan",
    )


@pytest.fixture(scope="module")
def _admin(_base_url: str) -> str:
    admin = _admin_url(_base_url)
    if not _postgres_reachable(admin):
        pytest.skip("Postgres not reachable; integration test skipped")
    return admin


@pytest.fixture
def test_db(_base_url: str, _admin: str) -> Generator[tuple[str, str], None, None]:
    db_name = f"codescan_worker_cleanup_it_{uuid4().hex}"
    _create_db(_admin, db_name)
    try:
        sync_url, psycopg_url = _build_test_url(_base_url, db_name)
        _apply_schema(psycopg_url)
        yield sync_url, psycopg_url
    finally:
        _drop_db(_admin, db_name)


@contextmanager
def _engine_session(sync_url: str) -> Iterator[Session]:
    engine = create_engine(sync_url, poolclass=NullPool, future=True)
    Maker = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    session = Maker()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_upload(
    session: Session,
    *,
    storage_path: Path,
    extract_path: Path,
    created_at: datetime,
) -> UUID:
    """Insert a fully-staged upload (status=ready, with extract_path) at a
    specific historical ``created_at`` so the cleanup task sees it as old."""

    from sqlalchemy import text

    user_id = uuid4()
    upload_id = uuid4()

    session.execute(
        text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, :pw)"),
        {
            "id": user_id,
            "email": f"cleanup-it-{uuid4().hex[:8]}@example.com",
            "pw": "not-a-real-hash",
        },
    )
    session.execute(
        text(
            """
            INSERT INTO uploads
                (id, user_id, original_name, kind, size_bytes, storage_path,
                 extract_path, status, created_at, updated_at)
            VALUES
                (:id, :uid, 'repo.zip', 'zip', 100, :sp, :ep, 'ready', :ts, :ts)
            """
        ),
        {
            "id": upload_id,
            "uid": user_id,
            "sp": str(storage_path),
            "ep": str(extract_path),
            "ts": created_at,
        },
    )
    session.commit()
    return upload_id


def test_cleanup_old_uploads_end_to_end(
    test_db: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_url, _ = test_db

    from sqlalchemy import text as sql_text

    from worker.core import config as cfg
    from worker.core import db as worker_db

    monkeypatch.setattr(cfg.settings, "database_sync_url", sync_url)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    monkeypatch.setattr(cfg.settings, "retention_days", 30)

    new_engine = create_engine(sync_url, poolclass=NullPool, future=True)
    new_maker = sessionmaker(bind=new_engine, future=True, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "engine", new_engine)
    monkeypatch.setattr(worker_db, "SessionMaker", new_maker)

    # Seed two uploads — one well past the cutoff, one fresh.
    old_raw = tmp_path / "uploads" / "old-upload"
    old_raw.mkdir(parents=True)
    (old_raw / "repo.zip").write_text("zip-bytes")
    old_extract = tmp_path / "extracts" / "old-upload"
    old_extract.mkdir(parents=True)
    (old_extract / "main.py").write_text("print('old')\n")

    fresh_raw = tmp_path / "uploads" / "fresh-upload"
    fresh_raw.mkdir(parents=True)
    (fresh_raw / "repo.zip").write_text("zip-bytes")

    now = datetime.now(tz=UTC)
    with _engine_session(sync_url) as session:
        old_id = _seed_upload(
            session,
            storage_path=old_raw / "repo.zip",
            extract_path=old_extract,
            created_at=now - timedelta(days=90),
        )
        # Move the upload's storage to its real id-namespaced dir so the
        # cleanup task's ``data_dir/uploads/<id>`` lookup finds the bytes.
        target = tmp_path / "uploads" / str(old_id)
        old_raw.rename(target)

        fresh_id = _seed_upload(
            session,
            storage_path=fresh_raw / "repo.zip",
            extract_path=tmp_path / "extracts" / "fresh-upload",
            created_at=now - timedelta(days=1),
        )
        target_fresh = tmp_path / "uploads" / str(fresh_id)
        fresh_raw.rename(target_fresh)
        # Update the extract_path on the old row so it points at the
        # post-rename location too — the seed used the pre-rename literal.
        session.execute(
            sql_text("UPDATE uploads SET extract_path = :ep WHERE id = :id"),
            {"ep": str(old_extract), "id": old_id},
        )
        session.commit()

    # Run the task.
    from worker.tasks.cleanup import cleanup_old_uploads

    result = cleanup_old_uploads()

    assert result == {"swept": 1, "errors": 0}

    # Old upload row + disk artifacts gone; fresh one untouched.
    with _engine_session(sync_url) as session:
        from sqlalchemy import text

        rows = session.execute(text("SELECT id FROM uploads ORDER BY created_at")).all()
        assert [r[0] for r in rows] == [fresh_id]

    assert not (tmp_path / "uploads" / str(old_id)).exists()
    assert not old_extract.exists()
    assert (tmp_path / "uploads" / str(fresh_id)).exists()


def test_cleanup_disabled_runs_no_db_queries(
    test_db: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When retention_days is None the task must short-circuit before opening
    a session — even if there's an old upload sitting in the test DB."""

    sync_url, _ = test_db

    from worker.core import config as cfg
    from worker.core import db as worker_db

    monkeypatch.setattr(cfg.settings, "database_sync_url", sync_url)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    monkeypatch.setattr(cfg.settings, "retention_days", None)

    new_engine = create_engine(sync_url, poolclass=NullPool, future=True)
    new_maker = sessionmaker(bind=new_engine, future=True, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "engine", new_engine)
    monkeypatch.setattr(worker_db, "SessionMaker", new_maker)

    # Drop a row that *would* be swept if retention were on.
    raw = tmp_path / "uploads" / "stale"
    raw.mkdir(parents=True)
    with _engine_session(sync_url) as session:
        upload_id = _seed_upload(
            session,
            storage_path=raw / "x.zip",
            extract_path=tmp_path / "extracts" / "stale",
            created_at=datetime.now(tz=UTC) - timedelta(days=365),
        )
        target = tmp_path / "uploads" / str(upload_id)
        raw.rename(target)

    from worker.tasks.cleanup import cleanup_old_uploads

    result = cleanup_old_uploads()

    assert result == {"swept": 0, "errors": 0}
    # Row still there.
    with _engine_session(sync_url) as session:
        from sqlalchemy import text

        rows = session.execute(text("SELECT id FROM uploads")).all()
        assert len(rows) == 1
    # Disk still there.
    assert (tmp_path / "uploads" / str(upload_id)).exists()
