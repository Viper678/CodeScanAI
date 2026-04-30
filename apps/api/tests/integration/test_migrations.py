from __future__ import annotations

from collections.abc import Callable

import psycopg
from conftest import DatabaseUrls

from alembic import command
from alembic.config import Config


def _table_names(psycopg_url: str) -> set[str]:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename IN ('users', 'refresh_tokens')
            """,
        )
        return {row[0] for row in cursor.fetchall()}


def _has_citext_extension(psycopg_url: str) -> bool:
    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'citext'")
        return cursor.fetchone() is not None


def test_alembic_upgrade_and_downgrade(
    migration_database_urls: DatabaseUrls,
    alembic_config_factory: Callable[[str], Config],
) -> None:
    config: Config = alembic_config_factory(migration_database_urls.sync_url)

    command.upgrade(config, "head")
    assert _table_names(migration_database_urls.psycopg_url) == {"refresh_tokens", "users"}
    assert _has_citext_extension(migration_database_urls.psycopg_url) is True

    command.downgrade(config, "base")
    assert _table_names(migration_database_urls.psycopg_url) == set()
    assert _has_citext_extension(migration_database_urls.psycopg_url) is True
