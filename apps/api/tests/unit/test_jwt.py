from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.exceptions import InvalidToken
from app.core.security import (
    JWT_ALGORITHM,
    create_access_token,
    create_refresh_token,
    decode_access_token,
)
from app.core.uuid7 import uuid7


def test_access_token_create_and_decode_roundtrip() -> None:
    user_id = uuid7()

    token = create_access_token(user_id)
    claims = decode_access_token(token)

    assert claims.user_id == user_id
    assert claims.expires_at > datetime.now(UTC)


def test_expired_access_token_is_rejected() -> None:
    user_id = uuid7()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "iat": now - timedelta(minutes=30),
            "exp": now - timedelta(minutes=1),
            "type": "access",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(InvalidToken):
        decode_access_token(token)


def test_refresh_token_hash_is_sha256_of_raw_jwt() -> None:
    user_id = uuid7()

    raw_jwt, token_hash, expires_at = create_refresh_token(user_id)

    assert token_hash == hashlib.sha256(raw_jwt.encode("utf-8")).hexdigest()
    assert expires_at > datetime.now(UTC)
