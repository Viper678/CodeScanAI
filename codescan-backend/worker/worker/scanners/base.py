"""Scanner protocol + shared dataclasses.

A scanner takes a file's content + a per-call ``ScanContext`` and returns a
``ScanCallResult`` (in-memory ``Finding`` rows + token / latency telemetry).
The orchestrator owns translation to the persistence layer (``ScanFinding``
ORM rows + ``scan_files`` row updates) — scanners stay pure-ish so they can
be unit-tested without DB or Celery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Finding:
    """In-memory finding produced by any scanner.

    Converted to a ``ScanFinding`` row by the orchestrator.
    """

    title: str
    message: str
    recommendation: str | None
    severity: Literal["critical", "high", "medium", "low", "info"]
    line_start: int
    line_end: int
    rule_id: str | None
    confidence: float | None


@dataclass(frozen=True)
class KeywordsConfig:
    """User-supplied keyword config carried through ``ScanContext``.

    Mirrors ``scan.keywords`` JSONB shape; deserialized by the orchestrator.
    """

    items: list[str]
    case_sensitive: bool
    regex: bool


@dataclass(frozen=True)
class ScanContext:
    """Per-call context passed to scanners. Read-only.

    ``keywords`` is only populated when the scanner being invoked is the
    keyword scanner; ``None`` for security / bugs.
    """

    relative_path: str
    language: str | None
    keywords: KeywordsConfig | None


@dataclass(frozen=True)
class ScanCallResult:
    """What a scanner returns. Tokens/latency are 0 for keywords (no LLM)."""

    findings: list[Finding]
    tokens_in: int
    tokens_out: int
    latency_ms: int


class Scanner(Protocol):
    """Common shape every scanner implements."""

    name: str

    def scan_file(self, content: str, ctx: ScanContext) -> ScanCallResult: ...
