from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable

import psycopg
from conftest import API_ROOT, DatabaseUrls

from alembic import command
from alembic.config import Config


def _table_names(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename IN (
                'users',
                'refresh_tokens',
                'uploads',
                'files',
                'scans',
                'scan_files',
                'scan_findings'
              )
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _files_indexes(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'files'
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _files_unique_constraints(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'public.files'::regclass
              AND contype = 'u'
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _uploads_indexes(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'uploads'
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _scans_indexes(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'scans'
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _scan_files_indexes(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'scan_files'
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _scan_files_unique_constraints(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'public.scan_files'::regclass
              AND contype = 'u'
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _scan_findings_indexes(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'scan_findings'
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _has_citext_extension(psycopg_url: str) -> bool:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'citext'")
        return cursor.fetchone() is not None


def _refresh_tokens_columns(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'refresh_tokens'
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _refresh_tokens_indexes(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'refresh_tokens'
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _refresh_tokens_unique_constraints(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'public.refresh_tokens'::regclass
              AND contype = 'u'
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _run_alembic_cli(database_urls: DatabaseUrls, *args: str) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": database_urls.async_url,
        "DATABASE_SYNC_URL": database_urls.sync_url,
    }
    subprocess.run(  # noqa: S603 - CLI args are fixed test literals for Alembic verification.
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )


def test_alembic_upgrade_and_downgrade(
    migration_database_urls: DatabaseUrls,
    alembic_config_factory: Callable[[str], Config],
) -> None:
    config: Config = alembic_config_factory(migration_database_urls.sync_url)

    command.upgrade(config, "head")
    assert _table_names(migration_database_urls.psycopg_url) == {
        "files",
        "refresh_tokens",
        "scan_files",
        "scan_findings",
        "scans",
        "uploads",
        "users",
    }
    assert _has_citext_extension(migration_database_urls.psycopg_url) is True

    command.downgrade(config, "base")
    assert _table_names(migration_database_urls.psycopg_url) == set()
    assert _has_citext_extension(migration_database_urls.psycopg_url) is True


def test_alembic_refresh_token_family_id_round_trip(
    migration_database_urls: DatabaseUrls,
) -> None:
    _run_alembic_cli(migration_database_urls, "upgrade", "head")
    assert "family_id" in _refresh_tokens_columns(migration_database_urls.psycopg_url)
    assert "ix_refresh_tokens_user_id_family_id" in _refresh_tokens_indexes(
        migration_database_urls.psycopg_url
    )
    assert "uq_refresh_tokens_token_hash" in _refresh_tokens_unique_constraints(
        migration_database_urls.psycopg_url
    )
    assert "ix_refresh_tokens_token_hash" not in _refresh_tokens_indexes(
        migration_database_urls.psycopg_url
    )

    # Round-trip the family-id migration once, then re-upgrade so subsequent
    # tests in this file see HEAD applied. Later migrations are layered on top,
    # so we have to step their downgrades first.
    _run_alembic_cli(migration_database_urls, "downgrade", "-1")  # drop scans+scan_files+findings
    _run_alembic_cli(migration_database_urls, "downgrade", "-1")  # drop files
    _run_alembic_cli(migration_database_urls, "downgrade", "-1")  # drop uploads
    _run_alembic_cli(migration_database_urls, "downgrade", "-1")  # drop family_id
    assert "family_id" not in _refresh_tokens_columns(migration_database_urls.psycopg_url)
    assert "ix_refresh_tokens_user_id_family_id" not in _refresh_tokens_indexes(
        migration_database_urls.psycopg_url
    )
    assert "uq_refresh_tokens_token_hash" not in _refresh_tokens_unique_constraints(
        migration_database_urls.psycopg_url
    )
    assert "ix_refresh_tokens_token_hash" in _refresh_tokens_indexes(
        migration_database_urls.psycopg_url
    )

    _run_alembic_cli(migration_database_urls, "upgrade", "head")
    assert "family_id" in _refresh_tokens_columns(migration_database_urls.psycopg_url)
    assert "ix_refresh_tokens_user_id_family_id" in _refresh_tokens_indexes(
        migration_database_urls.psycopg_url
    )
    assert "uq_refresh_tokens_token_hash" in _refresh_tokens_unique_constraints(
        migration_database_urls.psycopg_url
    )
    assert "ix_refresh_tokens_token_hash" not in _refresh_tokens_indexes(
        migration_database_urls.psycopg_url
    )


def test_alembic_uploads_round_trip(migration_database_urls: DatabaseUrls) -> None:
    _run_alembic_cli(migration_database_urls, "upgrade", "head")
    assert "uploads" in _table_names(migration_database_urls.psycopg_url)
    assert "ix_uploads_user_id_created_at" in _uploads_indexes(migration_database_urls.psycopg_url)

    # Step past later migrations first so the uploads downgrade can run.
    _run_alembic_cli(migration_database_urls, "downgrade", "-1")  # drop scans+scan_files+findings
    _run_alembic_cli(migration_database_urls, "downgrade", "-1")  # drop files
    _run_alembic_cli(migration_database_urls, "downgrade", "-1")  # drop uploads
    assert "uploads" not in _table_names(migration_database_urls.psycopg_url)

    _run_alembic_cli(migration_database_urls, "upgrade", "head")
    assert "uploads" in _table_names(migration_database_urls.psycopg_url)
    assert "ix_uploads_user_id_created_at" in _uploads_indexes(migration_database_urls.psycopg_url)


def test_alembic_files_round_trip(migration_database_urls: DatabaseUrls) -> None:
    _run_alembic_cli(migration_database_urls, "upgrade", "head")
    assert "files" in _table_names(migration_database_urls.psycopg_url)
    indexes = _files_indexes(migration_database_urls.psycopg_url)
    assert "ix_files_upload_id_path" in indexes
    assert "ix_files_upload_id_parent_path" in indexes
    assert "uq_files_upload_id_path" in _files_unique_constraints(
        migration_database_urls.psycopg_url
    )

    # Step past the scans migration first so the files downgrade can run.
    _run_alembic_cli(migration_database_urls, "downgrade", "-1")  # drop scans+scan_files+findings
    _run_alembic_cli(migration_database_urls, "downgrade", "-1")  # drop files
    assert "files" not in _table_names(migration_database_urls.psycopg_url)

    _run_alembic_cli(migration_database_urls, "upgrade", "head")
    assert "files" in _table_names(migration_database_urls.psycopg_url)
    indexes = _files_indexes(migration_database_urls.psycopg_url)
    assert "ix_files_upload_id_path" in indexes
    assert "ix_files_upload_id_parent_path" in indexes
    assert "uq_files_upload_id_path" in _files_unique_constraints(
        migration_database_urls.psycopg_url
    )


def test_alembic_scans_round_trip(migration_database_urls: DatabaseUrls) -> None:
    _run_alembic_cli(migration_database_urls, "upgrade", "head")
    tables = _table_names(migration_database_urls.psycopg_url)
    assert {"scans", "scan_files", "scan_findings"} <= tables

    scans_indexes = _scans_indexes(migration_database_urls.psycopg_url)
    assert "ix_scans_user_id_created_at" in scans_indexes
    assert "ix_scans_upload_id" in scans_indexes
    assert "ix_scans_status" in scans_indexes

    scan_files_indexes = _scan_files_indexes(migration_database_urls.psycopg_url)
    assert "ix_scan_files_scan_id_status" in scan_files_indexes
    assert "uq_scan_files_scan_id_file_id" in _scan_files_unique_constraints(
        migration_database_urls.psycopg_url
    )

    scan_findings_indexes = _scan_findings_indexes(migration_database_urls.psycopg_url)
    assert "ix_scan_findings_scan_id_severity" in scan_findings_indexes
    assert "ix_scan_findings_scan_id_scan_type" in scan_findings_indexes
    assert "ix_scan_findings_scan_id_file_id" in scan_findings_indexes

    # Scans / scan_files / scan_findings live in one migration — one step is enough.
    _run_alembic_cli(migration_database_urls, "downgrade", "-1")
    tables = _table_names(migration_database_urls.psycopg_url)
    assert "scans" not in tables
    assert "scan_files" not in tables
    assert "scan_findings" not in tables

    _run_alembic_cli(migration_database_urls, "upgrade", "head")
    tables = _table_names(migration_database_urls.psycopg_url)
    assert {"scans", "scan_files", "scan_findings"} <= tables
    scans_indexes = _scans_indexes(migration_database_urls.psycopg_url)
    assert "ix_scans_user_id_created_at" in scans_indexes
    assert "ix_scans_upload_id" in scans_indexes
    assert "ix_scans_status" in scans_indexes
    scan_files_indexes = _scan_files_indexes(migration_database_urls.psycopg_url)
    assert "ix_scan_files_scan_id_status" in scan_files_indexes
    assert "uq_scan_files_scan_id_file_id" in _scan_files_unique_constraints(
        migration_database_urls.psycopg_url
    )
    scan_findings_indexes = _scan_findings_indexes(migration_database_urls.psycopg_url)
    assert "ix_scan_findings_scan_id_severity" in scan_findings_indexes
    assert "ix_scan_findings_scan_id_scan_type" in scan_findings_indexes
    assert "ix_scan_findings_scan_id_file_id" in scan_findings_indexes
