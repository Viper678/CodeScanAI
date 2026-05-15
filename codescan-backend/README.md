# CodeScan Backend (api + worker)

FastAPI + Celery worker stack that handles uploads, extraction, and LLM-driven
security/bugs scanning for CodeScan. Postgres holds state (uploads, files,
scans, findings), Redis serves as the Celery broker (and rate-limit /
correlation cache), and either local disk or Google Cloud Storage backs the
upload + extracted-file artifacts.

## Layout

- `api/` — FastAPI service (entrypoint `app.main:app`)
- `worker/` — Celery worker (entrypoint `worker.celery_app`)

Both services share the same Postgres schema (managed by `api/alembic/`) and
the same Redis instance via key-prefix isolation.

## Quick start (development)

The compose stack for the backend lives here:

```bash
cd codescan-backend
docker compose up --build
```

That brings up `api + worker + postgres + redis`. The frontend has its
own compose stack under `codescan-frontend/`; bring it up separately for
the full local dev experience (or run `make dev` from the monorepo root
to chain both).

The API is reachable at <http://localhost:8000> (OpenAPI docs at `/docs`); the
worker is headless and only emits structured logs.

## Make targets

Run these from the monorepo root:

- `make lint-api` — ruff + black + mypy (`--strict`) for `api/`
- `make lint-worker` — ruff + black + mypy (`--strict`) for `worker/`
- `make test-api` — pytest for `api/` (unit + integration)
- `make test-worker` — pytest for `worker/` (unit + integration)

The make targets re-sync the uv lockfile before each step, so the venvs stay
consistent with `pyproject.toml` between runs.

## Environment

The canonical list of backend environment variables (and their defaults)
lives in `codescan-backend/.env.example`. Copy it to `.env` next to the
compose file:

```bash
cp codescan-backend/.env.example codescan-backend/.env
```

The most important knob for local development is:

- `LLM_MOCK_MODE=true` — short-circuits the Gemma client with a deterministic
  in-process transport so security/bugs scans produce canned findings without
  needing a reachable vLLM endpoint. Used by the Playwright e2e suite for the
  same reason.

Other notable variables: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`,
`STORAGE_BACKEND` (`local` | `gcs`), `RETENTION_DAYS`, `LOG_LEVEL`.

## Docs

Architecture, API contracts, schema, deployment, and security notes all live
in the top-level `docs/` directory:

- `docs/ARCHITECTURE.md` — system shape
- `docs/API.md` — HTTP contracts (routes, payloads, errors)
- `docs/SCHEMA.md` — Postgres tables and relationships
- `docs/FILE_HANDLING.md` — extraction, safety caps, storage layout
- `docs/SECURITY.md` — auth, rate limiting, secret handling
- `docs/DEPLOYMENT.md` — production deploy + GCP/GKE target
- `docs/SCAN_RULES.md` — scanner contracts and token budgets

This README is intentionally short — orientation only, not a full guide.
