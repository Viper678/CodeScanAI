from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def test_jwt_secret_shorter_than_32_bytes_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_secret=SecretStr("x" * 31))


def test_jwt_secret_exactly_32_bytes_is_accepted() -> None:
    settings = Settings(jwt_secret=SecretStr("x" * 32))

    assert settings.jwt_secret.get_secret_value() == "x" * 32
