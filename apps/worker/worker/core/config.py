"""Worker process settings.

Loaded from environment variables. Mirrors compose defaults so local
``celery -A worker.celery_app worker`` "just works" without an explicit env
file. Limits are sourced from docs/FILE_HANDLING.md §"Upload limits".
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    return None


class Settings(BaseSettings):
    """Worker settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Sync URL — Celery tasks are sync.
    database_sync_url: str = (
        "postgresql+psycopg://codescan:codescan-dev-only-change-me@postgres:5432/codescan"
    )

    # Storage root shared with the api service via a docker volume.
    data_dir: Path = Path("/data")

    # Celery
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # File-handling caps from docs/FILE_HANDLING.md §"Upload limits".
    max_uncompressed_total_mb: int = 500
    max_files_in_archive: int = 20_000
    max_dirs_in_archive: int = 5_000
    max_entry_uncompressed_mb: int = 50  # single zip entry
    max_scan_file_size_mb: int = 1  # excluded if larger
    max_nesting_depth: int = 20
    # Compression-ratio cutoff for the zip-bomb heuristic (uncompressed/compressed).
    max_compression_ratio: int = 100

    # ---- LLM ----
    # Required at runtime to instantiate the default Gemma transport. ``None``-able
    # so unit tests can construct ``GemmaClient(api_key="fake", transport=fake)``
    # without touching the environment.
    google_ai_api_key: SecretStr | None = None
    gemma_model: str = "gemma-4-31b-it"
    prompt_version: str = "v1"


settings = Settings()
