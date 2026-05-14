import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    # worker can read/write the same artifacts. Only consulted when
    # ``storage_backend == 'local'``.
    data_dir: Path = Path("/data")
    # Backend selector — see docs/GCP_MIGRATION.md §D2 for the resolved
    # decision. ``local`` keeps the existing filesystem behavior (default;
    # dev/CI/docker-compose). ``gcs`` routes the same operations through
    # Google Cloud Storage, requiring ``storage_bucket`` to be set.
    storage_backend: Literal["local", "gcs"] = "local"
    # GCS bucket name when ``storage_backend == 'gcs'``. Required in that
    # mode (validated below); ignored when local.
    storage_bucket: str | None = None
    # Limits sourced from docs/FILE_HANDLING.md §"Upload limits".
    max_upload_size_mb: int = 100
    max_loose_files: int = 50
    max_loose_file_size_mb: int = 50

    # ---- Redis (app-level) ----
    # Used for the rate limiter (T5.1). Post-M3 the rate limiter, the Celery
    # broker and the Celery result backend all share db 0 — Celery scopes its
    # keys via ``global_keyprefix`` (see ``worker.celery_app``) so they cannot
    # collide with rate-limit keys (which live under ``rl:``). The single-db
    # shape matches the prod target (legacy Memorystore for Redis, Standard
    # Tier, 5 GB — see docs/GCP_MIGRATION.md §D1).
    redis_url: str = "redis://redis:6379/0"

    # ---- Celery ----
    # The API only enqueues; consumption lives in codescan-backend/worker. Default mirrors
    # docker-compose so local dev "just works". Shares db 0 with the rate
    # limiter and the result backend (see redis_url comment above).
    celery_broker_url: str = "redis://redis:6379/0"

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
    #
    # ``NoDecode`` defers env parsing to the ``split_cors_origins`` validator
    # below. Without it, pydantic-settings JSON-decodes ``list[str]`` env
    # values BEFORE validators run, so a plain string like
    # ``CORS_ALLOW_ORIGINS=https://app.example.com`` raises ``SettingsError``
    # at startup — which contradicts the validator's documented intent.
    cors_allow_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:3001",
    ]

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        """Accept either a comma-separated string or a JSON-encoded list.

        Comma form is the documented prod operator interface
        (``CORS_ALLOW_ORIGINS=https://a,https://b``). JSON form
        (``["https://a","https://b"]``) is also accepted because the
        e2e compose overlay uses it; either works.
        """
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(decoded, list):
                    return decoded
        return [item.strip() for item in value.split(",") if item.strip()]

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

    # ---- Logging / observability (T5.4) ---------------------------------------
    # Root log level. Accepts the standard Python names (debug/info/warning/...)
    # case-insensitive. Anything unrecognized falls back to INFO at configure
    # time rather than crashing — operators sometimes typo this in env files.
    log_level: str = "info"

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            msg = "jwt_secret must be at least 32 bytes"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _validate_storage_backend(self) -> "Settings":
        # Fail fast at startup so a misconfigured prod deploy doesn't get
        # 500s on the first upload. Mirrored in the worker config.
        if self.storage_backend == "gcs" and not self.storage_bucket:
            msg = "storage_bucket must be set when storage_backend='gcs'"
            raise ValueError(msg)
        return self


settings = Settings()  # type: ignore[call-arg]  # jwt_secret is required from environment
