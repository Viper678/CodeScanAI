"""In-process regex keyword scanner. No LLM call.

Algorithm follows docs/SCAN_RULES.md §"Scan type 3 — Keywords" verbatim.
The API validates user-supplied regex at request time (T3.2), so an
``InvalidPattern`` here is defensive — surfaced as a per-file failure rather
than killing the whole run.
"""

from __future__ import annotations

import re
import time

from worker.scanners.base import Finding, ScanCallResult, ScanContext


class InvalidPattern(Exception):
    """Raised when a user-supplied keyword fails to compile as a regex."""

    def __init__(self, term: str, message: str) -> None:
        super().__init__(f"invalid regex {term!r}: {message}")
        self.term = term
        self.message = message


def scan_keywords(
    content: str,
    *,
    items: list[str],
    case_sensitive: bool,
    regex: bool,
) -> list[Finding]:
    """Search ``content`` for each ``items`` term and emit one Finding per match."""

    flags = 0 if case_sensitive else re.IGNORECASE
    findings: list[Finding] = []
    for term in items:
        pattern = term if regex else re.escape(term)
        try:
            rx = re.compile(pattern, flags)
        except re.error as e:
            raise InvalidPattern(term, str(e)) from e
        for m in rx.finditer(content):
            line_start = content.count("\n", 0, m.start()) + 1
            line_end = content.count("\n", 0, m.end()) + 1
            findings.append(
                Finding(
                    title=f"Keyword match: {term}",
                    message=f'Found "{m.group(0)}" at line {line_start}.',
                    recommendation=None,
                    severity="info",
                    line_start=line_start,
                    line_end=line_end,
                    rule_id=f"KW:{term}",
                    confidence=1.0,
                )
            )
    return findings


class KeywordScanner:
    """Adapter so the orchestrator can dispatch keyword scans uniformly."""

    name = "keywords"

    def scan_file(self, content: str, ctx: ScanContext) -> ScanCallResult:
        if ctx.keywords is None:
            # Defensive: orchestrator must populate this when scan_types
            # includes "keywords"; an empty config means "no items".
            return ScanCallResult(findings=[], tokens_in=0, tokens_out=0, latency_ms=0)

        start = time.monotonic()
        findings = scan_keywords(
            content,
            items=ctx.keywords.items,
            case_sensitive=ctx.keywords.case_sensitive,
            regex=ctx.keywords.regex,
        )
        end = time.monotonic()
        return ScanCallResult(
            findings=findings,
            tokens_in=0,
            tokens_out=0,
            latency_ms=int((end - start) * 1000),
        )
