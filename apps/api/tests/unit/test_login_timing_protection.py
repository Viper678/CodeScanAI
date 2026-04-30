from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidCredentials
from app.repositories.user_repo import UserRepo
from app.services import auth_service
from app.services.auth_service import AuthService


async def test_unknown_email_still_runs_bcrypt_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression guard for docs/SECURITY.md §2:
    # auth response time must not reveal account existence.
    calls = 0

    async def get_by_email(_: UserRepo, email: str) -> None:
        assert email == "missing@example.com"

    def verify_password(_: str, hashed: str) -> bool:
        nonlocal calls
        calls += 1
        assert hashed == auth_service.DUMMY_BCRYPT_HASH
        return False

    monkeypatch.setattr(UserRepo, "get_by_email", get_by_email)
    monkeypatch.setattr(auth_service, "verify_password", verify_password)

    service = AuthService(cast(AsyncSession, object()))
    with pytest.raises(InvalidCredentials):
        await service.login(
            email="missing@example.com",
            password="correct-horse",  # noqa: S106 - test credential fixture
            user_agent=None,
            ip=None,
        )

    assert calls == 1
