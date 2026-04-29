from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from alembic import command
from alembic.config import Config
from app.core.config import settings
from app.models.user import User

API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = API_ROOT / "alembic.ini"


@dataclass(frozen=True)
class DatabaseUrls:
    async_url: str
    sync_url: str
    psycopg_url: str
    database_name: str


SampleUserFactory = Callable[..., Awaitable[User]]


def _render_url(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def _host_test_url(url: URL) -> URL:
    """Map compose service hostnames to localhost for host-run tests."""

    if url.host == "postgres":
        return url.set(host="localhost")
    return url


def _build_database_urls(database_name: str) -> DatabaseUrls:
    async_url = _host_test_url(make_url(settings.database_url)).set(database=database_name)
    sync_url = _host_test_url(make_url(settings.database_sync_url)).set(database=database_name)
    psycopg_url = _host_test_url(make_url(settings.database_sync_url)).set(
        drivername="postgresql",
        database=database_name,
    )
    return DatabaseUrls(
        async_url=_render_url(async_url),
        sync_url=_render_url(sync_url),
        psycopg_url=_render_url(psycopg_url),
        database_name=database_name,
    )


def _admin_sync_url() -> str:
    return _render_url(
        _host_test_url(make_url(settings.database_sync_url)).set(
            drivername="postgresql",
            database="postgres",
        ),
    )


def _drop_database(database_name: str) -> None:
    with (
        psycopg.connect(_admin_sync_url(), autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (database_name,),
        )
        cursor.execute(
            sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)),
        )


def _create_database(database_name: str) -> None:
    with (
        psycopg.connect(_admin_sync_url(), autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)),
        )


def _reset_database(database_name: str) -> None:
    _drop_database(database_name)
    _create_database(database_name)


def _alembic_config(sync_url: str) -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("sqlalchemy.url", sync_url)
    return config


def _run_migrations(sync_url: str, revision: str) -> None:
    config = _alembic_config(sync_url)
    if revision == "head":
        command.upgrade(config, revision)
    else:
        command.downgrade(config, revision)


@pytest.fixture(scope="session")
def test_database_urls() -> DatabaseUrls:
    base_database_name = make_url(settings.database_sync_url).database
    assert base_database_name is not None
    return _build_database_urls(f"{base_database_name}_test")


@pytest.fixture
def migration_database_urls() -> Generator[DatabaseUrls, None, None]:
    base_database_name = make_url(settings.database_sync_url).database
    assert base_database_name is not None
    database_urls = _build_database_urls(f"{base_database_name}_migration_{uuid4().hex}")
    _create_database(database_urls.database_name)
    try:
        yield database_urls
    finally:
        _drop_database(database_urls.database_name)


@pytest.fixture
def alembic_config_factory() -> Callable[[str], Config]:
    return _alembic_config


@pytest.fixture(scope="session")
def engine(test_database_urls: DatabaseUrls) -> Generator[AsyncEngine, None, None]:
    _reset_database(test_database_urls.database_name)
    _run_migrations(test_database_urls.sync_url, "head")

    async_engine = create_async_engine(test_database_urls.async_url, pool_pre_ping=True)
    try:
        yield async_engine
    finally:
        asyncio.run(async_engine.dispose())
        _drop_database(test_database_urls.database_name)


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def sample_user_factory(db_session: AsyncSession) -> SampleUserFactory:
    async def factory(**overrides: object) -> User:
        user = User(
            email=str(overrides.pop("email", f"user-{uuid4().hex[:8]}@example.com")),
            password_hash=str(overrides.pop("password_hash", "not-a-real-hash")),
            is_active=bool(overrides.pop("is_active", True)),
            **overrides,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return factory
