# GCP migration

Plan for taking the current docker-compose-only codebase to the approved GCP shape: GKE Standard + GPU node pool (vLLM Gemma) + Memorystore + Cloud SQL + GCS. Sourced from the audit on 2026-05-08.

> One task = one branch = one PR. Same workflow as `docs/TASKS.md`. Squash-merge.

---

## Target architecture (as approved)

| Layer | Choice | Notes |
|---|---|---|
| Compute (apps) | GKE Standard, regional, private; node pool `n2-standard-4 × 3` | api / worker / web |
| Compute (LLM) | GPU node pool, `g2-standard-48` (4× L4) | self-hosted Gemma on vLLM, tensor-parallel = 4 |
| Cache / queue | Memorystore for Redis | Celery broker + result + rate-limit |
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

## Open decisions (resolve before starting Phase A)

These block scoping for the items they tag.

### D1 — Memorystore product
**Pick:** "Memorystore for Redis" (legacy / non-cluster) **or** "Memorystore for Redis Cluster"?

The cost calculator shows the Cluster product. Legacy supports DB 0-15 natively; Cluster supports DB 0 only and constrains Celery's broker (BLPOP across queues needs same hash slot — a real Celery + cluster gotcha).

**Recommendation:** legacy Memorystore for Redis. Same Standard-Small footprint (~₹20.5K/mo line item), eliminates the cluster-mode work in M3.

→ Affects scope of **M3**.

### D2 — Storage backend strategy
**Pick:** Native GCS SDK (Path B) **or** GCS Fuse CSI driver (Path A)?

Fuse keeps existing `Path` code mostly intact but every file open is an HTTP roundtrip — a 200-file scan would feel terrible. Native SDK is more code but better runtime.

**Recommendation:** native SDK with a `STORAGE_BACKEND=local|gcs` feature flag so local dev keeps working without GCS.

→ Affects scope of **M2**.

### D3 — vLLM image / quantization
Gemma 4 31B fits 2× L4 with int8/AWQ; the approved 4× L4 has plenty of headroom for full-precision. Decide once based on cost vs latency target.

→ Doesn't block code; affects only the GKE manifest for the vLLM Deployment.

### D4 — Production domain
Need the prod domain to bake `NEXT_PUBLIC_API_BASE_URL` at web image build time, set `CORS_ALLOW_ORIGINS`, and configure the Google-managed cert.

→ Blocks **M7** and **M8** end-to-end test.

### D5 — Workload Identity vs static service-account keys
Recommend Workload Identity (no key files, IAM-bound to the k8s SA). Affects how api/worker authenticate to Cloud SQL, GCS, Secret Manager.

→ Affects **B2**, **B3**, **B5**.

---

## Phase A — Code changes (must-do before deploy)

Roughly 5-7 days of focused work, parallelizable in places.

### M1 — Worker LLM client: google-genai → vLLM
- **Goal:** Worker calls Gemma via vLLM's OpenAI-compatible HTTP API instead of `google-genai` SDK.
- **AC:**
  - `apps/worker/worker/llm/client.py::_DefaultGemmaTransport` rewritten to call `${LLM_BASE_URL}/v1/chat/completions`.
  - Structured JSON output via vLLM's `guided_json` extra param + existing JSON schema, or `response_format={"type":"json_object"}` + the existing repair loop.
  - New env: `LLM_BASE_URL` (default `http://vllm.llm.svc.cluster.local:8000/v1`); drop `GOOGLE_AI_API_KEY` from worker config and `.env.example`.
  - Retry policy preserved (429, 5xx, invalid JSON repair).
  - `LLM_MOCK_MODE=true` (T5.5) keeps working unchanged.
  - Prompts (`apps/worker/worker/llm/prompts/v1/{security,bugs}.txt`) reviewed / tweaked for vLLM's chat template if needed; bumped to `v2/` if substantive.
  - Live-LLM integration test (`apps/worker/tests/integration/test_gemma_real.py`) re-pointed at a vLLM endpoint behind a marker gate.
- **Touches:** `apps/worker/worker/llm/{client.py, mock_transport.py}`, `apps/worker/worker/core/config.py`, `apps/worker/pyproject.toml` (drop `google-genai`, add `openai` or `httpx`), `.env.example`, `docker-compose.yml`.
- **Depends on:** D3.

### M2 — Storage abstraction: /data filesystem → GCS
- **Goal:** Uploads + extracts live in GCS in prod; local filesystem still works for dev/CI.
- **AC:**
  - New `apps/worker/worker/storage/` (or shared) module with a `Storage` interface and two impls: `LocalStorage` (current behavior) and `GcsStorage` (using `google-cloud-storage`).
  - `STORAGE_BACKEND=local|gcs` env switch; `STORAGE_BUCKET` for GCS.
  - `upload_service.UploadService._raw_upload_path` and `_wipe_upload_artifacts` go through the abstraction.
  - `prepare_upload._extract_root_for` and `safe_extract` write through the abstraction.
  - `run_scan._FilePlan.abs_path` replaced by a storage-relative key + a `read_text()` helper that streams from GCS or local.
  - `cleanup.cleanup_old_uploads` deletes through the abstraction.
  - File-content endpoint (`apps/api/app/routers/files.py`) streams from the abstraction.
  - Existing zip-safety checks (path traversal, symlinks, zip-bomb ratio, nesting depth) still run before uploading to GCS.
  - All existing tests pass against `LocalStorage`; new tests against `GcsStorage` with a fake (e.g. `pytest-gcp-storage` or in-process bucket fake).
- **Touches:** `apps/api/app/services/upload_service.py`, `apps/api/app/routers/{uploads.py, files.py}`, `apps/worker/worker/files/safety.py`, `apps/worker/worker/tasks/{prepare_upload.py, run_scan.py, cleanup.py}`, new `apps/{api,worker}/{app,worker}/storage/`.
- **Depends on:** D2.

### M3 — Redis: 3 DBs → 1 DB on a single Memorystore
- **Goal:** All Redis usage (rate limit, Celery broker, Celery result) coexists on DB 0 of a single Memorystore instance.
- **AC (assumes D1 = legacy Memorystore):**
  - `redis_url`, `celery_broker_url`, `celery_result_backend` all default to `redis://...:6379/0`; key prefixes via Celery `broker_transport_options.global_keyprefix` and `result_backend_transport_options.global_keyprefix`.
  - Rate-limit prefix already supported via `rate_limit_key_namespace` (T5.1).
  - Smoke test: rate limit + Celery task enqueue + result retrieval all hit the same Redis without key collision.
- **AC (if D1 = Cluster):** add hash-tag to queue names (`{celery}.default`) so all broker keys land in one slot; verify with `redis-cli --cluster check`.
- **Touches:** `apps/api/app/core/config.py`, `apps/worker/worker/{core/config.py, celery_app.py}`, `.env.example`.
- **Depends on:** D1.

### M4 — Cloud SQL connection
- **Goal:** Api connects to Cloud SQL via private IP from inside the GKE VPC.
- **AC:**
  - Connection string format works with Cloud SQL's private IP (zero code change beyond `DATABASE_URL` env).
  - Cloud SQL Auth Proxy decision: skip (private IP is enough) unless we need IAM auth — defer to a follow-up.
  - Pool sizing reviewed (Cloud SQL has connection caps; tune `pool_size` / `max_overflow`).
- **Touches:** `apps/api/app/core/db.py` (only if pool tuning), `.env.example` docs.
- **Depends on:** B2 (VPC peering set up).

### M5 — Alembic migrations as a Kubernetes Job
- **Goal:** Migrations run exactly once per release, not per api pod startup.
- **AC:**
  - `apps/api/Dockerfile` no longer chains `alembic upgrade head` into the entrypoint.
  - New `deploy/k8s/migrate-job.yaml` (or Helm chart equivalent) that runs `alembic upgrade head` against Cloud SQL.
  - GH Actions / Cloud Build deploy step waits for the Job to complete before rolling the api Deployment.
  - Local docker-compose still runs migrations on `api` startup (override file or script wrapper).
- **Touches:** `apps/api/Dockerfile`, deploy manifests, CI workflow.
- **Depends on:** M4 (DB reachable).

### M6 — Beat task split
- **Goal:** Exactly one beat scheduler runs across all worker replicas; cleanup task fires once daily, not N times.
- **AC:** Either:
  - **Option A:** Two Deployments — `worker` (replicas=N, command without `--beat`) and `worker-beat` (replicas=1, command with `--beat`).
  - **Option B:** Switch to `celery-redbeat` (Redis-backed lock); single deployment with replicas=N.
  - Smoke test in staging: `progress_total` of the cleanup metric increments exactly once per day with N=2 worker replicas.
- **Touches:** `apps/worker/Dockerfile` (split CMD), deploy manifests, `apps/worker/pyproject.toml` if redbeat.
- **Depends on:** none.

### M7 — Web: prod build (`pnpm build && pnpm start`)
- **Goal:** Web image runs Next.js standalone build, not `pnpm dev`.
- **AC:**
  - `apps/web/Dockerfile` switches CMD to `pnpm build` at build time + `pnpm start` (or Next.js standalone output) at run time.
  - Multi-stage build: builder stage runs `pnpm build` with `NEXT_PUBLIC_API_BASE_URL` passed as `--build-arg`, final stage is the slim runtime.
  - Healthcheck still works (Next.js prod server responds on `/`).
  - Local `docker compose up` still works (dev override keeps `pnpm dev`).
- **Touches:** `apps/web/Dockerfile`, `docker-compose.override.yml`, deploy manifests with `--build-arg`.
- **Depends on:** D4.

### M8 — Prod cookie + CORS config
- **Goal:** Cookies + CORS configured for the actual prod domain over HTTPS.
- **AC (env-only, no code):**
  - `COOKIE_SECURE=true` (already default).
  - `COOKIE_SAMESITE=lax`.
  - `COOKIE_DOMAIN=<prod-domain>`.
  - `CORS_ALLOW_ORIGINS=https://<prod-domain>` (comma-separated supported per PR #58).
  - HTTPS LB sets `X-Forwarded-Proto: https`; api trusts it (verify via integration test — currently we don't enforce this via TrustedHost middleware — see "Out of scope" below).
- **Touches:** Helm values / k8s ConfigMap. **No code changes.**
- **Depends on:** D4.

### M9 — Secret Manager integration
- **Goal:** `JWT_SECRET`, DB password, any LLM auth token come from Secret Manager.
- **AC (env-only if Workload Identity + External Secrets Operator):**
  - Secrets created in Secret Manager.
  - ESO syncs them to k8s Secrets, mounted as env on the api/worker pods.
  - **No api/worker code changes** — pydantic-settings still reads from env.
- **AC (if direct SDK integration desired):** small `apps/api/app/core/secrets.py` that fetches at startup and stuffs into env before `Settings()` instantiates. Not recommended for v1.
- **Touches:** Helm values / k8s manifests; optionally `apps/api/app/core/`.
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

- **Resolve D1, D2, D3, D4, D5 first.** They scope the rest.
- **M1 (vLLM swap) is the smallest standalone PR** and is gated behind `LLM_MOCK_MODE` for tests — good first move to de-risk the LLM path.
- **M2 (GCS) is the biggest** — split into multiple PRs if needed (storage abstraction first, then per-call site migration behind the flag).
- **M3 / M4 / M8 / M9 are env-/config-only** once D1 is settled — fast.
- **M5 / M6 / M7 are independent** — can be done in any order, parallel with M1/M2.
- **Phase B can start in parallel with Phase A** as long as the infra owner has the design.
- **C1 (staging deploy + e2e) is the integration gate.** Don't cut over until staging passes the e2e suite end-to-end with the real vLLM (not the mock).
