# Scan Rules

This is the contract between the worker and Gemma. Treat the prompts and JSON schemas in this file as **versioned**: any change requires bumping `PROMPT_VERSION` and is recorded in `scans.model_settings`.

`PROMPT_VERSION = "v1"` for everything below.

---

## Common scan envelope

Every per-file scan call uses:

- **Model:** `gemma-4-31b-it`
- **Mode:** structured JSON output (Gemma 4 supports native JSON / function-calling).
- **Temperature:** 0.0 (we want determinism for findings, not creativity).
- **Max output tokens:** 4096.
- **System prompt:** scan-type-specific (below).
- **User prompt:** templated:
  ```
  File: {relative_path}
  Language: {language or "unknown"}
  
  ```{language}
  {file_contents_with_line_numbers}
  ```
  ```
- File contents are prefixed with line numbers (`   1 │ import os` etc.) so the model can reliably reference line ranges. Keep ` │ ` separator consistent — strip it server-side after parsing.

---

## Token budget & chunking

Gemma 4 31B has a **256K** context window. In practice, we cap per-call input at **120K tokens** to leave headroom and keep latency reasonable.

- Estimate tokens with `~chars/4` heuristic before the call (cheap; refined with the SDK's token counter when needed).
- If a file fits → one call.
- If it doesn't → split into overlapping windows of 100K tokens with 5K-token overlap. Each window is scanned independently. Findings are deduplicated post-hoc by `(rule_id, line_start, line_end, title)`.
- Files > `MAX_SCAN_FILE_SIZE` (1 MB) are skipped (see `FILE_HANDLING.md`); they shouldn't reach the chunker.

---

## Scan type 1 — Security

### Purpose
Identify common security weaknesses in source code: injection, hardcoded secrets, weak cryptography, insecure deserialization, SSRF, path traversal, missing authn/z checks, unsafe regex, insecure defaults, dangerous APIs.

### System prompt (verbatim)

```
You are a senior application security engineer reviewing code for vulnerabilities.

You will be given a single source file. Identify concrete, exploitable security
issues in this file. Do NOT report style issues, performance issues, or generic
"this could be improved" comments.

For each issue you report:
- Cite the exact line range that contains the vulnerability.
- Use a severity from: critical, high, medium, low, info.
  - critical: directly exploitable to RCE / auth bypass / mass data leak
  - high:     exploitable with realistic preconditions
  - medium:   weakness that contributes to risk
  - low:      hardening opportunity
  - info:     informational, no exploit path
- If it maps to a CWE, include it as rule_id (e.g. "CWE-89").
- Be conservative. False positives are worse than false negatives here.

Respond ONLY with JSON matching this schema:
{
  "findings": [
    {
      "title": string (≤ 120 chars),
      "message": string (≤ 1000 chars, explain why this is a vulnerability),
      "recommendation": string (≤ 500 chars, concrete fix),
      "severity": "critical"|"high"|"medium"|"low"|"info",
      "line_start": integer (1-indexed),
      "line_end": integer (1-indexed, inclusive),
      "rule_id": string|null,
      "confidence": number between 0 and 1
    }
  ]
}

If you find no issues, return {"findings": []}. Do not invent issues.
```

### Output validation
- Pydantic schema mirrors the JSON.
- Reject any finding with `line_start > line_end` or out-of-bounds line numbers.
- Reject any with `severity` outside the enum (re-prompt once with the error, then fail the file if still bad).

---

## Scan type 2 — Bug report

### Purpose
Logic bugs, null derefs, off-by-one, race conditions, resource leaks, missing error handling, dead code that hides bugs, incorrect API usage. Distinct from security — overlap goes to whichever fits better.

### System prompt (verbatim)

```
You are a senior software engineer doing a careful bug-hunting code review.

You will be given a single source file. Identify concrete bugs: code that is
incorrect, will crash, leaks resources, has race conditions, mishandles errors,
has off-by-one errors, has unreachable / dead branches that hide bugs, or
misuses APIs.

Do NOT report:
- Security issues (those are handled separately).
- Style preferences.
- Performance suggestions unless they cause incorrect behavior under load.
- "Could be more readable" comments.

For each bug:
- Cite the exact line range.
- Severity rubric:
  - critical: certain crash on common path / data corruption
  - high:     incorrect behavior with realistic inputs
  - medium:   bug under specific conditions / edge cases
  - low:      latent bug, unlikely path
  - info:     suspicious code worth a look, low confidence
- Be conservative. False positives undermine trust.

Respond ONLY with JSON matching this schema:
{
  "findings": [
    {
      "title": string (≤ 120 chars),
      "message": string (≤ 1000 chars),
      "recommendation": string (≤ 500 chars),
      "severity": "critical"|"high"|"medium"|"low"|"info",
      "line_start": integer,
      "line_end": integer,
      "rule_id": null,
      "confidence": number between 0 and 1
    }
  ]
}

If you find no bugs, return {"findings": []}.
```

---

## Scan type 3 — Keywords

This one is **not** an LLM scan in the same sense — it's a deterministic regex/substring search done in the worker, using Python's `re`. The Gemma model is **not** called.

Why deterministic? The user gave us exact keywords. An LLM would be slower, more expensive, and worse at this.

### Algorithm

```python
def keyword_scan(content: str, items: list[str], case_sensitive: bool, regex: bool):
    flags = 0 if case_sensitive else re.IGNORECASE
    findings = []
    for term in items:
        pattern = term if regex else re.escape(term)
        try:
            rx = re.compile(pattern, flags)
        except re.error as e:
            raise InvalidPattern(term, str(e))
        for m in rx.finditer(content):
            line_start = content.count('\n', 0, m.start()) + 1
            line_end = content.count('\n', 0, m.end()) + 1
            findings.append(Finding(
                title=f"Keyword match: {term}",
                message=f'Found "{m.group(0)}" at line {line_start}.',
                recommendation=None,
                severity="info",
                line_start=line_start,
                line_end=line_end,
                rule_id=f"KW:{term}",
                confidence=1.0,
            ))
    return findings
```

### Validation up front (in API)

If `regex=true`, every pattern is compiled at request time inside the API to fail fast with `422 validation_error` per-pattern. This avoids enqueuing a doomed scan.

---

## Cost & token tracking

Per call we record on `scan_files`:
- `tokens_in`, `tokens_out` (from Gemma response usage).
- `latency_ms`.

Aggregated on `scans.model_settings.usage` after completion: `{ "total_tokens_in": N, "total_tokens_out": N, "calls": N }`.

For UI cost preview during file selection, use the heuristic:
- input tokens per file ≈ `size_bytes * 0.27` (rough chars-to-tokens for code)
- output tokens per file ≈ 1500 (mid-estimate)

Don't display a dollar figure unless we have a real price source — show "~480k tokens" instead. **TODO:** decide whether to surface cost or hide it.

---

## Retry logic

Per-file Gemma call retry policy:

| Outcome                              | Action                                                          |
| ------------------------------------ | --------------------------------------------------------------- |
| 2xx, valid JSON                      | persist findings, mark `done`                                   |
| 2xx, invalid JSON                    | one repair retry with appended message: "Your previous response was not valid JSON. Respond ONLY with the JSON object." If still bad: mark `failed`. |
| 4xx (other than 429)                 | mark `failed` — bug on our side, no retry                       |
| 429                                  | wait `Retry-After`, retry up to 5x                              |
| 5xx                                  | exponential backoff (1s, 2s, 4s, 8s, 16s), 5 attempts           |
| network/timeout                      | same as 5xx                                                     |

Celery's retry mechanism handles task-level retries; the per-call retries above happen inside the task.

---

## Determinism / reproducibility

- `model`, `model_settings`, `PROMPT_VERSION` are all stored on the `scans` row.
- The exact prompt text for each version lives in `apps/worker/worker/llm/prompts/v1/`.
- "Re-run scan" creates a new scan row with the same inputs and current PROMPT_VERSION (not necessarily the original) — UI surfaces this so users know.

---

## Adding new scan types later

Add a new value to the `scan_types` enum, add a new system prompt file, register a scanner class implementing:

```python
class Scanner(Protocol):
    name: str  # 'security' | 'bugs' | 'keywords' | new
    async def scan_file(self, content: str, ctx: ScanContext) -> list[Finding]: ...
```

The orchestrator dispatches to the right scanner based on `scan_types`.
