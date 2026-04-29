# Tasks

Phased plan. Each task is sized for one PR. Tasks within a phase can be parallelized unless marked with a dependency.

Each task has:
- **Goal:** what shipping this means
- **Acceptance criteria:** how we know it's done
- **Touches:** which paths
- **Depends on:** prior task IDs

> Agents: read `WORKFLOW.md` before picking a task. One task = one branch = one PR.

---

## Phase 0 — Bootstrap

### T0.1 — Repo scaffold
- **Goal:** monorepo with `apps/api`, `apps/worker`, `apps/web`, `docs/`, `docker-compose.yml`, `.env.example`, root `README.md`.
- **AC:**
  - `docker compose up` brings up empty-but-running api (200 on `/healthz`), worker (idle), postgres, redis, web (renders blank page).
  - Pre-commit hooks installed: `ruff`, `black`, `mypy`, `prettier`, `eslint`.
  - CI workflow runs lint + type-check on every PR.
- **Touches:** root, all of `apps/*`, `.github/workflows/`.

### T0.2 — Database baseline & Alembic
- **Goal:** SQLAlchemy 2 setup, Alembic configured, first migration creates `users` and `refresh_tokens`.
- **AC:**
  - `alembic upgrade head` works against the compose Postgres.
  - `pytest` skeleton with one passing test that creates a user.
- **Depends on:** T0.1.

### T0.3 — Frontend baseline
- **Goal:** Next.js app with shell layout, Tailwind, shadcn/ui initialized, dark mode default, top bar + sidebar, `/login` and `/register` placeholders.
- **AC:** routes render, shell collapses responsively, no auth wired yet.
- **Depends on:** T0.1.

---

## Phase 1 — Auth

### T1.1 — API: register / login / me
- **Goal:** `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, password hashing (bcrypt cost 12), JWT issuance, httpOnly cookies, rate limiting on login.
- **AC:** all endpoints in `API.md` work end-to-end against compose. Tests cover happy path + wrong-password + duplicate-email.
- **Depends on:** T0.2.

### T1.2 — API: refresh / logout / token rotation
- **Goal:** `POST /auth/refresh` rotates refresh token (old hash revoked, new persisted). `POST /auth/logout` revokes. Stolen-token-detection: if a revoked refresh is presented, revoke entire user's token family.
- **AC:** integration test simulates stolen-token replay → fails + logs out everywhere.
- **Depends on:** T1.1.

### T1.3 — Web: auth pages + session
- **Goal:** working `/login`, `/register`, redirect logic, `useSession` hook, protected routes.
- **AC:** can register, log in, refresh page and stay logged in, log out.
- **Depends on:** T0.3, T1.2.

---

## Phase 2 — Uploads & tree

### T2.1 — API: upload endpoint + storage
- **Goal:** `POST /uploads` with size/type validation, persists to `/data/uploads/`, creates row, enqueues `prepare_upload`.
- **AC:** rejects oversized, wrong-type, malformed multipart. Test uploads a small zip and gets `202 + uuid`.
- **Depends on:** T1.1.

### T2.2 — Worker: zip extraction + safety
- **Goal:** `prepare_upload` task. Implements every safety check in `FILE_HANDLING.md`. Walks tree, classifies files, bulk-inserts `files` rows, sets `uploads.status=ready`.
- **AC:**
  - Unit tests for: zip bomb (compression ratio), path traversal (entry with `..`), absolute path entry, max files, max size, symlink entry — all rejected.
  - Integration test extracts a real small repo and produces correct `files` rows.
  - Migration creates the `uploads` and `files` tables.
- **Depends on:** T2.1.

### T2.3 — API: tree endpoint
- **Goal:** `GET /uploads/{id}/tree` returns flat list per the contract in `API.md`. Includes `is_excluded_by_default` and `excluded_reason`.
- **AC:** returns 404 for other users' uploads. Returns empty `files: []` if not yet ready (with `status` echoed in response). Pagination not needed — capped at 20k entries by upload limits.
- **Depends on:** T2.2.

### T2.4 — Web: upload step (wizard step 1)
- **Goal:** dropzone, progress bar via XHR, polls `GET /uploads/{id}` until `ready`.
- **AC:** drag-drop a zip, see progress, see "extracting…", advance to step 2.
- **Depends on:** T1.3, T2.3.

### T2.5 — Web: directory tree component (wizard step 2)
- **Goal:** virtualized tree, tri-state checkboxes, default-exclusion styling, toolbar (select all / deselect all / reset to defaults / show only selected), keyboard nav, search filter.
- **AC:** unit tests for tri-state math, descendants cascade correctly, keyboard nav matches spec. Manual test on a repo with 10k files: scroll/select stays smooth.
- **Depends on:** T2.3.

---

## Phase 3 — Scans

### T3.1 — Migration + models for scans / scan_files / scan_findings
- **Goal:** ship the schema in `SCHEMA.md` for these three tables; SQLAlchemy models; Pydantic schemas.
- **AC:** alembic migration applies/rolls back cleanly; CRUD repository tests pass.
- **Depends on:** T2.2.

### T3.2 — API: create / get / list / cancel / delete scan endpoints
- **Goal:** all `/scans` endpoints in `API.md` except findings & export. Validates `file_ids` ownership, enforces `MAX_FILES_PER_SCAN`.
- **AC:** integration tests for: create succeeds, create rejects another-user's file_ids (403), create rejects empty scan_types (422), cancel transitions correctly, get returns progress.
- **Depends on:** T3.1.

### T3.3 — Worker: Gemma client + prompts
- **Goal:** module wrapping `google-genai`, env-key configured. Loads system prompts from `apps/worker/worker/llm/prompts/v1/{security,bugs}.txt`. Implements structured-JSON call with retry policy in `SCAN_RULES.md`.
- **AC:** unit-tested with a fake transport — verifies retry on 429/5xx, invalid-JSON repair attempt, persists `tokens_in/out/latency_ms`. Manual integration test against real Gemma in a separate marker-gated test.
- **Depends on:** T3.1.

### T3.4 — Worker: scanner orchestrator + per-scanner implementations
- **Goal:** `run_scan(scan_id)` task that:
  - Loads scan, files; updates status to `running`.
  - For each `scan_files` row, runs the appropriate scanner. Security and bugs go through Gemma; keywords stays in-process.
  - Bounded concurrency via semaphore.
  - On each file completion: insert findings, update progress.
  - On any cancellation flag: exit clean.
- **AC:** end-to-end test on a tiny fixture repo with mocked Gemma returning canned findings. Asserts `scans.status=completed`, findings written correctly.
- **Depends on:** T3.3.

### T3.5 — Web: scan config (wizard step 3) + confirm (step 4)
- **Goal:** scan-type toggle cards, keyword editor with regex/case toggles + validate button, confirm summary, "Start scan" hits `POST /scans`.
- **AC:** keyword regex validator round-trips; can start a scan and lands on progress page.
- **Depends on:** T2.5, T3.2.

### T3.6 — Web: progress page
- **Goal:** polling progress, severity counters, recent-files tail, ETA, cancel button.
- **AC:** progress bar advances during a real scan; cancel works; transition to results once completed.
- **Depends on:** T3.5.

---

## Phase 4 — Results

### T4.1 — API: findings endpoint + export
- **Goal:** `GET /scans/{id}/findings` with filters + cursor pagination. `GET /scans/{id}/export?fmt=json|csv`.
- **AC:** filters compose correctly (severity AND scan_type AND file_id); export produces valid CSV (round-trip parsable).
- **Depends on:** T3.4.

### T4.2 — Web: results page (table + expansion)
- **Goal:** findings table with filters, severity dots, expandable rows showing message/recommendation/snippet with line numbers.
- **AC:** filters drive query params; expansion is keyboard-accessible.
- **Depends on:** T4.1.

### T4.3 — Web: file viewer with inline findings
- **Goal:** `/uploads/{upload_id}/files/{file_id}` route, CodeMirror read-only, gutter markers per finding, sidebar list.
- **AC:** click a finding in the table → opens file viewer scrolled to the line.
- **Depends on:** T4.2.

### T4.4 — Web: dashboard / scan list
- **Goal:** `/scans` table listing past scans with filters. Re-run action (creates a new scan with same inputs).
- **AC:** filtering and re-run both work end-to-end.
- **Depends on:** T4.1.

---

## Phase 5 — Hardening & polish

### T5.1 — Rate limiting
- **Goal:** Redis-backed sliding window limits on auth, uploads, scans per `API.md`.
- **AC:** integration test asserts 429 + `Retry-After` after threshold.
- **Depends on:** T1.2.

### T5.2 — Cleanup beat task
- **Goal:** daily cleanup of uploads older than `RETENTION_DAYS`. Cascades to extracts on disk.
- **AC:** unit tested with frozen time. **TODO:** confirm retention default.
- **Depends on:** T2.2.

### T5.3 — Healthz / readyz
- **Goal:** `/healthz` (process), `/readyz` (db + redis). Compose healthchecks reference `/readyz`.
- **AC:** kill redis → `/readyz` 503 within 5s; restart → 200 again.
- **Depends on:** T0.1.

### T5.4 — Logging & error tracking
- **Goal:** structured JSON logs (request id, user id, scan id) across api + worker. Optional Sentry / OTel hooks behind env flag.
- **AC:** every request log has correlation id; worker logs include `scan_id` / `file_id`.
- **Depends on:** T0.1.

### T5.5 — End-to-end test suite
- **Goal:** Playwright tests covering the full happy path: register → upload sample repo → run scan → see findings → export.
- **AC:** runs in CI in < 10 min.
- **Depends on:** T4.4.

---

## Phase 6 — Nice to have (post-v1 backlog)

- SARIF export
- SSE / WebSocket progress instead of polling
- Password reset / email verification
- Self-hosted Gemma path (vLLM)
- Per-finding "ignore" / "false positive" feedback
- IDE plugin
- Org / team accounts
