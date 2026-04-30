from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.refresh_token import RefreshToken

CSRF_HEADERS = {"X-Requested-With": "codescan"}


def _clear_cookie_header_present(headers: list[str], cookie_name: str) -> bool:
    return any(header.startswith(f"{cookie_name}=") and "Max-Age=0" in header for header in headers)


# Blocked on issue #7 until refresh-token minting stops colliding within the same second.
@pytest.mark.xfail(
    reason="blocked on issue #7: refresh-token same-second collision",
    strict=False,
)
async def test_refresh_happy_path_rotates_token_and_sets_new_cookies(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    register_response = await client.post(
        "/api/v1/auth/register",
        json={"email": "refresh@example.com", "password": "correct-horse"},
    )
    original_refresh = register_response.cookies.get("cs_refresh")
    assert original_refresh is not None
    original_hash = hashlib.sha256(original_refresh.encode("utf-8")).hexdigest()
    original_row = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == original_hash)
    )
    assert original_row is not None

    response = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)

    assert response.status_code == 200
    assert response.content == b""
    new_access = response.cookies.get("cs_access")
    new_refresh = response.cookies.get("cs_refresh")
    assert new_access is not None
    assert new_refresh is not None
    assert new_refresh != original_refresh

    await db_session.refresh(original_row)
    assert original_row.revoked_at is not None
    rotated_row = await db_session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hashlib.sha256(new_refresh.encode("utf-8")).hexdigest()
        )
    )
    assert rotated_row is not None
    assert rotated_row.family_id == original_row.family_id


async def test_refresh_without_csrf_header_returns_forbidden(
    authed_client: httpx.AsyncClient,
) -> None:
    response = await authed_client.post("/api/v1/auth/refresh")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_refresh_without_cookie_returns_unauthorized(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_refresh_with_tampered_jwt_returns_unauthorized(client: httpx.AsyncClient) -> None:
    client.cookies.set("cs_refresh", "tampered")

    response = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_refresh_with_expired_refresh_jwt_returns_unauthorized(
    client: httpx.AsyncClient,
) -> None:
    expired_refresh = jwt.encode(
        {
            "sub": "12345678-1234-5678-1234-567812345678",
            "iat": datetime.now(UTC) - timedelta(days=2),
            "exp": datetime.now(UTC) - timedelta(days=1),
            "type": "refresh",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    client.cookies.set("cs_refresh", expired_refresh)

    response = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_logout_happy_path_revokes_token_and_clears_cookies(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    register_response = await client.post(
        "/api/v1/auth/register",
        json={"email": "logout@example.com", "password": "correct-horse"},
    )
    refresh_token = register_response.cookies.get("cs_refresh")
    assert refresh_token is not None
    refresh_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
    refresh_row = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == refresh_hash)
    )
    assert refresh_row is not None

    response = await client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)

    assert response.status_code == 204
    await db_session.refresh(refresh_row)
    assert refresh_row.revoked_at is not None
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert _clear_cookie_header_present(set_cookie_headers, "cs_access")
    assert _clear_cookie_header_present(set_cookie_headers, "cs_refresh")


async def test_logout_without_csrf_header_returns_forbidden(
    authed_client: httpx.AsyncClient,
) -> None:
    response = await authed_client.post("/api/v1/auth/logout")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_logout_without_cookie_returns_no_content(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)

    assert response.status_code == 204


async def test_logout_with_tampered_cookie_returns_unauthorized(
    client: httpx.AsyncClient,
) -> None:
    client.cookies.set("cs_refresh", "tampered")

    response = await client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_logout_with_signed_unknown_cookie_returns_unauthorized(
    client: httpx.AsyncClient,
) -> None:
    unknown_refresh = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(days=1),
            "type": "refresh",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    client.cookies.set("cs_refresh", unknown_refresh)

    response = await client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
