"""Unit tests for the worker's structured-logging primitives (T5.4).

Mirrors ``apps/api/tests/unit/test_logging.py`` for parity. The worker
also exercises Celery signals via ``worker.core.observability``.
"""

from __future__ import annotations

import json
import logging

from worker.core.logging import (
    ApiKeyScrubFilter,
    CorrelationFilter,
    JsonFormatter,
    file_id_var,
    scan_id_var,
    task_id_var,
    upload_id_var,
)
from worker.core.observability import (
    _on_task_postrun,
    _on_task_prerun,
    _safe_str,
)


def _record(
    *,
    level: int = logging.INFO,
    msg: str = "hello",
    args: tuple[object, ...] | None = None,
    extra: dict[str, object] | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="worker.test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args or (),
        exc_info=None,
    )
    if extra:
        for key, value in extra.items():
            record.__dict__[key] = value
    return record


# ---- JsonFormatter ---------------------------------------------------------


def test_formatter_emits_required_fields() -> None:
    payload = json.loads(JsonFormatter().format(_record(msg="hello")))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "worker.test"
    assert payload["message"] == "hello"
    assert payload["timestamp"].endswith("+00:00")


def test_formatter_omits_unset_correlation_keys() -> None:
    payload = json.loads(JsonFormatter().format(_record()))
    for key in ("task_id", "scan_id", "upload_id", "file_id"):
        assert key not in payload


def test_formatter_includes_each_correlation_key_when_filter_runs() -> None:
    tokens = [
        task_id_var.set("task-1"),
        scan_id_var.set("scan-1"),
        upload_id_var.set("upload-1"),
        file_id_var.set("file-1"),
    ]
    try:
        record = _record()
        CorrelationFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        file_id_var.reset(tokens[3])
        upload_id_var.reset(tokens[2])
        scan_id_var.reset(tokens[1])
        task_id_var.reset(tokens[0])
    assert payload["task_id"] == "task-1"
    assert payload["scan_id"] == "scan-1"
    assert payload["upload_id"] == "upload-1"
    assert payload["file_id"] == "file-1"


# ---- ApiKeyScrubFilter -----------------------------------------------------


_FAKE_KEY = "AIza" + "y" * 35


def test_scrub_filter_redacts_msg_and_args() -> None:
    record = _record(msg="key=%s", args=(_FAKE_KEY,))
    ApiKeyScrubFilter().filter(record)
    assert _FAKE_KEY not in record.getMessage()
    assert "AIza<redacted>" in record.getMessage()


def test_scrub_filter_redacts_nested_extras() -> None:
    record = _record(extra={"context": [{"value": _FAKE_KEY}]})
    ApiKeyScrubFilter().filter(record)
    nested = record.__dict__["context"]
    assert _FAKE_KEY not in nested[0]["value"]


def test_formatter_redacts_api_key_in_object_arg_after_interpolation() -> None:
    """Codex round-7 P1: an arg whose ``__str__`` contains the key bypasses
    the scrub filter (filter only walks string args). The key only
    materializes during ``record.getMessage()``'s ``%`` interpolation,
    which runs at format time. ``JsonFormatter`` must scrub the rendered
    message as a backstop.
    """

    class _LeakyError(Exception):
        def __str__(self) -> str:
            return f"https://api.example.com/?key={_FAKE_KEY}"

    record = _record(msg="upstream call failed: %s", args=(_LeakyError(),))
    # Run the scrub filter (it leaves the non-string arg untouched).
    ApiKeyScrubFilter().filter(record)
    # Format and assert the rendered message has been redacted.
    payload = json.loads(JsonFormatter().format(record))
    assert (
        _FAKE_KEY not in payload["message"]
    ), f"API key leaked through %s interpolation: {payload['message']!r}"
    assert "AIza<redacted>" in payload["message"]


# ---- Celery signal handlers ------------------------------------------------


class _FakeTask:
    """Stand-in for a Celery task instance — only the ``name`` attr is read."""

    def __init__(self, name: str) -> None:
        self.name = name


def _reset_all() -> None:
    task_id_var.set(None)
    scan_id_var.set(None)
    upload_id_var.set(None)
    file_id_var.set(None)


def test_prerun_sets_task_id() -> None:
    _reset_all()
    _on_task_prerun(
        sender="worker.tasks.ping.ping",
        task_id="task-uuid-1",
        task=_FakeTask("worker.tasks.ping.ping"),
        args=(),
    )
    assert task_id_var.get() == "task-uuid-1"
    assert scan_id_var.get() is None  # ping doesn't seed scan_id
    _reset_all()


def test_prerun_sets_scan_id_for_run_scan() -> None:
    _reset_all()
    _on_task_prerun(
        sender="worker.tasks.run_scan.run_scan",
        task_id="task-uuid-2",
        task=_FakeTask("worker.tasks.run_scan.run_scan"),
        args=("scan-uuid-2",),
    )
    assert task_id_var.get() == "task-uuid-2"
    assert scan_id_var.get() == "scan-uuid-2"
    _reset_all()


def test_prerun_sets_upload_id_for_prepare_upload() -> None:
    _reset_all()
    _on_task_prerun(
        sender="worker.tasks.prepare_upload.prepare_upload",
        task_id="task-uuid-3",
        task=_FakeTask("worker.tasks.prepare_upload.prepare_upload"),
        args=("upload-uuid-3",),
    )
    assert upload_id_var.get() == "upload-uuid-3"
    _reset_all()


def test_postrun_clears_all_correlation_vars() -> None:
    task_id_var.set("t")
    scan_id_var.set("s")
    upload_id_var.set("u")
    file_id_var.set("f")
    _on_task_postrun(
        sender="worker.tasks.run_scan.run_scan",
        task_id="t",
        task=_FakeTask("worker.tasks.run_scan.run_scan"),
        args=(),
    )
    assert task_id_var.get() is None
    assert scan_id_var.get() is None
    assert upload_id_var.get() is None
    assert file_id_var.get() is None


def test_safe_str_rejects_log_injection_shapes() -> None:
    assert _safe_str("normal-id") == "normal-id"
    assert _safe_str(None) is None
    # Newlines / overlong values are rejected (mirrors api request-id rules).
    assert _safe_str("has\nnewline") is None
    assert _safe_str("a" * 65) is None


def test_prerun_silently_skips_when_args_missing() -> None:
    """The run_scan task is always invoked with positional scan_id, but a
    weird call site (e.g. a unit test invoking ``.apply()`` with empty args)
    shouldn't blow up — we just leave scan_id unset."""

    _reset_all()
    _on_task_prerun(
        sender="worker.tasks.run_scan.run_scan",
        task_id="task-uuid-4",
        task=_FakeTask("worker.tasks.run_scan.run_scan"),
        args=(),
    )
    assert task_id_var.get() == "task-uuid-4"
    assert scan_id_var.get() is None
    _reset_all()


# ---- Celery root-logger hijack (Codex P1) -----------------------------------


def test_celery_app_disables_root_logger_hijack() -> None:
    """Codex P1: Celery's ``worker_hijack_root_logger`` defaults to True,
    which would replace the JsonFormatter + ApiKeyScrubFilter we install
    in ``configure_logging`` once the worker bootstrap finishes. The conf
    must opt out so structured logs survive into task execution.
    """

    from worker.celery_app import celery_app

    assert celery_app.conf.worker_hijack_root_logger is False, (
        "worker_hijack_root_logger must be False or our JSON formatter + "
        "API-key scrub filter get silently replaced by Celery's ColorFormatter"
    )


def test_celery_setup_logging_signal_is_hijacked() -> None:
    """Codex round-3 P2: Celery's ``celery worker --loglevel=info`` would
    reset the root logger level after our import-time ``configure_logging``
    runs, silently overriding the LOG_LEVEL env knob we advertise. The fix
    connects to the ``setup_logging`` signal — a connected handler tells
    Celery "I've handled logging, don't touch it" so the CLI flag becomes
    a no-op and ``settings.log_level`` (env-driven) wins.
    """

    from celery.signals import setup_logging

    # ``setup_logging.receivers`` is a list of (lookup_key, weakref-or-callable)
    # tuples. Any non-empty receivers list is enough to short-circuit Celery's
    # default logging setup.
    assert setup_logging.receivers, (
        "setup_logging signal must have a connected handler — without one, "
        "Celery resets root level to --loglevel and ignores LOG_LEVEL env"
    )


def test_configure_logging_sets_handler_level() -> None:
    """Codex round-3 P3: same fix as the api copy — the handler must carry
    the configured level so propagated child records (celery.app.trace,
    kombu, sqlalchemy, …) get filtered, not just records emitted at root.
    """

    from worker.core.logging import configure_logging

    configure_logging(level="error")
    root = logging.getLogger()
    assert root.handlers
    handler = root.handlers[0]
    assert (
        handler.level == logging.ERROR
    ), f"handler must inherit the configured level (ERROR=40); got {handler.level}"


# ---- ContextVar propagation across ThreadPoolExecutor (Codex P2) ------------


def test_contextvar_propagates_into_thread_pool_via_copy_context() -> None:
    """Codex P2: ``run_scan._dispatch`` copies the current context per
    submission so worker threads inherit ``task_id`` / ``scan_id`` set on
    the main thread by Celery signals. This test pins down the propagation
    pattern itself; the per-file thread sees the parent's context vars.
    """

    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    task_id_var.set("task-T-PROP-1")
    scan_id_var.set("scan-S-PROP-1")

    def _read_context_vars() -> tuple[str | None, str | None]:
        return task_id_var.get(), scan_id_var.get()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            ctx_a = contextvars.copy_context()
            ctx_b = contextvars.copy_context()
            fut_a = pool.submit(ctx_a.run, _read_context_vars)
            fut_b = pool.submit(ctx_b.run, _read_context_vars)
            assert fut_a.result() == ("task-T-PROP-1", "scan-S-PROP-1")
            assert fut_b.result() == ("task-T-PROP-1", "scan-S-PROP-1")

            # Sanity check: without copy_context the thread starts with
            # the default (None) — verifies the propagation actually
            # depends on copy_context, not on some thread-local accident.
            fut_c = pool.submit(_read_context_vars)
            assert fut_c.result() == (None, None)
    finally:
        task_id_var.set(None)
        scan_id_var.set(None)


# ---- Codex P1 follow-up: redact API keys in serialized exception text -------


def test_formatter_scrubs_api_key_in_exception_traceback() -> None:
    """Codex P1 follow-up: ``logger.exception`` serializes the exception
    via ``formatException``. The worker holds ``GOOGLE_AI_API_KEY``, so a
    Gemma SDK exception whose message includes the key (e.g. an
    ``HTTPError`` carrying the request URL) would otherwise leak the key
    into the ``exc`` field of every error log. The formatter applies the
    scrub regex to the formatted exception text as a hard backstop.
    """

    import sys

    leaky = "AIza" + "y" * 35
    try:
        raise RuntimeError(f"gemma call failed for key {leaky}")
    except RuntimeError:
        record = logging.LogRecord(
            name="worker.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=0,
            msg="upstream gemma error",
            args=None,
            exc_info=sys.exc_info(),
        )

    formatted = json.loads(JsonFormatter().format(record))
    assert "exc" in formatted
    assert leaky not in formatted["exc"], f"API key leaked into exc field: {formatted['exc']!r}"
    assert "AIza<redacted>" in formatted["exc"]
