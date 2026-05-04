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
| LLM         | Gemma 4 31B via `google-genai` SDK               | 256K context, JSON-structured output, code-strong  |
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
# fill in GOOGLE_AI_API_KEY at minimum
docker compose up --build
```

Then:

- Web → http://localhost:3000
- API → http://localhost:8000 (docs at `/docs`)
- Postgres → `localhost:5432`
- Redis → `localhost:6379`

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

🟡 In active development. Phase 4 nearly done — findings list/export API (T4.1), results page (T4.2), and the in-app file viewer (T4.3) are in; only dashboard polish (T4.4) remains.

Shipped:

- Auth: register / login / me, refresh-token rotation + family-based stolen-token revocation
- Upload: `.zip` and loose-file ingest, server-side extraction with zip-bomb / path-traversal / nesting-depth guards, materialized file tree
- Scans API: create / get / list / cancel / delete + recent-files tail (`/scans/{id}/files`); file-ownership validation, `MAX_FILES_PER_SCAN` cap
- Findings API: cursor-paginated `GET /scans/{id}/findings` with severity / scan_type / file_id filters and `GET /scans/{id}/export?fmt=json|csv` streaming exports
- Worker: Gemma client (`google-genai`) with retry policy + Pydantic validation; scanner orchestrator (`run_scan` Celery task) with bounded thread pool, cancellation, and per-file findings persistence
- Web: auth pages, full new-scan wizard (upload → file selection → scan config → confirm), the live `/scans/{id}` progress page (status-aware polling, determinate progress + ETA, severity counters, recent-files tail, cancel button), the post-completion findings table (filter chips synced to URL, expandable rows with snippet + recommendation, JSON/CSV export menu), and the read-only file viewer at `/uploads/{upload_id}/files/{file_id}` (lazy-loaded CodeMirror 6 with language autodetect, severity-colored gutter markers, sidebar list, scroll-to-line on link-through from findings)
- File-content API: `GET /uploads/{upload_id}/files/{file_id}/content` streams text with size cap + binary guard + path-traversal defense in depth

Next up: T4.4 dashboard polish (`/scans` filters + re-run action) closes out Phase 4.
