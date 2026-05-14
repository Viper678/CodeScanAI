"""``run_scan`` Celery task — the scan orchestrator.

Loads a Scan + its scan_files + the underlying files + the upload's extract
path, dispatches each (file, scan_type) pair to the matching scanner via a
bounded thread pool, and finalizes the scan with aggregate token / call
usage. Per-file failures don't fail the run; cancellation is polled between
batches by re-reading ``scan.status``.

Why threads (not asyncio): Celery tasks are sync, and the only blocking IO
worth parallelizing is the Gemma HTTP call. ThreadPoolExecutor is the
simplest fit, and SDK calls release the GIL during socket waits.

Per-file dispatch decision: ``scan_files`` is one row per file (NOT one per
file-per-scan-type, per docs/SCHEMA.md §scan_files). To keep the per-file
status atomic, all scan_types for a given file run sequentially inside a
single thread; the row is updated once with aggregated tokens/latency. If at
least one scan_type produced findings, the row is ``done``; if all
scan_types raised, it's ``failed`` with a joined error message.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, attributes, sessionmaker

from worker.celery_app import celery_app
from worker.core import db as worker_db
from worker.core.config import settings
from worker.core.logging import file_id_var
from worker.core.models import (
    SCAN_FILE_STATUS_DONE,
    SCAN_FILE_STATUS_FAILED,
    SCAN_FILE_STATUS_RUNNING,
    SCAN_FILE_STATUS_SKIPPED,
    SCAN_STATUS_CANCELLED,
    SCAN_STATUS_COMPLETED,
    SCAN_STATUS_FAILED,
    SCAN_STATUS_PENDING,
    SCAN_STATUS_RUNNING,
    SCAN_TYPE_BUGS,
    SCAN_TYPE_KEYWORDS,
    SCAN_TYPE_SECURITY,
    File,
    Scan,
    ScanFile,
    ScanFinding,
    Upload,
)
from worker.llm.client import GemmaClient
from worker.scanners.base import (
    Finding,
    KeywordsConfig,
    ScanContext,
    Scanner,
)
from worker.scanners.bugs import BugsScanner
from worker.scanners.keywords import KeywordScanner
from worker.scanners.security import SecurityScanner
from worker.storage import Storage, StorageKeyError, get_storage

logger = logging.getLogger(__name__)

ScannerRegistry = dict[str, Scanner]
ScannerRegistryFactory = Callable[[list[str], KeywordsConfig | None], ScannerRegistry]

# Sentinel prefix used to discriminate the benign "user deleted upload while
# scan was running" race from other LookupError causes (e.g. scan id missing
# at task start). The task entry point swallows + INFO-logs the former; the
# latter still bubbles up to Celery's failure handler.
_SCAN_DISAPPEARED_PREFIX = "scan disappeared mid-run:"


# ---- Per-file plan ----------------------------------------------------------


@dataclass(frozen=True)
class _FilePlan:
    """Pre-flight materialization for one scan_file row.

    Post-M2: holds a storage key rather than a filesystem Path. The
    backing bytes are read through ``Storage.get_bytes`` (LocalStorage:
    direct filesystem; GcsStorage: HTTP fetch). The size + binary +
    language metadata is captured from the ``files`` row up front so the
    pre-flight skip pass doesn't need to touch storage at all.
    """

    scan_file_id: UUID
    file_id: UUID
    relative_path: str
    key: str
    language: str | None
    size_bytes: int
    is_binary: bool

    def read_text(self, storage: Storage, *, encoding: str = "utf-8") -> str:
        """Read the file's content as ``str`` via the Storage backend.

        Mirrors the pre-M2 ``Path.read_text(encoding=..., errors='replace')``
        contract: bad UTF-8 is replaced rather than raising, because
        scanners deal with mojibake gracefully and a per-file decode
        failure shouldn't fail the whole scan. Bounded by the
        ``max_scan_file_size_mb`` pre-flight skip, so the in-memory cost
        is capped at 1 MiB per file by default.
        """

        data = storage.get_bytes(self.key)
        return data.decode(encoding, errors="replace")


@dataclass
class _PerFileOutcome:
    """What a worker thread reports back to the main thread."""

    scan_file_id: UUID
    findings_by_type: dict[str, list[Finding]] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    total_latency_ms: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    final_status: str = SCAN_FILE_STATUS_DONE
    final_error: str | None = None


# ---- Public task ------------------------------------------------------------


@celery_app.task(  # type: ignore[misc]
    bind=True,
    name="worker.tasks.run_scan.run_scan",
)
def run_scan(self: Task, scan_id: str) -> dict[str, object] | None:
    """Run a scan end-to-end. Idempotent on re-delivery (terminal status no-ops).

    Args:
        scan_id: String form of the scan's UUID.

    Returns:
        Small dict for the celery result backend with final status + progress,
        or ``None`` when the scan vanished mid-run because the user deleted
        the parent upload (the DB cascade dropped the scan row — see
        ``docs/API.md`` §``DELETE /uploads/{id}``). That race is benign and
        logged at INFO so the worker doesn't surface a spurious ERROR +
        traceback for user-initiated cleanup.

    Raises:
        LookupError: scan id does not exist at task start (NOT the benign
            mid-run cascade — that path is caught here and returns ``None``).
    """

    del self  # unused; bound for explicit naming in error traces
    try:
        return _run(scan_id, scanner_registry_factory=_default_scanner_registry)
    except LookupError as exc:
        # Discriminator: the scan was found at task start (so _run got past
        # the "scan not found" raise) but disappeared between dispatch and
        # finalize — that's the user-deleted-upload cascade. Any other
        # LookupError (e.g. _run's "scan not found: ..." raise from line 177)
        # bubbles up so Celery's failure handler logs the real bug.
        if str(exc).startswith(_SCAN_DISAPPEARED_PREFIX):
            # ``scan_id`` is intentionally NOT in ``extra`` here — the worker's
            # LogRecord factory (worker.core.logging) already snapshots the
            # scan_id contextvar onto every record, and Python's logging raises
            # ``KeyError`` if ``extra`` tries to overwrite an existing record
            # attribute. Pass only the fields the factory doesn't already cover.
            logger.info(
                "scan deleted by user mid-run, no-op",
                extra={"reason": str(exc)},
            )
            return None
        raise


def _run(
    scan_id: str,
    *,
    scanner_registry_factory: ScannerRegistryFactory,
    session_maker: sessionmaker[Session] | None = None,
) -> dict[str, object]:
    """Orchestrator core, parameterized for tests.

    Args:
        scan_id: scan UUID as string.
        scanner_registry_factory: callable ``(scan_types, keywords_cfg) -> ScannerRegistry``.
            Tests inject a fake here to avoid touching the network.
        session_maker: override for ``worker.core.db.SessionMaker``; tests use
            this so per-thread sessions hit the integration DB.
    """

    parsed_id = UUID(scan_id)
    maker = session_maker if session_maker is not None else worker_db.SessionMaker
    storage = get_storage()

    with maker() as session:
        scan = session.scalar(select(Scan).where(Scan.id == parsed_id))
        if scan is None:
            logger.error("run_scan: scan %s not found", scan_id)
            raise LookupError(f"scan not found: {scan_id}")

        if scan.status in (SCAN_STATUS_COMPLETED, SCAN_STATUS_FAILED, SCAN_STATUS_CANCELLED):
            logger.info("run_scan: scan %s already terminal (%s)", scan_id, scan.status)
            return _result_dict(scan)

        # Move pending -> running (allow re-entry from running too — replay).
        if scan.status in (SCAN_STATUS_PENDING, SCAN_STATUS_RUNNING):
            scan.status = SCAN_STATUS_RUNNING
            scan.started_at = scan.started_at or datetime.now(UTC)
            scan.error = None
            session.commit()

        keywords_cfg = _parse_keywords(scan.keywords)
        scan_types: list[str] = list(scan.scan_types or [])
        upload = session.scalar(select(Upload).where(Upload.id == scan.upload_id))
        if upload is None or not upload.extract_path:
            scan.status = SCAN_STATUS_FAILED
            scan.error = "upload missing or not extracted"
            scan.finished_at = datetime.now(UTC)
            session.commit()
            return _result_dict(scan)
        # Pre-M2 rows persisted extract_path as an absolute filesystem path
        # (``/data/extracts/<id>``). Post-M2 storage backends reject leading-
        # slash keys, so any per-file read would die in ``_build_plans`` /
        # preflight with a ValueError — leaving the scan stuck in ``running``.
        # Fail the scan cleanly so the operator can re-upload. Codex P1 on M2.
        if upload.extract_path.startswith("/"):
            scan.status = SCAN_STATUS_FAILED
            scan.error = "upload predates storage migration; re-upload required"
            scan.finished_at = datetime.now(UTC)
            session.commit()
            return _result_dict(scan)
        # Post-M2: extract_path holds a storage prefix (e.g.
        # ``uploads/<id>/extracted``) — the worker joins per-file keys
        # against this string, not a filesystem path. Strip any
        # trailing slash so the join produces clean keys.
        extract_prefix = upload.extract_path.rstrip("/")

        plans = _build_plans(session, parsed_id, extract_prefix)

    # Pre-flight skip pass — done in a fresh session so we can stream updates.
    eligible: list[_FilePlan] = []
    with maker() as session:
        for plan in plans:
            skip_reason = _preflight_skip(plan, storage)
            if skip_reason is not None:
                _mark_skipped(session, plan.scan_file_id, skip_reason)
                _bump_progress(session, parsed_id)
            else:
                eligible.append(plan)
        session.commit()

    # Construct the scanner registry. If this fails (e.g. LLM_BASE_URL is
    # malformed for an LLM scan, network blip while building the SDK client),
    # the scan would otherwise sit stuck in `running` because the task raised
    # AFTER we flipped to `running` but BEFORE the dispatch loop owns the
    # finalize. Catch and mark `failed` with a clear error.
    try:
        registry = scanner_registry_factory(scan_types, keywords_cfg)
    except Exception as exc:
        logger.exception("run_scan: failed to build scanner registry for %s", scan_id)
        with maker() as session:
            scan = session.scalar(select(Scan).where(Scan.id == parsed_id))
            if scan is not None:
                scan.status = SCAN_STATUS_FAILED
                scan.error = f"scanner_init_failed: {exc}"[:500]
                scan.finished_at = datetime.now(UTC)
                session.commit()
        raise

    cancelled = False
    if eligible:
        cancelled = _dispatch(
            scan_id=parsed_id,
            plans=eligible,
            scan_types=scan_types,
            keywords_cfg=keywords_cfg,
            registry=registry,
            maker=maker,
            storage=storage,
        )

    # Finalize.
    with maker() as session:
        scan = session.scalar(select(Scan).where(Scan.id == parsed_id))
        if scan is None:
            raise LookupError(f"{_SCAN_DISAPPEARED_PREFIX} {scan_id}")

        if cancelled or scan.status == SCAN_STATUS_CANCELLED:
            # Honor the cancellation: don't flip to completed.
            session.commit()
            return _result_dict(scan)

        usage = _aggregate_usage(session, parsed_id, scan_types=scan_types)
        merged = dict(scan.model_settings or {})
        merged["usage"] = usage
        scan.model_settings = merged
        # JSONB needs an explicit modified flag for in-place dict updates;
        # we rebuild the dict above so reassignment alone is sufficient, but
        # flag_modified is defensive and harmless.
        attributes.flag_modified(scan, "model_settings")
        scan.status = SCAN_STATUS_COMPLETED
        scan.finished_at = datetime.now(UTC)
        session.commit()
        return _result_dict(scan)


# ---- Default registry -------------------------------------------------------


def _default_scanner_registry(
    scan_types: list[str], keywords_cfg: KeywordsConfig | None
) -> ScannerRegistry:
    """Construct only the scanners the scan actually needs.

    Building ``GemmaClient`` opens an HTTP client against ``LLM_BASE_URL``;
    constructing it eagerly for a keyword-only scan would do unnecessary work
    on installs without a reachable vLLM. Build LLM scanners only when the
    scan selected ``security`` or ``bugs``.

    ``keywords_cfg`` is accepted for signature parity with test factories;
    the keyword scanner reads it via ``ScanContext`` per call.
    """

    del keywords_cfg
    registry: ScannerRegistry = {}
    needs_llm = any(t in (SCAN_TYPE_SECURITY, SCAN_TYPE_BUGS) for t in scan_types)
    if needs_llm:
        if settings.llm_mock_mode:
            # T5.5 e2e: deterministic canned findings, no outbound HTTP. The
            # mock transport ignores base_url / api_key, so we pass placeholders.
            from worker.llm.mock_transport import MockGemmaTransport

            client = GemmaClient(
                base_url=settings.llm_base_url,
                model=settings.gemma_model,
                transport=MockGemmaTransport(),
            )
        else:
            api_key_secret = settings.llm_api_key
            api_key = api_key_secret.get_secret_value() if api_key_secret else None
            client = GemmaClient(
                base_url=settings.llm_base_url,
                api_key=api_key,
                model=settings.gemma_model,
            )
        if SCAN_TYPE_SECURITY in scan_types:
            registry[SCAN_TYPE_SECURITY] = SecurityScanner(client)
        if SCAN_TYPE_BUGS in scan_types:
            registry[SCAN_TYPE_BUGS] = BugsScanner(client)
    if SCAN_TYPE_KEYWORDS in scan_types:
        registry[SCAN_TYPE_KEYWORDS] = KeywordScanner()
    return registry


# ---- Plan construction ------------------------------------------------------


def _build_plans(session: Session, scan_id: UUID, extract_prefix: str) -> list[_FilePlan]:
    """Load scan_files joined to files and materialize per-file plans.

    Only non-terminal rows (``pending`` / ``running``) are returned. On Celery
    re-delivery after partial completion, already-finalized rows
    (``done`` / ``skipped`` / ``failed``) keep their findings and stay out of
    the worklist — re-running them would duplicate ``scan_findings`` inserts
    and bump ``scan.progress_done`` past ``progress_total``.

    ``extract_prefix`` is the storage prefix (no trailing slash) that
    ``files.path`` is relative to. Each plan's storage key is built as
    ``{extract_prefix}/{file.path}``.
    """

    rows = session.execute(
        select(ScanFile, File)
        .join(File, ScanFile.file_id == File.id)
        .where(
            ScanFile.scan_id == scan_id,
            ScanFile.status.notin_(
                (
                    SCAN_FILE_STATUS_DONE,
                    SCAN_FILE_STATUS_SKIPPED,
                    SCAN_FILE_STATUS_FAILED,
                )
            ),
        )
        .order_by(File.path)
    ).all()
    plans: list[_FilePlan] = []
    for sf, f in rows:
        plans.append(
            _FilePlan(
                scan_file_id=sf.id,
                file_id=f.id,
                relative_path=f.path,
                key=f"{extract_prefix}/{f.path}",
                language=f.language,
                size_bytes=f.size_bytes,
                is_binary=f.is_binary,
            )
        )
    return plans


def _preflight_skip(plan: _FilePlan, storage: Storage) -> str | None:
    """Decide whether ``plan`` should be skipped pre-dispatch. Returns reason or None."""

    if plan.is_binary:
        return "binary"
    max_bytes = settings.max_scan_file_size_mb * 1024 * 1024
    if plan.size_bytes > max_bytes:
        return "oversize"
    # ``storage.size`` doubles as the existence check — a missing key
    # raises ``StorageKeyError`` which we map to ``missing``. Cheap on
    # both backends (LocalStorage: stat; GcsStorage: HEAD).
    try:
        content_len = storage.size(plan.key)
    except StorageKeyError:
        return "missing"
    except Exception:
        # justify: GCS transport / IAM errors don't subclass
        # StorageKeyError or OSError (they live under
        # ``google.api_core.exceptions``). Without containment, a
        # transient cloud hiccup during preflight would abort the
        # Celery task while the scan is already ``running``, stranding
        # it. Treat the file as unreadable and skip — the per-row
        # error gets logged with the actual cause so an operator can
        # see what happened. Codex P2 on M2.
        logger.warning(
            "preflight storage.size failed for key=%r; skipping file",
            plan.key,
            exc_info=True,
        )
        return "missing"
    # Estimate tokens as chars/4 (approximate for code per SCAN_RULES.md
    # §"Token budget & chunking"). Files exceeding the per-call budget are
    # skipped here; chunking those is the documented follow-up.
    if content_len // 4 > settings.gemma_max_input_tokens:
        return "too_large_for_context"
    return None


# ---- Per-file work ----------------------------------------------------------


def _process_file(
    plan: _FilePlan,
    *,
    scan_types: list[str],
    keywords_cfg: KeywordsConfig | None,
    registry: ScannerRegistry,
    maker: sessionmaker[Session],
    storage: Storage,
) -> _PerFileOutcome:
    """Run all selected scan_types on one file, sequentially, in this thread.

    Each thread owns its own SQLAlchemy session — sessions are not thread-safe.
    """

    # Stamp file_id correlation for the duration of this per-file work so
    # log lines emitted from the scanners + persistence helpers carry it.
    # ContextVar is thread-local in the absence of an explicit Context;
    # the worker thread runs in the Celery prefork pool's child process
    # and gets its own isolated context here.
    file_id_token = file_id_var.set(str(plan.file_id))
    try:
        # Mark running in its own short transaction.
        with maker() as session:
            sf = session.scalar(select(ScanFile).where(ScanFile.id == plan.scan_file_id))
            if sf is not None:
                sf.status = SCAN_FILE_STATUS_RUNNING
                sf.started_at = datetime.now(UTC)
                session.commit()

        outcome = _process_file_no_db(
            plan,
            scan_types=scan_types,
            keywords_cfg=keywords_cfg,
            registry=registry,
            storage=storage,
        )
        _persist_outcome(plan, outcome, maker)
        return outcome
    finally:
        file_id_var.reset(file_id_token)


def _process_file_no_db(
    plan: _FilePlan,
    *,
    scan_types: list[str],
    keywords_cfg: KeywordsConfig | None,
    registry: ScannerRegistry,
    storage: Storage,
) -> _PerFileOutcome:
    """Pure scanner dispatch for one file — no DB access. Unit-test entry point."""

    outcome = _PerFileOutcome(scan_file_id=plan.scan_file_id)

    try:
        content = plan.read_text(storage)
    except StorageKeyError as exc:
        outcome.final_status = SCAN_FILE_STATUS_FAILED
        outcome.final_error = f"read_error: {exc}"[:500]
        return outcome
    except OSError as exc:
        outcome.final_status = SCAN_FILE_STATUS_FAILED
        outcome.final_error = f"read_error: {exc}"[:500]
        return outcome
    except Exception as exc:
        # justify: GCS SDK errors (google.api_core.exceptions.*) don't
        # subclass OSError. Treat as a per-file read failure so dispatch
        # can finalize the scan cleanly instead of letting the exception
        # escape ``fut.result()`` and stall the rows. Codex P2 on M2.
        logger.warning(
            "read_text failed for key=%r (non-OSError); marking file failed",
            plan.key,
            exc_info=True,
        )
        outcome.final_status = SCAN_FILE_STATUS_FAILED
        outcome.final_error = f"read_error: {exc}"[:500]
        return outcome

    any_success = False
    for scan_type in scan_types:
        scanner = registry.get(scan_type)
        if scanner is None:
            outcome.errors[scan_type] = "no scanner registered"
            continue
        ctx = ScanContext(
            relative_path=plan.relative_path,
            language=plan.language,
            keywords=keywords_cfg if scan_type == SCAN_TYPE_KEYWORDS else None,
        )
        try:
            result = scanner.scan_file(content, ctx)
        except Exception as exc:  # justify: per-file fault must not fail the run
            logger.warning("scanner %s failed on %s: %s", scan_type, plan.relative_path, exc)
            outcome.errors[scan_type] = str(exc)[:200]
            continue
        any_success = True
        outcome.findings_by_type[scan_type] = result.findings
        outcome.tokens_in += result.tokens_in
        outcome.tokens_out += result.tokens_out
        outcome.total_latency_ms += result.latency_ms

    if not any_success:
        outcome.final_status = SCAN_FILE_STATUS_FAILED
        outcome.final_error = "; ".join(f"{k}:{v}" for k, v in outcome.errors.items())[:500]
    else:
        outcome.final_status = SCAN_FILE_STATUS_DONE
        outcome.final_error = None
    return outcome


def _persist_outcome(
    plan: _FilePlan,
    outcome: _PerFileOutcome,
    maker: sessionmaker[Session],
) -> None:
    """Insert findings + finalize the scan_file row in one short transaction."""

    with maker() as session:
        sf = session.scalar(select(ScanFile).where(ScanFile.id == plan.scan_file_id))
        if sf is None:
            return
        # Need scan_id to insert findings — load it from the scan_file row.
        scan_id = sf.scan_id
        for scan_type, findings in outcome.findings_by_type.items():
            for f in findings:
                session.add(
                    ScanFinding(
                        scan_id=scan_id,
                        file_id=plan.file_id,
                        scan_type=scan_type,
                        severity=f.severity,
                        title=f.title,
                        message=f.message,
                        recommendation=f.recommendation,
                        line_start=f.line_start,
                        line_end=f.line_end,
                        snippet=None,
                        rule_id=f.rule_id,
                        confidence=Decimal(str(f.confidence)) if f.confidence is not None else None,
                        meta={},
                    )
                )

        sf.status = outcome.final_status
        sf.error = outcome.final_error
        sf.tokens_in = outcome.tokens_in or None
        sf.tokens_out = outcome.tokens_out or None
        sf.latency_ms = outcome.total_latency_ms or None
        sf.finished_at = datetime.now(UTC)
        session.commit()


# ---- Dispatch loop ----------------------------------------------------------


def _dispatch(
    *,
    scan_id: UUID,
    plans: list[_FilePlan],
    scan_types: list[str],
    keywords_cfg: KeywordsConfig | None,
    registry: ScannerRegistry,
    maker: sessionmaker[Session],
    storage: Storage,
) -> bool:
    """Submit per-file work to a thread pool and watch for cancellation.

    Returns True if cancelled mid-run.
    """

    cancelled = False
    completed = 0
    futures: dict[Future[_PerFileOutcome], _FilePlan] = {}
    # Each worker thread runs inside its OWN copy of the parent task's
    # correlation context (task_id, scan_id set by Celery signals on the
    # main thread). ``ThreadPoolExecutor`` does not propagate ContextVars
    # across the thread boundary by default — without this snapshot the
    # per-file scanner logs would carry only ``file_id`` and lose
    # ``scan_id`` / ``task_id``, breaking the worker correlation contract
    # advertised in T5.4. ``Context.run`` raises ``RuntimeError`` when
    # called on the same context object from more than one OS thread, so
    # we copy per submission.
    with ThreadPoolExecutor(max_workers=settings.scan_concurrency) as executor:
        for plan in plans:
            ctx = contextvars.copy_context()
            fut = executor.submit(
                ctx.run,
                _process_file,
                plan,
                scan_types=scan_types,
                keywords_cfg=keywords_cfg,
                registry=registry,
                maker=maker,
                storage=storage,
            )
            futures[fut] = plan

        try:
            for fut in as_completed(futures):
                _outcome = fut.result()
                completed += 1
                _atomic_progress_bump(maker, scan_id)

                if completed % max(settings.cancel_check_interval_files, 1) == 0 and _is_cancelled(
                    maker, scan_id
                ):
                    cancelled = True
                    break
        finally:
            if cancelled:
                executor.shutdown(wait=False, cancel_futures=True)
            # If we exit normally, the with-block waits for in-flight futures.

    return cancelled


def _atomic_progress_bump(maker: sessionmaker[Session], scan_id: UUID) -> None:
    """Increment ``scan.progress_done`` with a single SQL UPDATE.

    Uses raw SQL UPDATE rather than read-modify-write to avoid races even
    though only the main thread bumps progress today — this keeps the
    invariant honest if we ever bump from worker threads.
    """

    with maker() as session:
        session.execute(
            update(Scan).where(Scan.id == scan_id).values(progress_done=Scan.progress_done + 1)
        )
        session.commit()


def _is_cancelled(maker: sessionmaker[Session], scan_id: UUID) -> bool:
    with maker() as session:
        status = session.scalar(select(Scan.status).where(Scan.id == scan_id))
        return status == SCAN_STATUS_CANCELLED


# ---- Helpers ----------------------------------------------------------------


def _parse_keywords(raw: dict[str, Any] | None) -> KeywordsConfig | None:
    """Deserialize ``scan.keywords`` JSONB to a typed config, or None if empty."""

    if not raw:
        return None
    items = raw.get("items") or []
    if not isinstance(items, list):
        return None
    return KeywordsConfig(
        items=[str(i) for i in items],
        case_sensitive=bool(raw.get("case_sensitive", False)),
        regex=bool(raw.get("regex", False)),
    )


def _mark_skipped(session: Session, scan_file_id: UUID, reason: str) -> None:
    sf = session.scalar(select(ScanFile).where(ScanFile.id == scan_file_id))
    if sf is None:
        return
    now = datetime.now(UTC)
    sf.status = SCAN_FILE_STATUS_SKIPPED
    sf.error = reason
    sf.started_at = sf.started_at or now
    sf.finished_at = now


def _bump_progress(session: Session, scan_id: UUID) -> None:
    session.execute(
        update(Scan).where(Scan.id == scan_id).values(progress_done=Scan.progress_done + 1)
    )


def _aggregate_usage(session: Session, scan_id: UUID, *, scan_types: list[str]) -> dict[str, int]:
    """Sum tokens across this scan's scan_files for the model_settings.usage block."""

    row = session.execute(
        select(
            func.coalesce(func.sum(ScanFile.tokens_in), 0),
            func.coalesce(func.sum(ScanFile.tokens_out), 0),
            func.count(ScanFile.id).filter(ScanFile.tokens_in.isnot(None)),
        ).where(ScanFile.scan_id == scan_id)
    ).one()
    return _aggregate_usage_from_rows(
        int(row[0] or 0),
        int(row[1] or 0),
        files_with_calls=int(row[2] or 0),
        scan_types=scan_types,
    )


def _aggregate_usage_from_rows(
    total_in: int,
    total_out: int,
    *,
    files_with_calls: int,
    scan_types: list[str],
) -> dict[str, int]:
    """Build the usage dict from already-aggregated counters.

    ``calls`` is files-with-LLM-activity multiplied by the number of LLM scan
    types selected. Approximate but bounded — keyword-only rows leave
    tokens_in null so they don't inflate the count.
    """

    llm_types = [t for t in scan_types if t in (SCAN_TYPE_SECURITY, SCAN_TYPE_BUGS)]
    calls = files_with_calls * len(llm_types) if files_with_calls else 0
    return {
        "total_tokens_in": total_in,
        "total_tokens_out": total_out,
        "calls": calls,
    }


def _result_dict(scan: Scan) -> dict[str, object]:
    return {
        "status": scan.status,
        "progress_done": scan.progress_done,
        "progress_total": scan.progress_total,
    }
