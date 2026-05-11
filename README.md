# CodeScan

> **TODO:** rename project. Placeholder: **CodeScan**.

CodeScan is a web app that lets a developer upload a codebase (zip or loose files), select the files they care about, and run one or more LLM-powered scans against them: **security**, **bug report**, and **keyword** scans. Results are normalized, filterable, and exportable.

The model used for analysis is **Gemma 4 31B** (Google AI Studio API, 256K context).

---

## Features (v1)

- Email + password auth (bcrypt + JWT, refresh-rotation)
- Upload a `.zip` or one-or-more individual source files (≤ 100 MB zip / ≤ 50 MB per file)
- Server-side extraction with zip-bomb / path-traversal protection
- Hydrated directory tree in the UI with sane default exclusions and tri-state checkbox selection
- Three orthogonal scan types per run:
  1. **Security scan** (OWASP-style: injections, hardcoded secrets, weak crypto, etc.)
  2. **Bug report scan** (null derefs, off-by-one, race conditions, resource leaks, logic bugs)
  3. **Keyword scan** (user-supplied keywords / phrases — case sensitivity & regex toggle)
- Async scan execution via Celery; per-file progress streamed back over polling (SSE optional later)
- Findings table with severity, file/line, snippet, and remediation hint
- Export findings to JSON / CSV / SARIF (SARIF can ship in v1.1)

---

## Tech stack

| Layer       | Choice                                           | Why                                                |
| ----------- | ------------------------------------------------ | -------------------------------------------------- |
| Frontend    | Next.js 14 (App Router), TS, Tailwind, shadcn/ui | Fast iteration, strong typing, clean primitives    |
| State       | TanStack Query + Zustand                         | Server cache + small client store                  |
| Backend     | FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic   | Modern Python, async, typed, migrations            |
| Worker      | Celery 5 + Redis broker                          | Mature, observable, retries, parallelism           |
| DB          | Postgres 16                                      | Relational, JSONB for finding metadata             |
| Cache/Queue | Redis 7                                          | Broker + cache + transient state                   |
| LLM         | Gemma 4 31B via vLLM (OpenAI-compatible HTTP)    | 256K context, JSON-structured output, code-strong  |
| Container   | Docker + docker-compose                          | Identical local / prod runtime                     |

---

## Repository layout

```
codescan/
├── README.md                       # this file
├── docker-compose.yml              # local + prod
├── .env.example
├── apps/
│   ├── api/                        # FastAPI service
│   │   ├── pyproject.toml
│   │   ├── alembic/
│   │   └── app/
│   │       ├── main.py
│   │       ├── core/               # config, security, db, deps
│   │       ├── models/             # SQLAlchemy
│   │       ├── schemas/            # Pydantic
│   │       ├── routers/            # FastAPI routers
│   │       ├── services/           # business logic
│   │       └── tests/
│   ├── worker/                     # Celery app
│   │   ├── pyproject.toml
│   │   └── worker/
│   │       ├── celery_app.py
│   │       ├── tasks/              # scan tasks
│   │       ├── llm/                # Gemma client + prompts
│   │       ├── scanners/           # security, bug, keyword
│   │       └── tests/
│   └── web/                        # Next.js
│       ├── package.json
│       ├── app/
│       ├── components/
│       ├── lib/
│       └── tests/
└── docs/
    ├── ARCHITECTURE.md
    ├── SCHEMA.md
    ├── API.md
    ├── FLOW.md
    ├── UI_DESIGN.md
    ├── FILE_HANDLING.md
    ├── SCAN_RULES.md
    ├── TASKS.md
    ├── WORKFLOW.md
    ├── SECURITY.md
    ├── DEPLOYMENT.md
    ├── TESTING.md
    └── CONTRIBUTING.md
```

---

## Quick start (local)

```bash
cp .env.example .env
# set LLM_BASE_URL (or use LLM_MOCK_MODE=true for testing without a real LLM)
docker compose up --build
```

Then:

- Web → http://localhost:3000
- API → http://localhost:8000 (docs at `/docs`)
- Postgres → `localhost:5432`
- Redis → `localhost:6379`

### Tests

```bash
make lint        # ruff + black + mypy + prettier + eslint + tsc
make test        # pytest (api + worker) + vitest (web)
make e2e-up      # bring up docker-compose with mocked Gemma
make e2e         # run the Playwright happy-path suite (headless)
make e2e-ui      # same suite, headed + Playwright UI mode
make e2e-down    # tear down the e2e stack and volumes
```

The Playwright suite drives the full register → upload → scan → findings →
export journey end-to-end. Real Gemma is replaced by a deterministic
fixture transport (`LLM_MOCK_MODE=true`) so CI stays offline and finishes
in well under 10 minutes; failures upload `playwright-report/` and
`test-results/` (which carries the trace files) as a CI artifact.

---

## Where to start reading

If you are an AI agent picking up work on this project, read in this order:

1. `docs/ARCHITECTURE.md` — system shape
2. `docs/FLOW.md` — what happens end-to-end
3. `docs/SCHEMA.md` + `docs/API.md` — data and contracts
4. `docs/TASKS.md` — pick a task
5. `docs/WORKFLOW.md` — branch, build, test, PR
6. `docs/CONTRIBUTING.md` — code conventions

---

## Status

🟡 In active development. Phase 5 hardening complete — rate limiting (T5.1), retention sweep (T5.2), health probes (T5.3), structured logging (T5.4), and the Playwright end-to-end suite (T5.5) are all in.

Shipped:

- Auth: register / login / me, refresh-token rotation + family-based stolen-token revocation
- Upload: `.zip` and loose-file ingest, server-side extraction with zip-bomb / path-traversal / nesting-depth guards, materialized file tree
- Scans API: create / get / list / cancel / delete + recent-files tail (`/scans/{id}/files`) + re-run (`POST /scans/{id}/rerun`); file-ownership validation, `MAX_FILES_PER_SCAN` cap; `GET /scans` honors `?status=` (comma-joined) and `?upload_id=`
- Findings API: cursor-paginated `GET /scans/{id}/findings` with severity / scan_type / file_id filters and `GET /scans/{id}/export?fmt=json|csv` streaming exports
- Worker: Gemma client (vLLM/OpenAI-compat) with retry policy + Pydantic validation; scanner orchestrator (`run_scan` Celery task) with bounded thread pool, cancellation, and per-file findings persistence
- Web: auth pages, full new-scan wizard (upload → file selection → scan config → confirm), the live `/scans/{id}` progress page (status-aware polling, determinate progress + ETA, severity counters, recent-files tail, cancel button), the post-completion findings table (filter chips synced to URL, expandable rows with snippet + recommendation, JSON/CSV export menu), the read-only file viewer at `/uploads/{upload_id}/files/{file_id}` (lazy-loaded CodeMirror 6 with language autodetect, severity-colored gutter markers, sidebar list, scroll-to-line on link-through from findings), and the `/scans` dashboard with status multi-select chips (URL-driven) and a per-row Re-run action that lands on the new scan's progress page
- File-content API: `GET /uploads/{upload_id}/files/{file_id}/content` streams text with size cap + binary guard + path-traversal defense in depth
- Data-retention deletes: `DELETE /uploads/{id}` wipes raw + extracted disk artifacts and cascades through files / scans / scan_files / scan_findings; `DELETE /scans/{id}` cascades scan_files + findings. Both surfaced in the UI as inline two-step confirmation buttons on `/uploads`, `/scans`, the upload tree-preview header, and the scan progress header
- Rate limiting: Redis-backed sliding-window limits on `POST /auth/login` + `/auth/register` (5/IP/min), `POST /uploads` (10/user/hour), and `POST /scans` (30/user/hour); 429 + `Retry-After` header on the standard error envelope, fail-open if Redis is unreachable
- Retention sweep: daily Celery beat task (`worker.tasks.cleanup.cleanup_old_uploads`, ticks at 03:00 UTC) purges uploads older than `RETENTION_DAYS` plus their on-disk artifacts and cascaded files / scans / scan_files / scan_findings; **disabled by default** (operators set a positive integer to enable), per-row resilience so a single bad disk wipe doesn't abort the sweep
- Health probes: cheap `GET /healthz` (process-up) plus dependency-aware `GET /readyz` that pings Postgres + Redis in parallel with a 2-second per-check timeout and returns a stable schema (`{"status","db","redis"}`) on both 200 and 503; docker-compose's api healthcheck now gates on `/readyz` so traffic only flows once the dependency pools are warm
- Structured logging: stdlib `logging` with a JSON formatter on both api and worker; per-request `request_id` (echoed via `X-Request-ID`) + `user_id` correlation on api, `task_id` / `scan_id` / `upload_id` / `file_id` on worker via Celery signals; Google API key scrub at filter + formatter + interpolation layers; `LOG_LEVEL` env-driven and enforced on both root logger and handler so propagated child records actually filter
- End-to-end suite: Playwright covers the full happy path (register → upload sample repo → run scan → see findings → export JSON) with realistic-pacing slowMo so a headed run looks like a real user; mocks Gemma via a worker-side `LLM_MOCK_MODE=true` switch so CI is deterministic and offline; `make e2e` runs the headless suite against a `docker-compose.e2e.yml` stack (under 10 minutes wall-clock), `make e2e-ui` opens the headed Playwright UI locally; failures upload `playwright-report` + `test-results` (with traces) as a CI artifact

Next up: Phase 6 backlog — SARIF export, SSE / WebSocket progress, password reset, and the self-hosted Gemma path.
