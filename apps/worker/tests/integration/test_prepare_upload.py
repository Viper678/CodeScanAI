"""End-to-end test for ``prepare_upload`` against a real Postgres.

Skipped automatically when no Postgres is reachable on the configured URL.
Mirrors the api's ``_build_database_urls`` (compose hostname → localhost)
helper so the suite can run from inside a host shell or inside docker.
"""

from __future__ import annotations

import io
import os
import zipfile
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, select
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
    """Return (sqlalchemy_url, psycopg_url) for a fresh test database."""

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


# ---- Schema setup -----------------------------------------------------------

# We avoid invoking the api's alembic from the worker test process; instead
# we apply the same DDL directly so the test runs without depending on the
# api package being installed in the worker's venv.
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

CREATE TABLE files (
    id UUID PRIMARY KEY,
    upload_id UUID NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    language TEXT,
    is_binary BOOLEAN NOT NULL,
    is_excluded_by_default BOOLEAN NOT NULL,
    excluded_reason TEXT,
    sha256 TEXT NOT NULL,
    CONSTRAINT uq_files_upload_id_path UNIQUE (upload_id, path)
);
CREATE INDEX ix_files_upload_id_path ON files (upload_id, path);
CREATE INDEX ix_files_upload_id_parent_path ON files (upload_id, parent_path);
"""


def _apply_schema(psycopg_url: str) -> None:
    with psycopg.connect(psycopg_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(_SCHEMA_DDL)


# ---- Fixtures ---------------------------------------------------------------


@pytest.fixture(scope="module")
def _base_url() -> str:
    # Reload settings here in case the env was set after worker import.
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
    db_name = f"codescan_worker_it_{uuid4().hex}"
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


# ---- Helpers ----------------------------------------------------------------


def _make_zip(path: Path) -> int:
    payload: dict[str, str] = {
        "src/main.py": "print('hi')\n",
        "src/utils.js": "module.exports = 1;\n",
        "src/lib/helper.py": "x = 1\n",
        "node_modules/lodash/index.js": "module.exports = {};\n",
        "README.md": "# hello\n",
        ".git/HEAD": "ref: refs/heads/main\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in payload.items():
            zf.writestr(name, body)
    data = buf.getvalue()
    path.write_bytes(data)
    return len(data)


def _insert_user(session: Session) -> UUID:
    from sqlalchemy import text

    from worker.core.uuid7 import uuid7

    user_id = uuid7()
    session.execute(
        text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, :pw)"),
        {
            "id": user_id,
            "email": f"worker-it-{uuid4().hex[:8]}@example.com",
            "pw": "not-a-real-hash",
        },
    )
    session.commit()
    return user_id


def _insert_upload(
    session: Session,
    *,
    user_id: UUID,
    storage_path: Path,
    size_bytes: int,
    kind: str,
    original_name: str,
) -> UUID:
    from worker.core.models import UPLOAD_STATUS_RECEIVED, Upload
    from worker.core.uuid7 import uuid7

    upload = Upload(
        id=uuid7(),
        user_id=user_id,
        original_name=original_name,
        kind=kind,
        size_bytes=size_bytes,
        storage_path=str(storage_path),
        status=UPLOAD_STATUS_RECEIVED,
        file_count=0,
        scannable_count=0,
    )
    session.add(upload)
    session.commit()
    return upload.id


# ---- The actual test --------------------------------------------------------


def test_prepare_upload_extracts_zip_end_to_end(
    test_db: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_url, _ = test_db

    # Point the worker's settings/sessionmaker at the freshly-built test DB.
    from worker.core import config as cfg
    from worker.core import db as worker_db

    monkeypatch.setattr(cfg.settings, "database_sync_url", sync_url)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)

    new_engine = create_engine(sync_url, poolclass=NullPool, future=True)
    new_maker = sessionmaker(bind=new_engine, future=True, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "engine", new_engine)
    monkeypatch.setattr(worker_db, "SessionMaker", new_maker)

    # Build the synthetic upload on disk.
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    zip_path = upload_dir / "demo.zip"
    size = _make_zip(zip_path)

    with _engine_session(sync_url) as session:
        user_id = _insert_user(session)
        upload_id = _insert_upload(
            session,
            user_id=user_id,
            storage_path=zip_path,
            size_bytes=size,
            kind="zip",
            original_name="demo.zip",
        )

    # Run the task synchronously (don't use .delay()).
    from worker.tasks.prepare_upload import prepare_upload

    result = prepare_upload.run(str(upload_id))
    assert result["status"] == "ready"

    # Re-read state from the DB.
    with _engine_session(sync_url) as session:
        from worker.core.models import File, Upload

        upload = session.scalar(select(Upload).where(Upload.id == upload_id))
        assert upload is not None
        assert upload.status == "ready"
        assert upload.error is None
        assert upload.file_count == 6
        # 3 scannable: src/main.py, src/utils.js, src/lib/helper.py, README.md
        # node_modules/lodash/index.js → vendor_dir, .git/HEAD → vcs_dir
        assert upload.scannable_count == 4
        assert upload.extract_path is not None
        assert Path(upload.extract_path).is_dir()

        files = list(
            session.scalars(select(File).where(File.upload_id == upload_id).order_by(File.path))
        )
        by_path = {f.path: f for f in files}

        assert ".git/HEAD" in by_path
        assert by_path[".git/HEAD"].excluded_reason == "vcs_dir"
        assert by_path[".git/HEAD"].is_excluded_by_default is True
        assert by_path[".git/HEAD"].parent_path == ".git"
        assert by_path[".git/HEAD"].name == "HEAD"

        node = by_path["node_modules/lodash/index.js"]
        assert node.excluded_reason == "vendor_dir"
        assert node.is_excluded_by_default is True

        main = by_path["src/main.py"]
        assert main.is_excluded_by_default is False
        assert main.language == "python"
        assert main.is_binary is False
        assert main.parent_path == "src"
        assert main.name == "main.py"
        assert main.sha256  # populated

        readme = by_path["README.md"]
        assert readme.language == "markdown"
        assert readme.parent_path == ""


def test_prepare_upload_loose_kind_walks_loose_subdir(
    test_db: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_url, _ = test_db

    from worker.core import config as cfg
    from worker.core import db as worker_db

    monkeypatch.setattr(cfg.settings, "database_sync_url", sync_url)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    new_engine = create_engine(sync_url, poolclass=NullPool, future=True)
    new_maker = sessionmaker(bind=new_engine, future=True, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "engine", new_engine)
    monkeypatch.setattr(worker_db, "SessionMaker", new_maker)

    upload_dir = tmp_path / "uploads" / "loose-upload"
    loose = upload_dir / "loose"
    loose.mkdir(parents=True, exist_ok=True)
    (loose / "snippet.py").write_text("def f():\n    return 1\n")
    (loose / "notes.md").write_text("# notes\n")

    with _engine_session(sync_url) as session:
        user_id = _insert_user(session)
        upload_id = _insert_upload(
            session,
            user_id=user_id,
            storage_path=upload_dir,
            size_bytes=99,
            kind="loose",
            original_name="loose-bundle",
        )

    from worker.tasks.prepare_upload import prepare_upload

    result = prepare_upload.run(str(upload_id))
    assert result["status"] == "ready"
    assert result["file_count"] == 2
    assert result["scannable_count"] == 2


def test_prepare_upload_marks_failed_on_zip_bomb(
    test_db: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_url, _ = test_db

    from worker.core import config as cfg
    from worker.core import db as worker_db

    monkeypatch.setattr(cfg.settings, "database_sync_url", sync_url)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    new_engine = create_engine(sync_url, poolclass=NullPool, future=True)
    new_maker = sessionmaker(bind=new_engine, future=True, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "engine", new_engine)
    monkeypatch.setattr(worker_db, "SessionMaker", new_maker)

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    zip_path = upload_dir / "bomb.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zeros.bin", b"\x00" * (1024 * 1024))
    zip_path.write_bytes(buf.getvalue())

    with _engine_session(sync_url) as session:
        user_id = _insert_user(session)
        upload_id = _insert_upload(
            session,
            user_id=user_id,
            storage_path=zip_path,
            size_bytes=zip_path.stat().st_size,
            kind="zip",
            original_name="bomb.zip",
        )

    from worker.files.safety import SafetyError
    from worker.tasks.prepare_upload import prepare_upload

    with pytest.raises(SafetyError):
        prepare_upload.run(str(upload_id))

    with _engine_session(sync_url) as session:
        from worker.core.models import File, Upload

        upload = session.scalar(select(Upload).where(Upload.id == upload_id))
        assert upload is not None
        assert upload.status == "failed"
        assert upload.error
        # No files persisted.
        files = list(session.scalars(select(File).where(File.upload_id == upload_id)))
        assert files == []
        # Extract dir cleaned up.
        extract_root = tmp_path / "extracts" / str(upload_id)
        assert not extract_root.exists()
