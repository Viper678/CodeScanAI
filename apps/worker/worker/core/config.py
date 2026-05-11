"""Worker process settings.

Loaded from environment variables. Mirrors compose defaults so local
``celery -A worker.celery_app worker`` "just works" without an explicit env
file. Limits are sourced from docs/FILE_HANDLING.md §"Upload limits".
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr, field_validator
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
    # vLLM (or any OpenAI-compatible) endpoint base URL. The default points at
    # the in-cluster service name used by the GKE manifests; override locally
    # via env. Always has a non-empty default so unit tests can construct
    # ``GemmaClient(transport=fake)`` without touching the environment.
    llm_base_url: str = "http://vllm.llm.svc.cluster.local:8000/v1"
    # Optional bearer token. Only set when the vLLM process was launched with
    # ``--api-key`` (i.e. requires auth); otherwise leave unset and the client
    # passes a placeholder that the server ignores.
    llm_api_key: SecretStr | None = None
    gemma_model: str = "gemma-4-31b-it"
    prompt_version: str = "v1"
    # Test-only switch: when true, ``run_scan`` swaps ``_DefaultGemmaTransport``
    # for ``MockGemmaTransport`` so security/bugs scanners produce canned
    # findings without an HTTP call. Used by the Playwright e2e suite (T5.5);
    # never set in production deployments.
    llm_mock_mode: bool = False

    # ---- Logging / observability (T5.4) ---------------------------------------
    log_level: str = "info"

    # ---- Scans ----
    scan_concurrency: int = 4
    # Per-call token budget; sourced from docs/SCAN_RULES.md §"Token budget &
    # chunking". Files whose char/4 estimate exceeds this are skipped pending
    # the chunker follow-up.
    gemma_max_input_tokens: int = 120_000
    # Re-poll scan.status every N completed files to honor cancellation.
    cancel_check_interval_files: int = 4

    # ---- Retention (T5.2) -----------------------------------------------------
    # Daily cleanup beat task purges uploads whose ``created_at`` is older than
    # ``retention_days``. **Disabled by default** — operators opt in by setting
    # ``RETENTION_DAYS=<positive int>`` in the environment. When ``None``, the
    # beat task still ticks daily but no-ops with a single DEBUG log line. Zero
    # and negative values are rejected: ``0`` is "delete everything older than
    # zero days = everything", which is a footgun, not a config.
    retention_days: int | None = None

    @field_validator("retention_days", mode="before")
    @classmethod
    def _coerce_retention_days(cls, value: object) -> object:
        # Pydantic-settings reads env strings; an empty ``RETENTION_DAYS=`` and
        # an unset var both arrive as ``""`` or absent. Treat empty as None so
        # operators can comment-out / clear the env var to disable.
        if value in (None, "", "null"):
            return None
        return value

    @field_validator("retention_days")
    @classmethod
    def _validate_retention_days(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0:
            msg = f"retention_days must be a positive integer or unset; got {value}"
            raise ValueError(msg)
        return value


settings = Settings()
