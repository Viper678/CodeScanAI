# Testing

## Pyramid

- **Wide base of unit tests.** Pure functions (tree math, exclusion rules, regex validators, JSON-shape validators).
- **Middle layer of integration tests.** API endpoints against a real Postgres + Redis (compose), worker tasks against a real broker. Gemma is mocked.
- **Thin top of end-to-end tests.** Playwright smoke tests for the happy path.

The pyramid shape is non-negotiable: e2e is too slow to be the safety net.

---

## Backend (api + worker)

Stack: `pytest`, `pytest-asyncio`, `httpx.AsyncClient` for API, `pytest-postgresql` (or just compose) for DB, `pytest-redis`.

Layout:
```
codescan-backend/api/tests/
├── conftest.py               # fixtures: db_session, client, authed_client, sample_user
├── unit/
│   ├── test_password.py
│   ├── test_pydantic_schemas.py
│   └── ...
├── integration/
│   ├── test_auth.py
│   ├── test_uploads.py
│   ├── test_scans.py
│   └── test_findings.py
└── fixtures/
    ├── tiny_repo.zip
    ├── zip_bomb.zip          # synthetic
    ├── path_traversal.zip    # synthetic, has ../etc/passwd entry
    └── symlink.zip           # synthetic
```

```
codescan-backend/worker/worker/tests/
├── unit/
│   ├── test_exclusion_rules.py
│   ├── test_zip_safety.py
│   ├── test_keyword_scanner.py
│   ├── test_prompt_loader.py
│   └── test_llm_retry.py
├── integration/
│   ├── test_prepare_upload.py
│   └── test_run_scan.py     # uses fake LLM transport
└── fixtures/
    └── ...
```

### Key fixtures

```python
@pytest.fixture
async def authed_client(client, sample_user):
    """Logs in sample_user and returns an authenticated httpx client."""
    ...

@pytest.fixture
def fake_gemma(monkeypatch):
    """Replace LLM client with a callable that returns canned responses
    based on file path or content. Use for deterministic worker tests."""
    ...
```

### Mocking Gemma

We do **not** call real Gemma in unit / integration tests. The fake transport accepts a `responses` dict keyed by file path. A separate suite of tests marked `@pytest.mark.live_llm` is opt-in (skipped in default CI), runs against the real API with a 1-token-budget guard.

---

## Frontend (web)

Stack: `vitest` + `@testing-library/react` for unit and component tests, `playwright` for e2e.

What gets unit-tested:
- Tree state machine (`getDirState`, `toggleDir`, `cascadeSelection`).
- Regex validator UI logic.
- Polling hook (with mocked timers and fake server).
- Severity sorting / filtering helpers.

What gets e2e-tested:
- One full-happy-path test (`codescan-frontend/e2e/full-scan.spec.ts`) covering all five legs in a single browser session: register → upload sample repo → run a scan covering all three scan types → assert findings render → export JSON and parse the download. Real Gemma is replaced by a worker-side mock transport (`codescan-backend/worker/worker/llm/mock_transport.py`), wired in by `LLM_MOCK_MODE=true` on the e2e compose stack — so the suite is deterministic and offline. The pyramid stays narrow at the top: regressions in form labels, polling, finding rendering, and CSV/JSON export each have unit / integration coverage closer to the source.

Layout:
```
codescan-frontend/
├── tests/                          # vitest unit + component tests
│   ├── auth-redirect.test.ts
│   ├── findings-table.test.tsx
│   └── …
└── e2e/                            # Playwright suite
    ├── full-scan.spec.ts
    ├── global-setup.ts             # rebuilds the sample zip on every run
    └── fixtures/
        ├── build_sample_zip.py     # generates tiny_repo.zip at runtime
        └── tiny_repo.zip           # gitignored — the AIzaSy… literal lives only here
```

### Running e2e locally

The e2e stack runs on alt host ports (web `3010`, api `8010`) so it coexists with a dev stack on `3000` / `8000` — no need to stop dev to run e2e.

```bash
make e2e            # headless run — what CI does
make e2e-ui         # headed + Playwright UI mode for debugging
make e2e-up         # bring the e2e stack up only (auto-runs as a dep of e2e / e2e-ui)
make e2e-down       # tear it down + drop the e2e named volumes
```

`make e2e` and `make e2e-ui` are self-contained: they build the sample-repo zip, bring the compose stack up (`-p codescan-e2e` keeps it isolated from a dev project), wait for healthchecks (`docker compose up --wait`), `pnpm install` on the host so the `playwright` binary resolves, install browser binaries, and run the suite against `http://localhost:3010`.

The Playwright config sets `slowMo: 300ms` so a headed run looks like a real user clicking through (override via `E2E_SLOW_MO_MS=…`). Failures retain a trace artifact in `codescan-frontend/test-results/`; CI uploads `playwright-report/` + `test-results/` as a workflow artifact for post-mortem analysis.

---

## Coverage philosophy

We don't enforce a percentage. We enforce, in code review:

1. Every branch with non-trivial logic has a test (you must point to it in the PR description).
2. Every bug fix ships with a regression test that fails without the fix.
3. Snapshot tests are banned for non-trivial output (they decay into rubber stamps).
4. Tests should fail for one reason. If a test would fail on multiple unrelated changes, it tests too much.

CI does report coverage as a metric, but it does not block.

---

## Test data

- `tiny_repo.zip` — a hand-built fixture with ~20 files in 3 languages, including:
  - one file with a deliberate SQL-injection-looking line
  - one file with a `TODO` for the keyword scanner
  - one file with a deliberate null-deref-looking pattern
  - one binary
  - one inside `node_modules/` (must be excluded by default)
  - one over 1MB (must be excluded by default)
- Synthetic adversarial zips for safety tests, generated by a `make fixtures` target so they're reproducible.

---

## Performance & load (post-v1)

- Locust scenario: 50 concurrent users uploading tiny repos and scanning. Asserts p95 endpoint latencies.
- Worker fan-out test: scan of 500 files completes in < N minutes with 4 workers and mocked Gemma. Sets a baseline; alerts on regression.

---

## Flake policy

- Any test that flakes is **quarantined** (marked `@pytest.mark.flaky` / `.skip` with a linked issue) within 24h of the second flake.
- Quarantined tests are fixed, not ignored. The issue is on the next sprint.
- We do not retry flakes in CI without quarantine — that hides the problem.
