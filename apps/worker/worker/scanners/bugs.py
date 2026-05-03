"""LLM-backed bug-report scanner. Symmetric with :mod:`worker.scanners.security`."""

from __future__ import annotations

from worker.llm.client import GemmaClient
from worker.llm.schemas import LlmFinding
from worker.scanners.base import Finding, ScanCallResult, ScanContext


class BugsScanner:
    """Calls Gemma with the bugs system prompt for one file."""

    name = "bugs"

    def __init__(self, client: GemmaClient) -> None:
        self._client = client

    def scan_file(self, content: str, ctx: ScanContext) -> ScanCallResult:
        result = self._client.scan_file(
            scan_type="bugs",
            relative_path=ctx.relative_path,
            language=ctx.language,
            content=content,
        )
        return ScanCallResult(
            findings=[_to_finding(f) for f in result.findings],
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            latency_ms=result.latency_ms,
        )


def _to_finding(f: LlmFinding) -> Finding:
    return Finding(
        title=f.title,
        message=f.message,
        recommendation=f.recommendation,
        severity=f.severity,
        line_start=f.line_start,
        line_end=f.line_end,
        rule_id=f.rule_id,
        confidence=f.confidence,
    )
