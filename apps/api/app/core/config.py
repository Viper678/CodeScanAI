from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    return None


class Settings(BaseSettings):
    """Application settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CodeScan API"
    database_url: str = (
        "postgresql+asyncpg://codescan:codescan-dev-only-change-me@postgres:5432/codescan"
    )
    database_sync_url: str = (
        "postgresql+psycopg://codescan:codescan-dev-only-change-me@postgres:5432/codescan"
    )
    jwt_secret: SecretStr
    jwt_access_ttl_min: int = 15
    jwt_refresh_ttl_days: int = 14
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            msg = "jwt_secret must be at least 32 bytes"
            raise ValueError(msg)
        return value


settings = Settings()  # type: ignore[call-arg]  # jwt_secret is required from environment
