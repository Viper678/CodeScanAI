from __future__ import annotations

import hashlib
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
async def test_refresh_replay_revokes_family_and_logs_warning(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    with patch.object(auth_service.logger, "warning") as warning_mock:
        register_response = await client.post(
            "/api/v1/auth/register",
            json={"email": "replay@example.com", "password": "correct-horse"},
        )
        refresh1 = register_response.cookies.get("cs_refresh")
        assert refresh1 is not None
        refresh1_hash = hashlib.sha256(refresh1.encode("utf-8")).hexdigest()
        refresh1_row = await db_session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == refresh1_hash)
        )
        assert refresh1_row is not None
        family_id = refresh1_row.family_id
        assert family_id is not None

        refresh_response = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
        assert refresh_response.status_code == 200
        refresh2 = refresh_response.cookies.get("cs_refresh")
        assert refresh2 is not None
        refresh2_hash = hashlib.sha256(refresh2.encode("utf-8")).hexdigest()

        await db_session.refresh(refresh1_row)
        assert refresh1_row.revoked_at is not None
        refresh2_row = await db_session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == refresh2_hash)
        )
        assert refresh2_row is not None
        assert refresh2_row.family_id == family_id
        assert refresh2_row.revoked_at is None

        replay_response = await client.post(
            "/api/v1/auth/refresh",
            headers=_refresh_headers(refresh1),
        )
        assert replay_response.status_code == 401
        assert replay_response.json()["error"]["code"] == "unauthorized"

        await db_session.refresh(refresh2_row)
        assert refresh2_row.revoked_at is not None

        family_dead_response = await client.post(
            "/api/v1/auth/refresh",
            headers=_refresh_headers(refresh2),
        )
        assert family_dead_response.status_code == 401
        assert family_dead_response.json()["error"]["code"] == "unauthorized"
        assert any(
            call.args == ("refresh_token_replay_detected",)
            and call.kwargs
            == {
                "extra": {
                    "event": "refresh_token_replay_detected",
                    "user_id": str(refresh1_row.user_id),
                    "family_id": str(family_id),
                    "tokens_revoked": 1,
                    "ip": "127.0.0.1",
                    "user_agent": "python-httpx/0.28.1",
                }
            }
            for call in warning_mock.call_args_list
        )
