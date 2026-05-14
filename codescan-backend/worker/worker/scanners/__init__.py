"""Scanner protocol + per-scan-type implementations used by the orchestrator."""

from __future__ import annotations

from worker.scanners.base import (
    Finding,
    KeywordsConfig,
    ScanCallResult,
    ScanContext,
    Scanner,
)
from worker.scanners.bugs import BugsScanner
from worker.scanners.keywords import InvalidPattern, KeywordScanner, scan_keywords
from worker.scanners.security import SecurityScanner

__all__ = [
    "BugsScanner",
    "Finding",
    "InvalidPattern",
    "KeywordScanner",
    "KeywordsConfig",
    "ScanCallResult",
    "ScanContext",
    "Scanner",
    "SecurityScanner",
    "scan_keywords",
]
