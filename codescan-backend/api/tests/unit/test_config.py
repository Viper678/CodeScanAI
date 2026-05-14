from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    """Build a ``Settings`` with ``_env_file=None`` so any local ``.env``
    file doesn't bleed into the test, and a valid ``jwt_secret`` so the
    instance constructs without complaint.

    ``_env_file`` is a pydantic-settings runtime kwarg not visible to
    ``BaseSettings.__init__``'s declared signature; the ignore is
    deliberate.
    """

    return Settings(
        jwt_secret=SecretStr("x" * 32),
        _env_file=None,  # type: ignore[call-arg]
        **overrides,  # type: ignore[arg-type]
    )


def test_jwt_secret_shorter_than_32_bytes_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_secret=SecretStr("x" * 31))


def test_jwt_secret_exactly_32_bytes_is_accepted() -> None:
    settings = Settings(jwt_secret=SecretStr("x" * 32))

    assert settings.jwt_secret.get_secret_value() == "x" * 32


def test_cors_allow_origins_default_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)

    settings = _settings()

    assert settings.cors_allow_origins == [
        "http://localhost:3000",
        "http://localhost:3001",
    ]


def test_cors_allow_origins_comma_separated_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plain comma-separated string is the documented prod operator
    form. Pydantic-settings would otherwise JSON-decode ``list[str]``
    env values first and raise ``SettingsError`` on a non-JSON string —
    the ``NoDecode`` annotation on the field defers parsing to the
    validator so this works."""

    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        "https://a.example.com,https://b.example.com",
    )

    settings = _settings()

    assert settings.cors_allow_origins == [
        "https://a.example.com",
        "https://b.example.com",
    ]


def test_cors_allow_origins_single_value_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://only.example.com")

    settings = _settings()

    assert settings.cors_allow_origins == ["https://only.example.com"]


def test_cors_allow_origins_json_list_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The e2e compose overlay uses JSON-list form so the validator
    accepts that too — back-compat for anyone already using it."""

    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        '["https://a.example.com","https://b.example.com"]',
    )

    settings = _settings()

    assert settings.cors_allow_origins == [
        "https://a.example.com",
        "https://b.example.com",
    ]


def test_cors_allow_origins_strips_whitespace_around_comma_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        "  https://a.example.com  ,\thttps://b.example.com\t",
    )

    settings = _settings()

    assert settings.cors_allow_origins == [
        "https://a.example.com",
        "https://b.example.com",
    ]
