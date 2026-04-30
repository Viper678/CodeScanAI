from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.deps import get_current_user, require_csrf_header
from app.core.exceptions import InvalidToken
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserOut
from app.services.auth_service import AuthCookies, AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _set_auth_cookies(response: Response, cookies: AuthCookies) -> None:
    response.set_cookie(
        "cs_access",
        cookies.access_token,
        expires=cookies.access_expires_at,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    response.set_cookie(
        "cs_refresh",
        cookies.refresh_token,
        expires=cookies.refresh_expires_at,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email)


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        "cs_access",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    response.delete_cookie(
        "cs_refresh",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserOut:
    user, cookies = await AuthService(session).register(
        email=str(payload.email),
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
        ip=_client_ip(request),
    )
    _set_auth_cookies(response, cookies)
    return _user_out(user)


@router.post("/login", response_model=UserOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserOut:
    # TODO(T5.1): rate-limit POST /auth/login at 5/IP/min — see docs/SECURITY.md §2 and docs/API.md §Rate limits  # noqa: E501 - required task TODO text
    user, cookies = await AuthService(session).login(
        email=str(payload.email),
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
        ip=_client_ip(request),
    )
    _set_auth_cookies(response, cookies)
    return _user_out(user)


@router.get("/me", response_model=UserOut)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserOut:
    return _user_out(current_user)


@router.post("/refresh", dependencies=[Depends(require_csrf_header)])
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    raw_refresh_token = request.cookies.get("cs_refresh")
    if raw_refresh_token is None:
        raise InvalidToken

    _, cookies = await AuthService(session).refresh(
        raw_refresh_token=raw_refresh_token,
        user_agent=request.headers.get("user-agent"),
        ip=_client_ip(request),
    )
    _set_auth_cookies(response, cookies)
    response.status_code = status.HTTP_200_OK
    return response


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf_header)],
)
async def logout(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    raw_refresh_token = request.cookies.get("cs_refresh")
    if raw_refresh_token is not None:
        await AuthService(session).logout(raw_refresh_token=raw_refresh_token)

    _clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
