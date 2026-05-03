"""End-to-end test for the ``run_scan`` orchestrator against a real Postgres.

Skipped automatically when no Postgres is reachable on the configured URL.
GemmaClient is mocked so the test never makes a network call; the real
in-process keyword scanner runs unmodified.
"""

from __future__ import annotations

import os
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

CREATE TABLE scans (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    upload_id UUID NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    name TEXT,
    scan_types TEXT[] NOT NULL,
    keywords JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL,
    progress_done INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error TEXT,
    model TEXT NOT NULL DEFAULT 'gemma-4-31b-it',
    model_settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_scans_user_id_created_at ON scans (user_id, created_at DESC);
CREATE INDEX ix_scans_upload_id ON scans (upload_id);
CREATE INDEX ix_scans_status ON scans (status);

CREATE TABLE scan_files (
    id UUID PRIMARY KEY,
    scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    file_id UUID NOT NULL REFERENCES files(id),
    status TEXT NOT NULL,
    error TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    latency_ms INTEGER,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    CONSTRAINT uq_scan_files_scan_id_file_id UNIQUE (scan_id, file_id)
);
CREATE INDEX ix_scan_files_scan_id_status ON scan_files (scan_id, status);

CREATE TABLE scan_findings (
    id UUID PRIMARY KEY,
    scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    file_id UUID NOT NULL REFERENCES files(id),
    scan_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    recommendation TEXT,
    line_start INTEGER,
    line_end INTEGER,
    snippet TEXT,
    rule_id TEXT,
    confidence NUMERIC(3, 2),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_scan_findings_scan_id_severity ON scan_findings (scan_id, severity);
CREATE INDEX ix_scan_findings_scan_id_scan_type ON scan_findings (scan_id, scan_type);
CREATE INDEX ix_scan_findings_scan_id_file_id ON scan_findings (scan_id, file_id);
"""


def _apply_schema(psycopg_url: str) -> None:
    with psycopg.connect(psycopg_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(_SCHEMA_DDL)


# ---- Fixtures ---------------------------------------------------------------


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
    db_name = f"codescan_worker_runscan_{uuid4().hex}"
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


# ---- Seed helpers -----------------------------------------------------------


def _insert_user(session: Session) -> UUID:
    from sqlalchemy import text

    from worker.core.uuid7 import uuid7

    user_id = uuid7()
    session.execute(
        text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, :pw)"),
        {
            "id": user_id,
            "email": f"runscan-{uuid4().hex[:8]}@example.com",
            "pw": "not-a-real-hash",
        },
    )
    session.commit()
    return user_id


def _insert_upload_and_files(
    session: Session,
    *,
    user_id: UUID,
    extract_root: Path,
) -> tuple[UUID, list[UUID]]:
    """Create an upload + 3 files (py, md, binary) and write them to disk.

    Returns (upload_id, [file_id_py, file_id_md, file_id_bin]).
    """

    from worker.core.models import UPLOAD_STATUS_READY, File, Upload
    from worker.core.uuid7 import uuid7

    extract_root.mkdir(parents=True, exist_ok=True)
    py_content = "# TODO: refactor this\nprint('hello')\n"
    md_content = "# Notes\nNothing TODO here.\n"
    bin_content = b"\x00\x01\x02BIN"

    (extract_root / "main.py").write_text(py_content)
    (extract_root / "README.md").write_text(md_content)
    (extract_root / "blob.bin").write_bytes(bin_content)

    upload = Upload(
        id=uuid7(),
        user_id=user_id,
        original_name="bundle.zip",
        kind="zip",
        size_bytes=999,
        storage_path=str(extract_root),
        extract_path=str(extract_root),
        status=UPLOAD_STATUS_READY,
        file_count=3,
        scannable_count=2,
    )
    session.add(upload)
    session.flush()

    f_py = File(
        id=uuid7(),
        upload_id=upload.id,
        path="main.py",
        name="main.py",
        parent_path="",
        size_bytes=len(py_content.encode()),
        language="python",
        is_binary=False,
        is_excluded_by_default=False,
        excluded_reason=None,
        sha256="a" * 64,
    )
    f_md = File(
        id=uuid7(),
        upload_id=upload.id,
        path="README.md",
        name="README.md",
        parent_path="",
        size_bytes=len(md_content.encode()),
        language="markdown",
        is_binary=False,
        is_excluded_by_default=False,
        excluded_reason=None,
        sha256="b" * 64,
    )
    f_bin = File(
        id=uuid7(),
        upload_id=upload.id,
        path="blob.bin",
        name="blob.bin",
        parent_path="",
        size_bytes=len(bin_content),
        language=None,
        is_binary=True,
        is_excluded_by_default=True,
        excluded_reason="binary",
        sha256="c" * 64,
    )
    session.add_all([f_py, f_md, f_bin])
    session.commit()
    return upload.id, [f_py.id, f_md.id, f_bin.id]


def _insert_scan(
    session: Session,
    *,
    user_id: UUID,
    upload_id: UUID,
    file_ids: list[UUID],
) -> UUID:
    from worker.core.models import (
        SCAN_FILE_STATUS_PENDING,
        SCAN_STATUS_PENDING,
        Scan,
        ScanFile,
    )
    from worker.core.uuid7 import uuid7

    scan = Scan(
        id=uuid7(),
        user_id=user_id,
        upload_id=upload_id,
        name="t",
        scan_types=["security", "bugs", "keywords"],
        keywords={"items": ["TODO"], "case_sensitive": False, "regex": False},
        status=SCAN_STATUS_PENDING,
        progress_done=0,
        progress_total=len(file_ids),
        model="gemma-4-31b-it",
        model_settings={},
    )
    session.add(scan)
    session.flush()
    for fid in file_ids:
        session.add(
            ScanFile(
                id=uuid7(),
                scan_id=scan.id,
                file_id=fid,
                status=SCAN_FILE_STATUS_PENDING,
            )
        )
    session.commit()
    return scan.id


# ---- Fake scanner factory ---------------------------------------------------


def _fake_registry_factory(scan_types, keywords_cfg):  # type: ignore[no-untyped-def]
    """Build a registry that uses fake security/bugs scanners + the real keyword scanner."""

    from worker.scanners.base import Finding, ScanCallResult, ScanContext
    from worker.scanners.keywords import KeywordScanner

    def _make_canned(scan_type: str, severity: str):  # type: ignore[no-untyped-def]
        class _Canned:
            name = scan_type

            def scan_file(self, content: str, ctx: ScanContext) -> ScanCallResult:
                return ScanCallResult(
                    findings=[
                        Finding(
                            title=f"{scan_type} finding",
                            message="canned",
                            recommendation=None,
                            severity=severity,  # type: ignore[arg-type]
                            line_start=1,
                            line_end=1,
                            rule_id=f"R-{scan_type}",
                            confidence=0.5,
                        )
                    ],
                    tokens_in=100,
                    tokens_out=50,
                    latency_ms=7,
                )

        return _Canned()

    del keywords_cfg
    registry = {}
    if "security" in scan_types:
        registry["security"] = _make_canned("security", "high")
    if "bugs" in scan_types:
        registry["bugs"] = _make_canned("bugs", "medium")
    if "keywords" in scan_types:
        registry["keywords"] = KeywordScanner()
    return registry


# ---- The AC test ------------------------------------------------------------


def test_run_scan_end_to_end_completes_with_findings_and_usage(
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

    extract_root = tmp_path / "uploads" / "extract"
    with _engine_session(sync_url) as session:
        user_id = _insert_user(session)
        upload_id, file_ids = _insert_upload_and_files(
            session, user_id=user_id, extract_root=extract_root
        )
        scan_id = _insert_scan(session, user_id=user_id, upload_id=upload_id, file_ids=file_ids)

    from worker.tasks.run_scan import _run

    result = _run(
        str(scan_id),
        scanner_registry_factory=_fake_registry_factory,
        session_maker=new_maker,
    )
    assert result["status"] == "completed"
    assert result["progress_done"] == 3

    from worker.core.models import Scan, ScanFile, ScanFinding

    with _engine_session(sync_url) as session:
        scan = session.scalar(select(Scan).where(Scan.id == scan_id))
        assert scan is not None
        assert scan.status == "completed"
        assert scan.started_at is not None
        assert scan.finished_at is not None
        assert scan.progress_done == 3

        usage = scan.model_settings.get("usage")
        assert usage is not None
        # 2 non-binary files * (security + bugs) = 4 LLM calls x 100 in / 50 out.
        assert usage["total_tokens_in"] == 400
        assert usage["total_tokens_out"] == 200
        assert usage["calls"] == 4

        sfs = list(session.scalars(select(ScanFile).where(ScanFile.scan_id == scan_id)))
        by_file = {sf.file_id: sf for sf in sfs}
        # Binary file → skipped with reason "binary".
        bin_id = file_ids[2]
        assert by_file[bin_id].status == "skipped"
        assert by_file[bin_id].error == "binary"
        # The two text files → done.
        py_id, md_id = file_ids[0], file_ids[1]
        assert by_file[py_id].status == "done"
        assert by_file[md_id].status == "done"
        assert by_file[py_id].tokens_in == 200  # security + bugs
        assert by_file[py_id].tokens_out == 100

        findings = list(session.scalars(select(ScanFinding).where(ScanFinding.scan_id == scan_id)))
        # 2 non-binary files x (1 security + 1 bugs) = 4 LLM findings,
        # plus 1 keyword finding (only main.py contains "TODO" — README has
        # "Nothing TODO here" too, that's another match).
        # main.py: "# TODO: refactor this" → 1 keyword
        # README.md: "Nothing TODO here." → 1 keyword
        # → 4 + 2 = 6 total findings
        assert len(findings) == 6
        kw = [f for f in findings if f.scan_type == "keywords"]
        assert len(kw) == 2
        assert all(f.severity == "info" for f in kw)
        sec = [f for f in findings if f.scan_type == "security"]
        assert len(sec) == 2
        assert all(f.severity == "high" for f in sec)


def test_run_scan_idempotent_when_already_completed(
    test_db: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-delivery of a completed scan must no-op rather than re-running."""

    sync_url, _ = test_db
    from worker.core import config as cfg
    from worker.core import db as worker_db

    monkeypatch.setattr(cfg.settings, "database_sync_url", sync_url)
    new_engine = create_engine(sync_url, poolclass=NullPool, future=True)
    new_maker = sessionmaker(bind=new_engine, future=True, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "engine", new_engine)
    monkeypatch.setattr(worker_db, "SessionMaker", new_maker)

    extract_root = tmp_path / "uploads" / "extract"
    with _engine_session(sync_url) as session:
        user_id = _insert_user(session)
        upload_id, file_ids = _insert_upload_and_files(
            session, user_id=user_id, extract_root=extract_root
        )
        scan_id = _insert_scan(session, user_id=user_id, upload_id=upload_id, file_ids=file_ids)

    # Pre-mark as completed.
    from worker.core.models import Scan

    with _engine_session(sync_url) as session:
        scan = session.scalar(select(Scan).where(Scan.id == scan_id))
        assert scan is not None
        scan.status = "completed"
        session.commit()

    from worker.tasks.run_scan import _run

    def _boom_factory(_types, _kw):  # type: ignore[no-untyped-def]
        raise AssertionError("scanner_registry_factory must not be invoked")

    result = _run(
        str(scan_id),
        scanner_registry_factory=_boom_factory,
        session_maker=new_maker,
    )
    assert result["status"] == "completed"


def test_run_scan_re_entry_skips_already_finalized_scan_files(
    test_db: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex P1 on PR #20: re-delivery of a partially-completed scan must not
    re-process scan_files that already finalized — that would duplicate
    scan_findings and bump scan.progress_done past progress_total."""

    sync_url, _ = test_db
    from worker.core import config as cfg
    from worker.core import db as worker_db

    monkeypatch.setattr(cfg.settings, "database_sync_url", sync_url)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    new_engine = create_engine(sync_url, poolclass=NullPool, future=True)
    new_maker = sessionmaker(bind=new_engine, future=True, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "engine", new_engine)
    monkeypatch.setattr(worker_db, "SessionMaker", new_maker)

    extract_root = tmp_path / "uploads" / "extract"
    with _engine_session(sync_url) as session:
        user_id = _insert_user(session)
        upload_id, file_ids = _insert_upload_and_files(
            session, user_id=user_id, extract_root=extract_root
        )
        scan_id = _insert_scan(session, user_id=user_id, upload_id=upload_id, file_ids=file_ids)

    from datetime import UTC
    from datetime import datetime as dt

    from worker.core.models import Scan, ScanFile, ScanFinding

    # Pre-finalize the .py file (file_ids[0]) as if a previous delivery did it,
    # and leave the scan in `running`. Bump progress_done to 1 to mirror the
    # bookkeeping the orchestrator would have done.
    with _engine_session(sync_url) as session:
        scan = session.scalar(select(Scan).where(Scan.id == scan_id))
        assert scan is not None
        scan.status = "running"
        scan.started_at = dt.now(UTC)
        scan.progress_done = 1
        sf = session.scalar(
            select(ScanFile).where(ScanFile.scan_id == scan_id, ScanFile.file_id == file_ids[0])
        )
        assert sf is not None
        sf.status = "done"
        sf.finished_at = dt.now(UTC)
        sf.tokens_in = 999
        sf.tokens_out = 111
        # Pretend the previous delivery already wrote one finding for this file.
        session.add(
            ScanFinding(
                scan_id=scan_id,
                file_id=file_ids[0],
                scan_type="security",
                severity="high",
                title="prior finding",
                message="from previous delivery",
                recommendation=None,
                line_start=1,
                line_end=1,
                snippet=None,
                rule_id="R-prior",
                confidence=None,
                meta={},
            )
        )
        session.commit()

    from worker.tasks.run_scan import _run

    result = _run(
        str(scan_id),
        scanner_registry_factory=_fake_registry_factory,
        session_maker=new_maker,
    )

    assert result["status"] == "completed"

    with _engine_session(sync_url) as session:
        scan = session.scalar(select(Scan).where(Scan.id == scan_id))
        assert scan is not None
        # progress_done must NOT exceed progress_total — re-entry skipped the
        # already-done file so we end at 3, not 4.
        assert scan.progress_done == scan.progress_total == 3

        # The previously-done .py file kept its prior finding, was NOT re-scanned.
        py_findings = list(
            session.scalars(
                select(ScanFinding).where(
                    ScanFinding.scan_id == scan_id, ScanFinding.file_id == file_ids[0]
                )
            )
        )
        # Only the prior finding survives; no duplicate inserts from re-delivery.
        assert len(py_findings) == 1
        assert py_findings[0].title == "prior finding"

        # The .md file got freshly scanned this delivery.
        md_findings = list(
            session.scalars(
                select(ScanFinding).where(
                    ScanFinding.scan_id == scan_id, ScanFinding.file_id == file_ids[1]
                )
            )
        )
        assert len(md_findings) >= 1
