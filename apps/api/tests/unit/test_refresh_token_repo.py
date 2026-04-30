from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from conftest import SampleUserFactory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.uuid7 import uuid7
from app.models.refresh_token import RefreshToken
from app.repositories.refresh_token_repo import RefreshTokenRepo


def _repo_token_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


async def test_create_sets_family_id_when_provided(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user = await sample_user_factory()
    family_id = uuid7()

    token = await RefreshTokenRepo(db_session).create(
        user_id=user.id,
        family_id=family_id,
        token_hash=_repo_token_hash("hash-1"),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        user_agent="pytest",
        ip="127.0.0.1",
    )

    assert token.family_id == family_id


async def test_get_by_hash_round_trips(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user = await sample_user_factory()
    repo = RefreshTokenRepo(db_session)
    token_hash = _repo_token_hash("hash-lookup")
    created = await repo.create(
        user_id=user.id,
        family_id=uuid7(),
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        user_agent=None,
        ip=None,
    )

    loaded = await repo.get_by_hash(token_hash)

    assert loaded is not None
    assert loaded.id == created.id


async def test_revoke_is_idempotent(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user = await sample_user_factory()
    repo = RefreshTokenRepo(db_session)
    created = await repo.create(
        user_id=user.id,
        family_id=uuid7(),
        token_hash=_repo_token_hash("hash-revoke"),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        user_agent=None,
        ip=None,
    )

    await repo.revoke(created.id)
    await db_session.flush()
    first_revoked_at = await db_session.scalar(
        select(RefreshToken.revoked_at).where(RefreshToken.id == created.id)
    )
    assert first_revoked_at is not None

    await repo.revoke(created.id)
    await db_session.flush()
    second_revoked_at = await db_session.scalar(
        select(RefreshToken.revoked_at).where(RefreshToken.id == created.id)
    )
    assert second_revoked_at == first_revoked_at


async def test_revoke_family_revokes_matching_tokens_and_filters_by_user(
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    user = await sample_user_factory()
    other_user = await sample_user_factory()
    family_id = uuid7()
    other_family_id = uuid7()
    repo = RefreshTokenRepo(db_session)
    expires_at = datetime.now(UTC) + timedelta(days=1)

    first = await repo.create(
        user_id=user.id,
        family_id=family_id,
        token_hash=_repo_token_hash("hash-family-1"),
        expires_at=expires_at,
        user_agent=None,
        ip=None,
    )
    second = await repo.create(
        user_id=user.id,
        family_id=family_id,
        token_hash=_repo_token_hash("hash-family-2"),
        expires_at=expires_at,
        user_agent=None,
        ip=None,
    )
    already_revoked = await repo.create(
        user_id=user.id,
        family_id=family_id,
        token_hash=_repo_token_hash("hash-family-3"),
        expires_at=expires_at,
        user_agent=None,
        ip=None,
    )
    other_user_token = await repo.create(
        user_id=other_user.id,
        family_id=family_id,
        token_hash=_repo_token_hash("hash-family-4"),
        expires_at=expires_at,
        user_agent=None,
        ip=None,
    )
    other_family = await repo.create(
        user_id=user.id,
        family_id=other_family_id,
        token_hash=_repo_token_hash("hash-family-5"),
        expires_at=expires_at,
        user_agent=None,
        ip=None,
    )
    await repo.revoke(already_revoked.id)

    revoked_count = await repo.revoke_family(user.id, family_id)
    await db_session.flush()

    assert revoked_count == 2
    refreshed = {
        token.id: token
        for token in (
            await db_session.execute(
                select(RefreshToken).where(
                    RefreshToken.id.in_(
                        [
                            first.id,
                            second.id,
                            already_revoked.id,
                            other_user_token.id,
                            other_family.id,
                        ]
                    )
                )
            )
        )
        .scalars()
        .all()
    }
    assert refreshed[first.id].revoked_at is not None
    assert refreshed[second.id].revoked_at is not None
    assert refreshed[already_revoked.id].revoked_at is not None
    assert refreshed[other_user_token.id].revoked_at is None
    assert refreshed[other_family.id].revoked_at is None
