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
              AND tablename IN ('users', 'refresh_tokens', 'uploads')
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
        "refresh_tokens",
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
    # tests in this file see HEAD applied. The uploads migration is layered on
    # top, so we have to step its downgrade first.
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

    _run_alembic_cli(migration_database_urls, "downgrade", "-1")
    assert "uploads" not in _table_names(migration_database_urls.psycopg_url)

    _run_alembic_cli(migration_database_urls, "upgrade", "head")
    assert "uploads" in _table_names(migration_database_urls.psycopg_url)
    assert "ix_uploads_user_id_created_at" in _uploads_indexes(migration_database_urls.psycopg_url)
