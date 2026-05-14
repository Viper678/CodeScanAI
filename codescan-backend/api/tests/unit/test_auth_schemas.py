from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginRequest, RegisterRequest


@pytest.mark.parametrize("schema", [RegisterRequest, LoginRequest])
def test_auth_request_rejects_short_password(schema: type[RegisterRequest | LoginRequest]) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate({"email": "user@example.com", "password": "short"})


@pytest.mark.parametrize("schema", [RegisterRequest, LoginRequest])
def test_auth_request_rejects_invalid_email(schema: type[RegisterRequest | LoginRequest]) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate({"email": "not-an-email", "password": "correct-horse"})


@pytest.mark.parametrize("schema", [RegisterRequest, LoginRequest])
def test_auth_request_rejects_extra_fields(schema: type[RegisterRequest | LoginRequest]) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(
            {"email": "user@example.com", "password": "correct-horse", "role": "admin"}
        )
