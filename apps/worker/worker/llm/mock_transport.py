"""Static-fixture Gemma transport for end-to-end testing.

Activated via ``LLM_MOCK_MODE=true`` in the worker environment. The
orchestrator (``run_scan._default_scanner_registry``) substitutes this
transport for ``_DefaultGemmaTransport`` so security/bugs scanners produce
deterministic findings without an outbound HTTP call.

Why it lives here instead of under ``tests/``: the worker container — which
is what Playwright actually exercises — needs to import it at runtime. The
Celery process never imports test modules.
"""

from __future__ import annotations

import json

from worker.llm.client import RawResponse

# Two canned findings per file — one "high" and one "info" — keyed by scan
# type. Line numbers are intentionally low (1-2) so they always fall inside
# the scanned file regardless of size; ``GemmaClient._filter_in_bounds`` drops
# anything past EOF, and an empty-file pre-flight skip means we never call
# this transport with zero lines.
_SECURITY_BODY = json.dumps(
    {
        "findings": [
            {
                "title": "Hardcoded API key",
                "message": (
                    "A literal credential pattern was detected in the source. "
                    "Hardcoded keys leak through version control and CI logs."
                ),
                "recommendation": (
                    "Read the credential from a secrets manager or environment "
                    "variable at runtime."
                ),
                "severity": "high",
                "line_start": 1,
                "line_end": 1,
                "rule_id": "CWE-798",
                "confidence": 0.95,
            }
        ]
    }
)

_BUGS_BODY = json.dumps(
    {
        "findings": [
            {
                "title": "Possible null dereference",
                "message": (
                    "The result of an attribute lookup is used without a "
                    "None-guard. Under failure paths this raises AttributeError."
                ),
                "recommendation": (
                    "Guard the access with an explicit None check or use "
                    "``getattr(..., default=None)``."
                ),
                "severity": "medium",
                "line_start": 1,
                "line_end": 2,
                "rule_id": "BUG-NULL-DEREF",
                "confidence": 0.7,
            }
        ]
    }
)

_EMPTY_BODY = json.dumps({"findings": []})


class MockGemmaTransport:
    """Drop-in transport that returns canned findings.

    The system prompt arrives with a leading marker line of the form
    ``# scan_type: security`` (loaded from the prompt file under
    ``worker/llm/prompts/v1/``); we sniff that to pick the right canned
    response. Falling back to "no findings" keeps the contract honest if a
    future prompt version changes the header — e2e still passes, and the
    static check that the mock is wired up at all stays green.
    """

    def __init__(self) -> None:
        # Stateless — instances are cheap. Kept as a class so the worker can
        # hand it to ``GemmaClient(transport=...)`` without further config.
        return

    def __call__(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_output_tokens: int,
    ) -> RawResponse:
        del model, temperature, max_output_tokens  # unused — fixed canned output
        scan_type = _detect_scan_type(system_prompt)
        if scan_type == "security":
            text = _SECURITY_BODY
        elif scan_type == "bugs":
            text = _BUGS_BODY
        else:
            text = _EMPTY_BODY
        # Token counts are illustrative — the orchestrator persists them but
        # the e2e test never asserts on token math.
        approx_in = max(len(user_prompt) // 4, 1)
        approx_out = max(len(text) // 4, 1)
        return RawResponse(text=text, tokens_in=approx_in, tokens_out=approx_out)


def _detect_scan_type(system_prompt: str) -> str | None:
    """Sniff scan type from the system prompt body.

    The shipped v1 bug prompt mentions "Security issues" once (in the
    "do NOT report" list) so a simple ``"security" in text`` would mis-route
    every bug call to the security canned response. Tally each scan-type
    keyword family and pick the dominant one — robust to single negative
    mentions in either prompt.
    """

    text = system_prompt.lower()
    security_score = text.count("security") + text.count("vulnerab")
    bugs_score = text.count("bug") + text.count("crash")
    if security_score > bugs_score:
        return "security"
    if bugs_score > security_score:
        return "bugs"
    return None
