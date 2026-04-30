from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import InvalidToken

BCRYPT_COST = 12
JWT_ALGORITHM = "HS256"


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    issued_at: datetime
    expires_at: datetime


def _prepare_password(plaintext: str) -> bytes:
    pw = plaintext.encode("utf-8")
    if len(pw) > 72:
        pw = hashlib.sha256(pw).digest()
    return pw


def hash_password(plaintext: str) -> str:
    prepared = _prepare_password(plaintext)
    return bcrypt.hashpw(prepared, bcrypt.gensalt(rounds=BCRYPT_COST)).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    prepared = _prepare_password(plaintext)
    return bcrypt.checkpw(prepared, hashed.encode("utf-8"))


def create_access_token(user_id: UUID) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.jwt_access_ttl_min)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": expires_at,
            "type": "access",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )


def create_refresh_token(user_id: UUID) -> tuple[str, str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=settings.jwt_refresh_ttl_days)
    raw_jwt = jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": expires_at,
            "type": "refresh",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    token_hash = hashlib.sha256(raw_jwt.encode("utf-8")).hexdigest()
    return raw_jwt, token_hash, expires_at


def decode_access_token(token: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
        )
        if payload.get("type") != "access":
            raise InvalidToken
        subject = payload.get("sub")
        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        if not isinstance(subject, str) or issued_at is None or expires_at is None:
            raise InvalidToken
        return AccessTokenClaims(
            user_id=UUID(subject),
            issued_at=datetime.fromtimestamp(float(issued_at), tz=UTC),
            expires_at=datetime.fromtimestamp(float(expires_at), tz=UTC),
        )
    except (ValueError, jwt.InvalidTokenError) as exc:
        raise InvalidToken from exc
