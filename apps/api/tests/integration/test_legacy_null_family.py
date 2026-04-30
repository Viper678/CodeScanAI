from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from conftest import SampleUserFactory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_refresh_token
from app.core.uuid7 import uuid7
from app.models.refresh_token import RefreshToken
from app.services import auth_service

CSRF_HEADERS = {"X-Requested-With": "codescan"}


def _refresh_headers(raw_refresh_token: str) -> dict[str, str]:
    return {
        "X-Requested-With": "codescan",
        "Cookie": f"cs_refresh={raw_refresh_token}",
    }


# Blocked on issue #7 until refresh-token minting stops colliding within the same second.
@pytest.mark.xfail(
    reason="blocked on issue #7: refresh-token same-second collision",
    strict=False,
)
async def test_legacy_null_family_token_refreshes_once_and_logs_legacy_replay(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    sample_user_factory: SampleUserFactory,
) -> None:
    with patch.object(auth_service.logger, "warning") as warning_mock:
        user = await sample_user_factory(email="legacy@example.com")
        legacy_refresh, legacy_hash, legacy_expires_at = create_refresh_token(user.id)
        legacy_row = RefreshToken(
            id=uuid7(),
            user_id=user.id,
            family_id=None,
            token_hash=legacy_hash,
            expires_at=legacy_expires_at,
            user_agent="pytest",
            ip="127.0.0.1",
        )
        db_session.add(legacy_row)
        await db_session.commit()

        first_refresh = await client.post(
            "/api/v1/auth/refresh", headers=_refresh_headers(legacy_refresh)
        )
        assert first_refresh.status_code == 200
        new_refresh = first_refresh.cookies.get("cs_refresh")
        assert new_refresh is not None

        await db_session.refresh(legacy_row)
        assert legacy_row.revoked_at is not None
        assert legacy_row.family_id is None
        rotated_row = await db_session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash != legacy_hash,
                RefreshToken.user_id == user.id,
            )
        )
        assert rotated_row is not None
        assert rotated_row.family_id is not None
        assert rotated_row.revoked_at is None

        replay_response = await client.post(
            "/api/v1/auth/refresh", headers=_refresh_headers(legacy_refresh)
        )
        assert replay_response.status_code == 401
        assert replay_response.json()["error"]["code"] == "unauthorized"

        await db_session.refresh(rotated_row)
        assert rotated_row.revoked_at is None
        assert any(
            call.args == ("refresh_token_replay_detected_legacy",)
            and call.kwargs
            == {
                "extra": {
                    "event": "refresh_token_replay_detected_legacy",
                    "user_id": str(user.id),
                    "ip": "127.0.0.1",
                    "user_agent": "python-httpx/0.28.1",
                }
            }
            for call in warning_mock.call_args_list
        )
