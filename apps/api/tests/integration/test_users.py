from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def test_create_and_lookup_user_case_insensitively(db_session: AsyncSession) -> None:
    user = User(
        email="Dev@Example.com",
        password_hash="fixture-password-hash",  # noqa: S106 - integration test fixture value
    )
    db_session.add(user)

    await db_session.commit()
    await db_session.refresh(user)

    assert user.id.version == 7
    assert user.created_at is not None
    assert user.updated_at is not None

    result = await db_session.execute(select(User).where(User.email == "dev@example.com"))
    loaded_user = result.scalar_one()

    assert loaded_user.id == user.id
    assert loaded_user.email == "Dev@Example.com"
