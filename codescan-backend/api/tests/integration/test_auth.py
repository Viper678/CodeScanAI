from __future__ import annotations

import hashlib
from http.cookies import SimpleCookie
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.models.user import User


def _set_cookie_headers(response: httpx.Response) -> list[str]:
    return response.headers.get_list("set-cookie")


def _assert_auth_cookies(response: httpx.Response) -> None:
    headers = _set_cookie_headers(response)
    assert any(header.startswith("cs_access=") for header in headers)
    assert any(header.startswith("cs_refresh=") for header in headers)

    for header in headers:
        if header.startswith(("cs_access=", "cs_refresh=")):
            cookie = SimpleCookie()
            cookie.load(header)
            morsel = next(iter(cookie.values()))
            assert morsel["httponly"]
            assert morsel["samesite"].lower() == "lax"
            assert morsel["path"] == "/"


async def test_register_happy_path_persists_user_and_sets_cookies(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "Dev@Example.com", "password": "correct-horse"},
    )

    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"])
    assert body["email"] == "dev@example.com"
    _assert_auth_cookies(response)

    result = await db_session.execute(select(User).where(User.email == "dev@example.com"))
    user = result.scalar_one()
    assert user.password_hash.startswith("$2b$12$")

    refresh_token = response.cookies.get("cs_refresh")
    assert refresh_token is not None
    refresh_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
    stored_refresh = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == refresh_hash)
    )
    assert stored_refresh is not None
    assert stored_refresh.family_id is not None


async def test_register_duplicate_email_returns_conflict(client: httpx.AsyncClient) -> None:
    payload = {"email": "user@example.com", "password": "correct-horse"}
    first_response = await client.post("/api/v1/auth/register", json=payload)
    response = await client.post("/api/v1/auth/register", json=payload)

    assert first_response.status_code == 201
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_register_weak_password_returns_validation_error(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "short"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_login_happy_path_sets_cookies_and_inserts_refresh_token(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    payload = {"email": "user@example.com", "password": "correct-horse"}
    register_response = await client.post("/api/v1/auth/register", json=payload)
    before_count = await db_session.scalar(select(func.count()).select_from(RefreshToken))

    response = await client.post("/api/v1/auth/login", json=payload)
    after_count = await db_session.scalar(select(func.count()).select_from(RefreshToken))

    assert before_count is not None
    assert after_count is not None
    assert register_response.status_code == 201
    assert response.status_code == 200
    assert response.json()["email"] == "user@example.com"
    _assert_auth_cookies(response)
    assert after_count == before_count + 1

    refresh_token = response.cookies.get("cs_refresh")
    assert refresh_token is not None
    refresh_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
    stored_refresh = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == refresh_hash)
    )
    assert stored_refresh is not None
    assert stored_refresh.family_id is not None


async def test_login_wrong_password_returns_generic_unauthorized(
    client: httpx.AsyncClient,
) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "correct-horse"},
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    message = response.json()["error"]["message"].lower()
    assert "password" not in message
    assert "email" not in message


async def test_login_unknown_email_matches_wrong_password_response(
    client: httpx.AsyncClient,
) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "correct-horse"},
    )
    wrong_password = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )
    unknown_email = await client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
    )

    assert unknown_email.status_code == 401
    assert unknown_email.json() == wrong_password.json()


async def test_me_with_valid_access_cookie_returns_user(authed_client: httpx.AsyncClient) -> None:
    response = await authed_client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["email"].endswith("@example.com")


async def test_me_with_no_cookie_returns_unauthorized(client: httpx.AsyncClient) -> None:
    client.cookies.clear()

    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_me_with_tampered_cookie_returns_unauthorized(client: httpx.AsyncClient) -> None:
    client.cookies.set("cs_access", "tampered")

    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
