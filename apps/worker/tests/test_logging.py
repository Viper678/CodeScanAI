"""Unit tests for the worker's structured-logging primitives (T5.4).

Mirrors ``apps/api/tests/unit/test_logging.py`` for parity. The worker
also exercises Celery signals via ``worker.core.observability``.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock

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


# ---- Sentry hook (smoke) ---------------------------------------------------


def test_init_sentry_skipped_when_dsn_unset(monkeypatch: Any) -> None:
    """No DSN → no init runs. We assert by patching the SDK and checking
    it wasn't touched."""

    from worker.core import config as cfg
    from worker.core import observability as obs

    monkeypatch.setattr(cfg.settings, "sentry_dsn", None)
    fake_sdk = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", fake_sdk)
    obs.init_sentry_if_configured()
    fake_sdk.init.assert_not_called()


# ---- Sentry before_send scrub (Codex round-4 P1) ----------------------------


def test_init_sentry_disables_logging_integration_event_capture(
    monkeypatch: Any,
) -> None:
    """Codex round-7 P2: ``ignore_logger(__name__)`` from round 5 only
    covered the observability module. Other task code does
    ``logger.exception`` then re-raises (e.g. ``run_scan`` scanner-registry
    failures), so Sentry's default LoggingIntegration captures those as
    standalone events while CeleryIntegration captures the same exception
    on re-raise — duplicate Sentry events with non-deterministic dedupe.

    The proper fix is to disable LoggingIntegration's *event* capture
    entirely (keep breadcrumbs) so only CeleryIntegration produces task
    failure events. This test pins down: ``LoggingIntegration`` is in the
    integrations list with ``event_level=None``.
    """

    import sys

    from worker.core import config as cfg
    from worker.core import observability as obs

    monkeypatch.setattr(
        cfg.settings,
        "sentry_dsn",
        type("DSN", (), {"get_secret_value": lambda self: "https://x@example.io/1"})(),
    )

    fake_sdk = MagicMock()
    fake_celery_integration = MagicMock()

    captured_logging_init: dict[str, Any] = {}

    class _FakeLoggingIntegration:
        def __init__(self, *, level: Any = None, event_level: Any = None) -> None:
            captured_logging_init["level"] = level
            captured_logging_init["event_level"] = event_level

    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
    monkeypatch.setitem(
        sys.modules,
        "sentry_sdk.integrations.celery",
        MagicMock(CeleryIntegration=fake_celery_integration),
    )
    monkeypatch.setitem(
        sys.modules,
        "sentry_sdk.integrations.logging",
        MagicMock(LoggingIntegration=_FakeLoggingIntegration),
    )

    obs.init_sentry_if_configured()

    fake_sdk.init.assert_called_once()
    assert captured_logging_init["event_level"] is None, (
        "LoggingIntegration must be configured with event_level=None "
        "or task-side logger.exception calls will create duplicate Sentry events"
    )


def test_sentry_before_send_strips_frame_locals() -> None:
    """Codex round-8 P1 (mirror of the api fix): even with
    ``include_local_variables=False`` set on init, scrub frame ``vars``
    in the before_send hook as defense-in-depth — a Gemma SDK error's
    stack could otherwise expose ``api_key`` or scanner locals.
    """

    from worker.core.observability import _sentry_before_send

    event = {
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": "gemma call failed",
                    "stacktrace": {
                        "frames": [
                            {
                                "function": "scan_file",
                                "vars": {
                                    "api_key": "should-not-ship",
                                    "file_content": "import secrets\n…",
                                },
                            },
                        ]
                    },
                }
            ]
        },
    }

    cleaned = _sentry_before_send(event, {})
    frame = cleaned["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "vars" not in frame
    assert frame["function"] == "scan_file"


def test_sentry_before_send_redacts_api_key_in_exception_value() -> None:
    """Codex round-4: Sentry's CeleryIntegration captures exceptions via
    ``event_from_exception`` — bypassing our log-side scrub. The
    ``before_send`` hook is the last line of defense for ``AIza…`` shapes
    in the event payload (exception messages, breadcrumbs, log entries).
    """

    from worker.core.observability import _sentry_before_send

    leaky = "AIza" + "z" * 35
    event: dict[str, Any] = {
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": f"Gemma call failed for {leaky}",
                    "stacktrace": {"frames": [{"vars": {"url": f"https://api/?key={leaky}"}}]},
                }
            ]
        },
        "breadcrumbs": {
            "values": [{"message": f"sent request with {leaky}"}],
        },
        "extra": {"context": [f"context line with {leaky}", "ok"]},
    }

    cleaned = _sentry_before_send(event, {})

    serialized = json.dumps(cleaned)
    assert leaky not in serialized, f"API key survived sentry before_send scrub: {serialized!r}"
    # All four sites should be redacted.
    assert cleaned["exception"]["values"][0]["value"].startswith("Gemma call failed")
    assert "AIza<redacted>" in cleaned["exception"]["values"][0]["value"]
    assert "AIza<redacted>" in cleaned["breadcrumbs"]["values"][0]["message"]
    assert "AIza<redacted>" in cleaned["extra"]["context"][0]
    # Non-string siblings stay intact.
    assert cleaned["extra"]["context"][1] == "ok"


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
