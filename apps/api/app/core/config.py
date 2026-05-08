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

    # ---- Storage ----
    # Default mirrors docker-compose's mounted /data volume so the API and
    # worker can read/write the same artifacts.
    data_dir: Path = Path("/data")
    # Limits sourced from docs/FILE_HANDLING.md §"Upload limits".
    max_upload_size_mb: int = 100
    max_loose_files: int = 50
    max_loose_file_size_mb: int = 50

    # ---- Redis (app-level) ----
    # Used for the rate limiter (T5.1). Db 0 is reserved for the API; Celery
    # owns 1 (broker) and 2 (result backend). Default mirrors docker-compose.
    redis_url: str = "redis://redis:6379/0"

    # ---- Celery ----
    # The API only enqueues; consumption lives in apps/worker. Default mirrors
    # docker-compose so local dev "just works".
    celery_broker_url: str = "redis://redis:6379/1"

    # ---- Rate limits (T5.1, sourced from docs/API.md §"Rate limits") ----
    # Sliding-window counts are evaluated lazily per request, so changes to
    # these via env hot-reload between requests, without re-registering routes.
    rate_limit_login_per_minute: int = 5
    rate_limit_register_per_minute: int = 5
    rate_limit_upload_per_hour: int = 10
    rate_limit_scan_per_hour: int = 30
    # Optional namespace prefix on every rate-limit key — empty in prod, set to
    # a per-test UUID in the test suite to isolate concurrent test runs that
    # share the same Redis db. Keeping it on Settings (rather than baked into
    # the test fixture) means no special-casing in the limiter itself.
    rate_limit_key_namespace: str = ""

    # ---- CORS ----
    # Browser → API is cross-origin; the frontend uses cookie auth so wildcard
    # origins are not allowed. Defaults cover both the docker-compose web
    # (3000) and a local `pnpm dev` instance bumped to 3001 by Next when 3000
    # is busy. Override via CORS_ALLOW_ORIGINS env (comma-separated) for prod.
    cors_allow_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
    ]

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    # ---- Scans ----
    # Cap on file_ids per POST /scans payload. Sourced from docs/API.md §Scans.
    max_files_per_scan: int = 500

    # ---- File viewer (T4.3) ----
    # Maximum size of a file we will stream back as text via
    # ``GET /uploads/{id}/files/{file_id}/content``. Anything larger gets a
    # 413 — the viewer is read-only source-code preview, not a download
    # service. 2 MiB comfortably covers source files; the worker already
    # excludes anything > 1 MiB from scans (docs/FILE_HANDLING.md), so the
    # gap leaves headroom for "I uploaded it loose, let me look at it".
    max_viewable_file_size_mb: int = 2

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            msg = "jwt_secret must be at least 32 bytes"
            raise ValueError(msg)
        return value


settings = Settings()  # type: ignore[call-arg]  # jwt_secret is required from environment
