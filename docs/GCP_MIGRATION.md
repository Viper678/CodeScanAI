# GCP migration

Plan for taking the current docker-compose-only codebase to the approved GCP shape: GKE Standard + GPU node pool (vLLM Gemma) + Memorystore + Cloud SQL + GCS. Sourced from the audit on 2026-05-08.

> One task = one branch = one PR. Same workflow as `docs/TASKS.md`. Squash-merge.

---

## Target architecture (as approved)

| Layer | Choice | Notes |
|---|---|---|
| Compute (apps) | GKE Standard, regional, private; node pool `n2-standard-4 × 3` | api / worker / web |
| Compute (LLM) | GPU node pool, `g2-standard-48` (4× L4) | self-hosted Gemma on vLLM, tensor-parallel = 4 |
| Cache / queue | Memorystore for Redis (legacy / non-cluster), Standard Tier, 5 GB | Celery broker + result + rate-limit (per D1) |
| Database | Cloud SQL for Postgres 16 | private IP via VPC |
| Object storage | GCS | uploads, extracts, pg_dump backups |
| Secrets | Secret Manager | JWT, DB password, vLLM auth token if any |
| Network / edge | HTTPS LB + Google-managed certs + Cloud Armor; Cloud DNS | |
| Observability | Cloud Logging / Monitoring + Managed Prometheus | api/worker JSON logs already T5.4-compliant |
| Build / CI | Artifact Registry + GH Actions or Cloud Build | |

Cost ceiling per the calculator (2026-05-08, Mumbai/asia-south1, INR): **₹3.85L/mo**.

---

## Readiness summary

**Already production-ready** (no code changes needed):
- Health probes — `/healthz` (liveness) + `/readyz` (DB + Redis, 2s parallel) — T5.3.
- Structured JSON logs with correlation IDs across api + worker — T5.4.
- API-key scrub at filter / formatter / interpolation / final-line layers — T5.4.
- Rate limiting (Redis sliding window, single-key ZADD pipeline → cluster-safe) — T5.1.
- Retention sweep (daily Celery beat, disabled-by-default) — T5.2.
- E2E happy-path suite with mocked LLM (`LLM_MOCK_MODE`) — T5.5.
- Auth, CSRF, refresh-token rotation, cross-user 404-not-403 — Phases 1, 4.

**Needs code changes** — see Phase A below.

**Needs infra wiring only** (no app code) — see Phase B.

---

## Resolved decisions

Settled 2026-05-10. Phase A scoping below reflects these choices.

### D1 — Memorystore product → **Legacy Memorystore for Redis, Standard Tier, 5 GB**

Why not Cluster: the cost calc's Cluster line was 1 shard, which is "cluster mode protocol on a single primary+replica" — all the Celery + Redis-Cluster complexity (hash-tag forcing, `BLPOP` slot constraints, Kombu edge cases) without the multi-shard payoff. Legacy Standard Tier behaves identically to local docker-compose redis: DB 0-15, plain Celery, no protocol gymnastics.

Sizing: 5 GB is comfortable headroom for rate-limit + Celery broker + result backend at our DAU range; we genuinely use <1 GB in practice. Approximate Mumbai price ~₹16K/mo for 5 GB Standard Tier (vs the calc's ~₹20.5K/mo for 6.5 GB Cluster). Switching to Cluster later (if we ever outgrow one shard) is a future migration with hash-tag prep work.

### D2 — Storage backend → **Native GCS SDK + `STORAGE_BACKEND=local|gcs` feature flag**

Native `google-cloud-storage` Python SDK wrapped behind a `Storage` interface. `LocalStorage` impl preserves docker-compose behavior; `GcsStorage` impl handles the prod path. Feature flag means dev/CI keep working without GCS, and the cutover is a single env-var flip.

Rejected GCS Fuse CSI: every file open is an HTTP roundtrip; a 200-file scan would feel awful.

### D3 — vLLM model / quantization → **Full-precision Gemma 4 31B on 4× L4 with tensor-parallel = 4**

Approved infra choice. AWQ/int8 quantization (would fit 2× L4 and ~halve the GPU line item) is filed under "Out of scope" — revisit only if cost-pressured later.

### D4 — Production domain handling → **Same-origin rewrites in Next.js (one image, env-driven proxy)**

The web image always asks for `/api/...` on its own origin. `next.config.js` rewrites proxy that to `${INTERNAL_API_URL}` server-side at request time — runtime env var, not bake-time. Result: **one web image works in any environment** (UAT, prod, future staging) — only the Helm value differs. No `--build-arg NEXT_PUBLIC_API_BASE_URL` per-env builds.

Implementation lives in **M7**. The actual prod URL is still TBD until hosting is set up; doesn't block code work.

Rejected Option A (per-env web image builds): three Dockerfiles' worth of complexity to maintain three near-identical images.

### D5 — Workload Identity vs service-account keys → **TBD; infra owner's call at Phase B time**

Either choice is zero app-code impact (Google SDKs auto-detect the credential mechanism), so deferred. Recommendation when the time comes: Workload Identity (short-lived tokens, no JSON keys to leak/rotate, default for new GKE clusters). But this gets decided alongside B2/B3/B5 wiring, not now.

---

## Phase A — Code changes (must-do before deploy)

Roughly 5-7 days of focused work, parallelizable in places.

### M1 — Worker LLM client: google-genai → vLLM
- **Goal:** Worker calls Gemma via vLLM's OpenAI-compatible HTTP API instead of `google-genai` SDK.
- **AC:**
  - `codescan-backend/worker/worker/llm/client.py::_DefaultGemmaTransport` rewritten to call `${LLM_BASE_URL}/v1/chat/completions`.
  - Structured JSON output via vLLM's `guided_json` extra param + existing JSON schema, or `response_format={"type":"json_object"}` + the existing repair loop.
  - New env: `LLM_BASE_URL` (default `http://vllm.llm.svc.cluster.local:8000/v1`); drop `GOOGLE_AI_API_KEY` from worker config and `.env.example`.
  - Retry policy preserved (429, 5xx, invalid JSON repair).
  - `LLM_MOCK_MODE=true` (T5.5) keeps working unchanged.
  - Prompts (`codescan-backend/worker/worker/llm/prompts/v1/{security,bugs}.txt`) reviewed / tweaked for vLLM's chat template if needed; bumped to `v2/` if substantive.
  - Live-LLM integration test (`codescan-backend/worker/tests/integration/test_gemma_real.py`) re-pointed at a vLLM endpoint behind a marker gate.
- **Touches:** `codescan-backend/worker/worker/llm/{client.py, mock_transport.py}`, `codescan-backend/worker/worker/core/config.py`, `codescan-backend/worker/pyproject.toml` (drop `google-genai`, add `openai` or `httpx`), `.env.example`, `docker-compose.yml`.
- **Depends on:** D3.

### M2 — Storage abstraction: /data filesystem → GCS
- **Goal:** Uploads + extracts live in GCS in prod; local filesystem still works for dev/CI.
- **AC:**
  - New `codescan-backend/worker/worker/storage/` (or shared) module with a `Storage` interface and two impls: `LocalStorage` (current behavior) and `GcsStorage` (using `google-cloud-storage`).
  - `STORAGE_BACKEND=local|gcs` env switch; `STORAGE_BUCKET` for GCS.
  - `upload_service.UploadService._raw_upload_path` and `_wipe_upload_artifacts` go through the abstraction.
  - `prepare_upload._extract_root_for` and `safe_extract` write through the abstraction.
  - `run_scan._FilePlan.abs_path` replaced by a storage-relative key + a `read_text()` helper that streams from GCS or local.
  - `cleanup.cleanup_old_uploads` deletes through the abstraction.
  - File-content endpoint (`codescan-backend/api/app/routers/files.py`) streams from the abstraction.
  - Existing zip-safety checks (path traversal, symlinks, zip-bomb ratio, nesting depth) still run before uploading to GCS.
  - All existing tests pass against `LocalStorage`; new tests against `GcsStorage` with a fake (e.g. `pytest-gcp-storage` or in-process bucket fake).
- **Touches:** `codescan-backend/api/app/services/upload_service.py`, `codescan-backend/api/app/routers/{uploads.py, files.py}`, `codescan-backend/worker/worker/files/safety.py`, `codescan-backend/worker/worker/tasks/{prepare_upload.py, run_scan.py, cleanup.py}`, new `codescan-backend/{api,worker}/{app,worker}/storage/`.
- **Depends on:** D2.

### M3 — Redis: rate-limit + Celery broker + result coexist on one Memorystore
- **Goal:** All Redis usage (rate limit, Celery broker, Celery result) safely shares a single legacy Memorystore for Redis instance via key prefixes — no DB segregation needed since legacy supports DB 0-15 but key-prefixing is cleaner anyway.
- **AC:**
  - `redis_url`, `celery_broker_url`, `celery_result_backend` all default to `redis://…:6379/0`.
  - Celery `broker_transport_options={"global_keyprefix": "celery-broker:"}` and `result_backend_transport_options={"global_keyprefix": "celery-result:"}` so broker / result keys never collide with rate-limit keys.
  - Rate-limit namespace already supported via `rate_limit_key_namespace` (T5.1) — set per-env if multi-tenant ever matters.
  - Local docker-compose still works against single redis (it already runs 3 DBs but moving to /0 + prefixes is harmless).
  - Smoke test: rate limit + Celery task enqueue + result retrieval against one redis instance, verify no key collisions via `redis-cli KEYS "*"`.
- **Touches:** `codescan-backend/api/app/core/config.py`, `codescan-backend/worker/worker/{core/config.py, celery_app.py}`, `.env.example`.
- **Depends on:** none (D1 resolved).

### M4 — Cloud SQL connection
- **Goal:** Api connects to Cloud SQL via private IP from inside the GKE VPC.
- **AC:**
  - Connection string format works with Cloud SQL's private IP (zero code change beyond `DATABASE_URL` env).
  - Cloud SQL Auth Proxy decision: skip (private IP is enough) unless we need IAM auth — defer to a follow-up.
  - Pool sizing reviewed (Cloud SQL has connection caps; tune `pool_size` / `max_overflow`).
- **Touches:** `codescan-backend/api/app/core/db.py` (only if pool tuning), `.env.example` docs.
- **Depends on:** B2 (VPC peering set up).

### M5 — Alembic migrations as a Kubernetes Job
- **Goal:** Migrations run exactly once per release, not per api pod startup.
- **AC:**
  - `codescan-backend/api/Dockerfile` no longer chains `alembic upgrade head` into the entrypoint.
  - New `deploy/k8s/migrate-job.yaml` (or Helm chart equivalent) that runs `alembic upgrade head` against Cloud SQL.
  - GH Actions / Cloud Build deploy step waits for the Job to complete before rolling the api Deployment.
  - Local docker-compose still runs migrations on `api` startup (override file or script wrapper).
- **Touches:** `codescan-backend/api/Dockerfile`, deploy manifests, CI workflow.
- **Depends on:** M4 (DB reachable).

### M6 — Beat task split
- **Goal:** Exactly one beat scheduler runs across all worker replicas; cleanup task fires once daily, not N times.
- **AC:** Either:
  - **Option A:** Two Deployments — `worker` (replicas=N, command without `--beat`) and `worker-beat` (replicas=1, command with `--beat`).
  - **Option B:** Switch to `celery-redbeat` (Redis-backed lock); single deployment with replicas=N.
  - Smoke test in staging: `progress_total` of the cleanup metric increments exactly once per day with N=2 worker replicas.
- **Touches:** `codescan-backend/worker/Dockerfile` (split CMD), deploy manifests, `codescan-backend/worker/pyproject.toml` if redbeat.
- **Depends on:** none.

### M7 — Web: prod build + same-origin API rewrites (one image, runtime-configurable)
- **Goal:** Web image runs Next.js standalone build (not `pnpm dev`) and proxies API calls to a runtime-configurable backend so a single image deploys identically to UAT / prod / future staging.
- **AC:**
  - `codescan-frontend/Dockerfile` becomes multi-stage: builder runs `pnpm build`, final stage runs `pnpm start` (or the Next.js standalone output server).
  - `next.config.js` adds `rewrites()` mapping `/api/:path*` → `${INTERNAL_API_URL}/:path*`. `INTERNAL_API_URL` is read at runtime (server-side), so changing the env doesn't require a rebuild.
  - Web client code uses relative `/api/...` URLs (already does in most places — verify `codescan-frontend/lib/api/client.ts`); drop reliance on `NEXT_PUBLIC_API_BASE_URL`.
  - Healthcheck still works (Next.js prod server responds on `/`).
  - Local `docker compose up` still works (dev override keeps `pnpm dev`; `INTERNAL_API_URL` defaults to `http://api:8000` in the compose env).
  - Single image promoted UAT → prod with no rebuild — only the Helm value of `INTERNAL_API_URL` differs.
- **Touches:** `codescan-frontend/Dockerfile`, `codescan-frontend/next.config.js`, `codescan-frontend/lib/api/client.ts` (drop `NEXT_PUBLIC_API_BASE_URL` references), `docker-compose.{yml,override.yml}`, deploy manifests.
- **Depends on:** none (D4 resolved — runtime rewrites approach unblocks immediately).

### M8 — Prod cookie + CORS config
- **Goal:** Cookies + CORS configured for the actual prod domain over HTTPS.
- **AC (env-only, no code):**
  - `COOKIE_SECURE=true` (already default).
  - `COOKIE_SAMESITE=lax`.
  - `COOKIE_DOMAIN=<prod-domain>`.
  - `CORS_ALLOW_ORIGINS=https://<prod-domain>` (comma-separated supported per PR #58).
  - With M7's same-origin rewrites, the browser's API calls are same-origin so CORS may even be unnecessary for the web → api path; still keep `CORS_ALLOW_ORIGINS` set for defense-in-depth + any direct api consumers (Postman, scripts).
  - HTTPS LB sets `X-Forwarded-Proto: https`; api trusts it (verify via integration test — currently we don't enforce this via TrustedHost middleware — see "Out of scope" below).
- **Touches:** Helm values / k8s ConfigMap. **No code changes.**
- **Depends on:** prod URL value (still TBD — doesn't block code work, only the actual deploy).

### M9 — Secret Manager integration
- **Goal:** `JWT_SECRET`, DB password, any LLM auth token come from Secret Manager.
- **AC (env-only if Workload Identity + External Secrets Operator):**
  - Secrets created in Secret Manager.
  - ESO syncs them to k8s Secrets, mounted as env on the api/worker pods.
  - **No api/worker code changes** — pydantic-settings still reads from env.
- **AC (if direct SDK integration desired):** small `codescan-backend/api/app/core/secrets.py` that fetches at startup and stuffs into env before `Settings()` instantiates. Not recommended for v1.
- **Touches:** Helm values / k8s manifests; optionally `codescan-backend/api/app/core/`.
- **Depends on:** D5.

---

## Phase B — Infra wiring (no app code)

These don't change the codebase but must happen for a green deploy.

| ID | Task | Output |
|---|---|---|
| B1 | GKE cluster + node pools | Cluster + `apps` pool (n2-standard-4 ×3) + `gpu` pool (g2-standard-48 ×1) |
| B2 | VPC, Cloud NAT, private IP for Cloud SQL + Memorystore | VPC peering done |
| B3 | Workload Identity + Google service accounts (api, worker) | k8s SAs bound to GSAs with IAM roles |
| B4 | Artifact Registry repos for api / worker / web / vllm | Build pipeline pushes here |
| B5 | Secret Manager + External Secrets Operator | Secrets synced to k8s |
| B6 | HTTPS LB + Google-managed cert + Cloud Armor + DNS | Public ingress |
| B7 | Helm chart or Kustomize manifests for api / worker / web / vllm | Single deploy unit |
| B8 | vLLM Deployment on GPU pool | OpenAI-compatible endpoint reachable from worker |
| B9 | Managed Prometheus + Cloud Monitoring dashboards | RED metrics + scan duration histogram |
| B10 | HPA configs (api on CPU, worker on Celery queue depth via custom metric) | Auto-scaling |

---

## Phase C — Cutover & verification

| ID | Task |
|---|---|
| C1 | Staging deploy: full GCP stack, run e2e suite against the staging URL |
| C2 | Load test: realistic scan throughput; verify p95 latency targets |
| C3 | Failover drill: kill a node, kill the vLLM pod — assert ✓ recovery |
| C4 | Backup + restore drill: pg_dump → GCS → restore to a fresh Cloud SQL |
| C5 | Production cutover; DNS flip |
| C6 | Post-cutover smoke + 24h watch |

---

## What's NOT changing

- Repository pattern (works against Cloud SQL identically).
- Auth / JWT / CSRF / refresh-token rotation.
- Healthchecks (`/healthz`, `/readyz`).
- Logging shape (JSON + correlation IDs).
- Rate-limit algorithm (single-key sliding window).
- Scanner contracts (`Scanner.scan_file` interface).
- E2E suite (continues to mock the LLM in CI; in staging hits the real vLLM).
- Pydantic-settings env-driven config style.
- Default scan rules / prompts (only template tweaks if vLLM chat template differs).

---

## Out of scope (separate work, called out so we don't forget)

- **`TRUSTED_HOSTS` middleware** — referenced in `.env.example` and `docs/DEPLOYMENT.md` but no `TrustedHostMiddleware` is wired up. Should add when we configure the prod domain.
- **HTTPS-redirect middleware on api** — currently the LB terminates TLS and we trust `X-Forwarded-Proto`. If we ever serve api directly without an LB, would need explicit redirect.
- **OTel / Cloud Trace** — Sentry was stripped intentionally (T5.4 conversation). OTel can be added when there's actual operator intent to instrument.
- **SARIF export** — `docs/TASKS.md` Phase 6 backlog.
- **Per-finding "ignore" / false-positive feedback** — Phase 6 backlog.
- **2× L4 + AWQ-quantized Gemma alternative** — would cut LLM line item ~half. Revisit if cost-pressured.

---

## Sequencing notes

- **D1-D4 resolved (2026-05-10);** D5 is infra-owner's call at Phase B time and doesn't block code. All Phase A work is unblocked.
- **M1 (vLLM swap) is the smallest standalone PR** and is gated behind `LLM_MOCK_MODE` for tests — good first move to de-risk the LLM path.
- **M2 (GCS) is the biggest** — split into multiple PRs if needed (storage abstraction first, then per-call site migration behind the flag).
- **M3 / M4 / M8 / M9 are env-/config-only** — fast.
- **M5 / M6 / M7 are independent** — can be done in any order, parallel with M1/M2.
- **Phase A code work is fully decoupled from Phase B infra** — develop and merge M1-M9 against current docker-compose. K8s + Phase B happens last, alongside the final deploy.
- **C1 (staging deploy + e2e) is the integration gate.** Don't cut over until staging passes the e2e suite end-to-end with the real vLLM (not the mock).
